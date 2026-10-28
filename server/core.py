import concurrent.futures
import csv
import fcntl
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
import tempfile
import selectors
from datetime import datetime, timezone
from urllib import request, parse

from .apk import inspect_apk

ROOT = Path(__file__).resolve().parent.parent
KEYS = {'up':19,'down':20,'left':21,'right':22,'ok':23,'source':178,'back':4,'home':3,'volume_up':24,'volume_down':25,
        **{str(n):n+7 for n in range(10)}}
ACTIONS = {'key','restart_app','reboot','shutdown','clear_data','factory_reset','set_time','network_time','install','record'}
RISKY = {'reboot','shutdown','clear_data','factory_reset','install'}
PKG = re.compile(r'^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class Problem(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class Store:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, at TEXT, kind TEXT, device TEXT, detail TEXT, ip TEXT, session TEXT);
          CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS apks(id TEXT PRIMARY KEY, data TEXT NOT NULL);
        ''')
        self.db.commit()

    def all(self, table):
        assert table in ('devices','tasks','apks')
        with self.lock:
            return [json.loads(r['data']) for r in self.db.execute(f'SELECT data FROM {table}')]

    def save(self, table, item):
        assert table in ('devices','tasks','apks')
        with self.lock:
            self.db.execute(f'INSERT OR REPLACE INTO {table} VALUES (?,?)', (item['id'], json.dumps(item, ensure_ascii=False)))
            self.db.commit()

    def event(self, kind, detail, device='', source=None):
        source = source or ('system','system')
        with self.lock:
            self.db.execute('INSERT INTO events(at,kind,device,detail,ip,session) VALUES (?,?,?,?,?,?)',
                            (now(),kind,device,str(detail),*source))
            self.db.commit()

    def events(self):
        with self.lock:
            return [dict(r) for r in self.db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 2000')]

    def backup(self):
        with self.lock:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/'snapshot.sqlite3'
                dest = sqlite3.connect(path)
                try:
                    self.db.backup(dest)
                    dest.execute('PRAGMA journal_mode=DELETE')
                finally:
                    dest.close()
                return path.read_bytes()

    def restore(self, data):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name)/'restore.sqlite3'
        path.write_bytes(data)
        candidate = sqlite3.connect(path)
        try:
            candidate.execute('PRAGMA trusted_schema=OFF')
            if candidate.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise Problem('備份完整性檢查失敗')
            for table in ('devices','tasks','apks'):
                rows = candidate.execute(f'SELECT id,data FROM {table}').fetchall()
                for key, value in rows:
                    obj = json.loads(value)
                    if not isinstance(obj, dict) or obj.get('id') != key:
                        raise Problem('備份資料結構無效')
            candidate.execute('SELECT at,kind,device,detail,ip,session FROM events LIMIT 1')
            # Copy only data into the known schema; never import triggers or executable schema.
            with self.lock:
                self.db.execute('BEGIN')
                try:
                    for table in ('devices','tasks','apks','events'):
                        cols = 'id,data' if table != 'events' else 'id,at,kind,device,detail,ip,session'
                        rows = candidate.execute(f'SELECT {cols} FROM {table}').fetchall()
                        self.db.execute(f'DELETE FROM {table}')
                        self.db.executemany(f'INSERT INTO {table}({cols}) VALUES ({",".join("?" for _ in cols.split(","))})', rows)
                    self.db.commit()
                except Exception:
                    self.db.rollback()
                    raise
        finally:
            candidate.close()
            directory.cleanup()


class Service:
    def __init__(self, data_dir=None, mode='mock'):
        os.umask(0o077)
        self.mode = mode
        self.data_dir = Path(data_dir or os.environ.get('ULTRON_DATA', ROOT/'.runtime')).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.instance_lock = open(self.data_dir/('.'+mode+'.lock'),'a')
        try:
            fcntl.flock(self.instance_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.instance_lock.close()
            raise Problem('相同資料目錄與模式的服務已啟動；請先停止原服務，避免覆寫執行中的任務',409)
        self.media = self.data_dir/'media'
        self.media.mkdir(exist_ok=True)
        self.apkdir = self.data_dir/'apks'
        self.apkdir.mkdir(exist_ok=True)
        # Demo operations must never replace real device registry / task metadata.
        self.store = Store(self.data_dir/('ultron-mock.sqlite3' if mode=='mock' else 'ultron.sqlite3'))
        self.adb = shutil.which(os.environ.get('ADB_PATH','adb'))
        self.package = os.environ.get('ULTRON_PACKAGE','com.ultron.app')
        if not PKG.fullmatch(self.package):
            raise Problem('ULTRON_PACKAGE 格式無效')
        self.token = secrets.token_urlsafe(32)
        self.guard = threading.RLock()
        self.processes = {}
        self.log_processes = set()
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=8)
        self.confirmations = {}
        self.stopped = threading.Event()
        self.devices = {d['id']: d for d in self.store.all('devices') if d.get('mode') == mode}
        self.tasks = {t['id']:t for t in self.store.all('tasks')}
        for task in self.tasks.values():
            if task['status'] in ('queued','running','cancelling'):
                task.update(status='interrupted', stage='服務中斷；請人工檢查後重試', ended=now())
                self.store.save('tasks',task)
        if mode == 'mock' and not self.devices:
            for i in (101,102,108):
                ident = f'192.168.1.{i}:5555'
                d = {'id':ident,'name':f'STB{i}','mode':'mock','brand':'Ultron','store':'展示門市',
                     'adb':'connected','app':'running','versionCode':'12040','versionName':'1.2.4',
                     'box':'Android TV Box','hardware':'Amlogic','localIP':f'192.168.1.{i}',
                     'publicIP':'待驗證（未提供可信設備端來源）','deviceID':f'DEMO-{i}', 'deviceTime':now(),
                     'cpu':12+i%13,'ram':46,'storage':62,'network':'模擬 LAN','lastSeen':now(), 'timeOffset':0}
                self.devices[ident] = d
                self.store.save('devices',d)
        for d in self.devices.values():
            if mode == 'real':
                d.update(adb='disconnected',app='unknown')
                self.store.save('devices',d)
        self.store.event('service',f'本機服務啟動：{mode}')

    def run_adb(self, serial, args, timeout=15, binary=False, task=None):
        if not self.adb:
            raise Problem('找不到 adb，請安裝 Android platform-tools 並設定 ADB_PATH',503)
        # args are constructed exclusively by server-owned allowlisted operations.
        cmd = [self.adb] + (['-s',serial] if serial else []) + args
        proc = subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if task:
            with self.guard:
                self.processes[task['id']] = proc
                if task.get('cancelRequested'):
                    proc.terminate()
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise Problem('ADB 逾時；設備狀態待驗證',504)
        finally:
            if task:
                with self.guard:
                    self.processes.pop(task['id'],None)
        if proc.returncode:
            raise Problem(err.decode(errors='replace').strip()[:1500] or 'ADB 指令失敗')
        return out if binary else out.decode(errors='replace').strip()

    @staticmethod
    def endpoint(value):
        try:
            ip, *port = value.strip().split(':')
            address = ipaddress.IPv4Address(ip)
            if not any(address in ipaddress.ip_network(net) for net in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')):
                raise ValueError()
            number = int(port[0]) if port else 5555
            if len(port)>1 or not 1<=number<=65535:
                raise ValueError()
            return f'{address}:{number}'
        except (ValueError,AttributeError):
            raise Problem('請輸入 LAN IPv4 與有效連接埠，例如 192.168.1.101:5555')

    def connect(self, value, source):
        ident = self.endpoint(value)
        if self.mode == 'real':
            result = self.run_adb(None,['connect',ident])
            if 'connected to' not in result:
                raise Problem(result)
        with self.guard:
            d = self.devices.get(ident, {'id':ident,'name':'STB'+ident.split(':')[0].split('.')[-1],
                                        'brand':'','store':'','mode':self.mode,'localIP':ident.split(':')[0]})
            d.update(adb='connected',app='unknown',lastSeen=now())
            self.devices[ident] = d
        self.store.event('connect','手動連線',ident,source)
        self.refresh(ident)
        return d

    def discover(self, cidr, source):
        try:
            subnet = ipaddress.IPv4Network(cidr, strict=False)
            if subnet.prefixlen < 24 or not any(subnet.subnet_of(ipaddress.ip_network(net)) for net in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')):
                raise ValueError()
        except ValueError:
            raise Problem('僅允許私人 LAN /24 或更小網段搜尋')
        if self.mode == 'mock':
            self.store.event('discovery','模擬網段搜尋',source=source)
            return list(self.devices.values())
        def probe(ip):
            try:
                with socket.create_connection((str(ip),5555),timeout=.25):
                    pass
                return self.connect(str(ip),source)
            except (OSError,Problem):
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
            found = [d for d in pool.map(probe, subnet.hosts()) if d]
        self.store.event('discovery',f'{cidr}：找到 {len(found)} 台',source=source)
        return found

    def get_device(self, ident):
        d = self.devices.get(ident)
        if not d:
            raise Problem('找不到設備',404)
        return d

    def refresh(self, ident):
        with self.guard:
            return self._refresh(ident)

    def _refresh(self, ident):
        d = self.get_device(ident)
        previous = d.get('adb')
        if self.mode == 'mock':
            d['deviceTime'] = datetime.fromtimestamp(time.time()+d.get('timeOffset',0),timezone.utc).isoformat(timespec='seconds')
            d['lastSeen'] = now()
        else:
            try:
                state = self.run_adb(ident,['get-state'],timeout=4)
                if state != 'device':
                    raise Problem('設備未授權或離線')
                d.pop('error',None)
                props = self.run_adb(ident,['shell','getprop'])
                p = dict(re.findall(r'\[([^]]+)\]: \[([^]]*)\]', props))
                d.update(adb='connected',box=p.get('ro.product.model','待驗證'),hardware=p.get('ro.product.manufacturer','待驗證'),
                         deviceID=p.get('ro.serialno','待驗證'),lastSeen=now())
                details = self.run_adb(ident,['shell','dumpsys','package',self.package])
                d['versionCode'] = (re.search(r'versionCode=(\d+)',details) or [None,'未安裝'])[1]
                d['versionName'] = (re.search(r'versionName=([^\s]+)',details) or [None,'未安裝'])[1]
                try:
                    d['app'] = 'running' if self.run_adb(ident,['shell','pidof',self.package]) else 'stopped'
                except Problem:
                    d['app'] = 'stopped' if d['versionCode'] != '未安裝' else 'not_installed'
                d['deviceTime'] = self.run_adb(ident,['shell','date','-u','+%Y-%m-%dT%H:%M:%SZ'])
                try:
                    stamp = datetime.fromisoformat(d['deviceTime'].replace('Z','+00:00')).timestamp()
                    d['timeOffset'] = round(stamp-time.time())
                except ValueError:
                    d['timeOffset'] = None
                d.update(cpu=None,ram=None,storage=None,network='待驗證',publicIP='待驗證（未提供可信設備端來源）')
                try:
                    cpu = self.run_adb(ident,['shell','dumpsys','cpuinfo'])
                    match = re.search(r'([\d.]+)% TOTAL',cpu)
                    d['cpu'] = float(match[1]) if match else None
                    mem = self.run_adb(ident,['shell','cat','/proc/meminfo'])
                    m = {k:int(v) for k,v in re.findall(r'(MemTotal|MemAvailable):\s+(\d+)',mem)}
                    if m.get('MemTotal') and 'MemAvailable' in m:
                        d['ram'] = round(100*(1-m['MemAvailable']/m['MemTotal']))
                    df = self.run_adb(ident,['shell','df','/data'])
                    pct = re.search(r'(\d+)%',df)
                    d['storage'] = int(pct[1]) if pct else None
                    d['network'] = self.run_adb(ident,['shell','ip','route'])[:600] or '待驗證'
                except Problem:
                    pass
            except Problem as exc:
                d.update(adb='disconnected',app='unknown',error=str(exc))
        if previous != d.get('adb'):
            self.store.event('alert' if d['adb'] != 'connected' else 'reconnected',f'ADB {d["adb"]}',ident)
        old_alerts = set(d.get('alerts',[]))
        d['alerts'] = [f'{label} 使用率 {d[key]}%' for key,label in [('cpu','CPU'),('ram','RAM'),('storage','儲存空間')]
                       if isinstance(d.get(key),(int,float)) and d[key]>=90]
        for alert in set(d['alerts'])-old_alerts:
            self.store.event('alert',alert,ident)
        self.store.save('devices',d)
        return d

    def monitor(self):
        while not self.stopped.wait(10):
            for d in list(self.devices.values()):
                try:
                    if self.mode == 'real' and d.get('adb') != 'connected' and d.get('autoReconnect',True):
                        self.run_adb(None,['connect',self.endpoint(d['id'])],timeout=5)
                    self.refresh(d['id'])
                except Exception as exc:
                    self.store.event('monitor_error',str(exc),d['id'])

    def validate_job(self, body):
        action = body.get('action')
        ids = body.get('devices',[])
        params = body.get('params',{})
        if action not in ACTIONS or not isinstance(ids,list) or not ids or len(ids)>64 or len(set(ids))!=len(ids):
            raise Problem('無效操作或設備選取')
        if not isinstance(params,dict):
            raise Problem('參數無效')
        for ident in ids:
            d = self.get_device(ident)
            if d.get('adb') != 'connected':
                raise Problem(f'{d["name"]} 離線，請先連線')
        if action == 'key' and params.get('key') not in KEYS:
            raise Problem('按鍵不在白名單')
        if action == 'set_time':
            if params.get('syncComputer') is True:
                params = {'syncComputer':True}
            else:
                try:
                    stamp = datetime.fromisoformat(params['time'])
                    if not 1990 <= stamp.year <= 2100 or stamp.tzinfo is None:
                        raise ValueError()
                    params = {'time':stamp.isoformat(timespec='seconds')}
                except (KeyError,ValueError,TypeError):
                    raise Problem('時間須為 1990～2100 年，精確到秒且含時區')
        if action == 'install':
            if not isinstance(params.get('allowDowngrade',False),bool):
                raise Problem('允許降版必須明確傳入布林值')
            params = {'apk':params.get('apk'),'allowDowngrade':params.get('allowDowngrade',False)}
            apk = next((a for a in self.apk_list() if a['id']==params.get('apk')),None)
            if not apk or apk.get('mock'):
                if not (apk and self.mode=='mock'):
                    raise Problem('找不到可安裝的本機 APK；Drive 檔案請先下載')
            if apk.get('mock') and self.mode != 'mock':
                raise Problem('模擬 APK 不可安裝到真實設備')
            if not PKG.fullmatch(apk.get('package','')):
                raise Problem('APK 套件名稱無效')
            # A rollback uses an explicitly selected old APK, never an automatic downgrade.
            for ident in ids:
                current = self.installed_version(ident,apk['package'])
                if current.isdigit() and int(current)>int(apk['versionCode']) and not params.get('allowDowngrade'):
                    raise Problem('偵測到降版：須勾選人工允許降版，並再次確認；Android 仍可能拒絕保留資料降版')
        return action,ids,params

    def installed_version(self, ident, package):
        if self.mode == 'mock':
            return str(self.get_device(ident).get('versionCode',''))
        text = self.run_adb(ident,['shell','dumpsys','package',package])
        match = re.search(r'versionCode=(\d+)',text)
        return match[1] if match else '未安裝'

    def confirmation(self, body, source):
        action,ids,params = self.validate_job(body)
        if action not in RISKY:
            raise Problem('此操作不需風險憑證')
        challenge = secrets.token_urlsafe(24)
        digest = json.dumps([action,ids,params],sort_keys=True)
        phrase = f'確認 {len(ids)} 台 {action}'
        with self.guard:
            self.confirmations[challenge] = (time.monotonic()+120,digest,source,phrase)
            self.confirmations = {k:v for k,v in self.confirmations.items() if v[0]>time.monotonic()}
        return {'challenge':challenge,'phrase':phrase,'warning':'操作可能無法復原。請檢查設備、備份與安裝條件；輸入指定文字完成第二次確認。'}

    def submit(self, body, source):
        action,ids,params = self.validate_job(body)
        with self.guard:
            busy = [t['device'] for t in self.tasks.values() if t['status'] in ('queued','running','cancelling')]
            if any(i in busy for i in ids):
                raise Problem('設備有未完成任務。請人工取消或等待完成，再重新確認操作。',409)
            if action in RISKY:
                item = self.confirmations.pop(body.get('challenge',''),None)
                if not item or item[0]<time.monotonic() or item[1]!=json.dumps([action,ids,params],sort_keys=True) or item[2]!=source or body.get('phrase')!=item[3]:
                    raise Problem('缺少、過期或不相符的雙重確認',403)
            batch = secrets.token_hex(8)
            result = []
            for ident in ids:
                task = {'id':secrets.token_hex(12),'batch':batch,'device':ident,'action':action,'params':params,
                        'status':'queued','stage':'等待執行','progress':0,'created':now(),'source':source,'mode':self.mode}
                self.tasks[task['id']] = task
                self.store.save('tasks',task)
                self.store.event('operation',f'{action} / {task["id"]}',ident,source)
                result.append(task)
            for task in result:
                self.pool.submit(self.execute,task)
            return result

    def stage(self, task, message, progress):
        if task.get('cancelRequested') or self.stopped.is_set():
            raise Problem('已要求取消；已送出的裝置變更無法回復')
        task.update(stage=message,progress=progress)
        self.store.save('tasks',task)

    def execute(self, task):
        d = self.get_device(task['device'])
        action,p = task['action'],task['params']
        task.update(status='running',started=now())
        self.store.save('tasks',task)
        try:
            self.stage(task,'連線檢查',5)
            if d.get('adb') != 'connected':
                raise Problem('設備已離線；任務停止，請手動重試')
            if self.mode == 'mock':
                for n,s in [(20,'模擬：前置條件檢查'),(50,'模擬：執行操作'),(85,'模擬：結果驗證')]:
                    time.sleep(.35)
                    self.stage(task,s,n)
                if action == 'set_time':
                    d['timeOffset'] = 0 if p.get('syncComputer') else datetime.fromisoformat(p['time']).timestamp()-time.time()
                elif action == 'network_time':
                    d['timeOffset'] = 0
                elif action == 'install':
                    apk = next(a for a in self.apk_list() if a['id']==p['apk'])
                    task['oldVersion'] = d.get('versionCode')
                    task['backup'] = '模擬：未備份 APP 私有資料'
                    d.update(versionCode=apk['versionCode'],versionName=apk.get('versionName'),app='running')
                elif action == 'record':
                    raise Problem('模擬模式不產生假錄影；請切換真實 ADB 模式')
                task['result'] = '模擬完成（未對真實設備執行）'
                self.refresh(d['id'])
            else:
                adb = lambda args,timeout=15,binary=False: self.run_adb(d['id'],args,timeout,binary,task)
                if action == 'key':
                    adb(['shell','input','keyevent',str(KEYS[p['key']])])
                elif action == 'restart_app':
                    adb(['shell','am','force-stop',self.package])
                    result = adb(['shell','monkey','-p',self.package,'-c','android.intent.category.LAUNCHER','1'])
                    if 'aborted' in result.lower():
                        raise Problem(result)
                    time.sleep(1)
                    if not adb(['shell','pidof',self.package]):
                        raise Problem('APP 啟動驗證失敗')
                elif action == 'reboot':
                    adb(['reboot'])
                    task['result'] = '已送出重啟；完成開機狀態待驗證'
                    d.update(adb='disconnected',app='unknown')
                elif action == 'shutdown':
                    adb(['shell','reboot','-p'])
                    task['result'] = '已送出關機；實際電源狀態待驗證'
                    d.update(adb='disconnected',app='unknown')
                elif action == 'clear_data':
                    result = adb(['shell','pm','clear',self.package])
                    if 'Success' not in result:
                        raise Problem(result)
                elif action == 'factory_reset':
                    raise Problem('不支援：各廠商的原廠重置權限及指令不同，尚未驗證，未送出重置指令')
                elif action in ('set_time','network_time'):
                    self.stage(task,'檢查時間設定權限',20)
                    uid = adb(['shell','id','-u'])
                    if uid != '0':
                        raise Problem('不支援：設備 adb shell 非 root，無法可靠修改並驗證系統時間；未重啟 APP')
                    if action == 'network_time':
                        adb(['shell','settings','put','global','auto_time','1'])
                        time.sleep(2)
                        if adb(['shell','settings','get','global','auto_time']) != '1':
                            raise Problem('恢復網路時間設定驗證失敗')
                        task['result'] = '網路自動時間設定已啟用；實際 NTP 校時待驗證；未重啟 APP'
                    else:
                        target = datetime.now(timezone.utc) if p.get('syncComputer') else datetime.fromisoformat(p['time'])
                        adb(['shell','settings','put','global','auto_time','0'])
                        self.stage(task,'設定時間（不重啟 APP）',50)
                        adb(['shell','date','-u',target.astimezone(timezone.utc).strftime('%m%d%H%M%Y.%S')])
                        actual = adb(['shell','date','+%s'])
                        difference = abs(int(actual)-target.timestamp())
                        if difference>5:
                            raise Problem(f'設定後驗證失敗：差距 {difference:.0f} 秒；未重啟 APP')
                        task['result'] = f'時間驗證通過，差距 {difference:.0f} 秒；未重啟 APP'
                    self.refresh(d['id'])
                elif action == 'install':
                    apk = next(a for a in self.store.all('apks') if a['id']==p['apk'])
                    package = apk['package']
                    path = self.apkdir/(apk['id']+'.apk')
                    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=apk['sha256']:
                        raise Problem('APK 本機檔案遺失或 SHA-256 不符')
                    task['oldVersion'] = self.installed_version(d['id'],package)
                    task['backup'] = '舊版 APK 備份待驗證；APP 私有資料未備份（Android 權限限制）'
                    self.stage(task,'記錄舊版與備份條件',15)
                    if task['oldVersion'].isdigit():
                        oldpaths = adb(['shell','pm','path',package]).splitlines()
                        backup_files = []
                        for index,line in enumerate(oldpaths):
                            remote = line.removeprefix('package:')
                            if not re.fullmatch(r'/[A-Za-z0-9_./=+@~\-]+\.apk',remote):
                                raise Problem('舊版 APK 路徑無法安全備份，停止安裝')
                            out = self.media/f'{task["id"]}-old-{index}.apk'
                            adb(['pull',remote,str(out)],60)
                            backup_files.append(out.name)
                        if not backup_files:
                            raise Problem('無法取得舊版 APK，停止安裝')
                        task['backupFiles'] = backup_files
                        task['backup'] = '已保存舊版 APK；APP 私有資料未備份；split APK 須人工處理回復'
                    if task['oldVersion'].isdigit() and int(task['oldVersion'])>int(apk['versionCode']) and not p.get('allowDowngrade'):
                        raise Problem('執行前再次檢查到降版，停止安裝')
                    self.stage(task,'ADB 安裝中（工具未提供逐位元進度）',35)
                    result = adb(['install','-r']+(['-d'] if p.get('allowDowngrade') else [])+[str(path)],180)
                    if 'Success' not in result:
                        raise Problem(result)
                    self.stage(task,'驗證安裝版本',75)
                    if self.installed_version(d['id'],package)!=str(apk['versionCode']):
                        raise Problem('安裝後 VersionCode 不符')
                    result = adb(['shell','monkey','-p',package,'-c','android.intent.category.LAUNCHER','1'])
                    if 'aborted' in result.lower():
                        raise Problem('已安裝，但 APP 無法啟動：'+result)
                    time.sleep(2)
                    if not adb(['shell','pidof',package]):
                        raise Problem('已安裝，但 APP 啟動後未存活')
                    logs = adb(['logcat','-d','-t','150','-v','threadtime'])
                    crash = [l for l in logs.splitlines() if package in l or 'FATAL EXCEPTION' in l or 'AndroidRuntime' in l]
                    task['logReview'] = '\n'.join(crash)[-6000:] or '最近 150 行未發現關鍵字；不保證 APP 無異常'
                    task['result'] = '版本及 APP 啟動驗證通過；異常 Logcat 已保存供人工檢查'
                    self.refresh(d['id'])
                elif action == 'record':
                    remote = '/sdcard/ultron-qa-'+task['id']+'.mp4'
                    self.stage(task,'設備錄影中，最長 30 秒',15)
                    adb(['shell','screenrecord','--time-limit','30',remote],40)
                    self.stage(task,'取回錄影',80)
                    out = self.media/(self.filename(d,'record')+'.mp4')
                    adb(['pull',remote,str(out)],60)
                    adb(['shell','rm',remote])
                    task['file'] = out.name
                task.setdefault('result','ADB 指令已完成')
            self.stage(task,'完成',100)
            task.update(status='succeeded')
        except Exception as exc:
            task.update(status='cancelled' if task.get('cancelRequested') else 'failed',stage='已取消' if task.get('cancelRequested') else '失敗',error=str(exc))
        finally:
            task['ended'] = now()
            self.store.save('devices',d)
            self.store.save('tasks',task)
            self.store.event('task_'+task['status'],json.dumps({k:task.get(k) for k in ('id','action','result','error','oldVersion','backup','backupFiles','logReview')},ensure_ascii=False),d['id'],task['source'])

    @staticmethod
    def filename(d, kind):
        name = re.sub(r'[^\w\-]','_',d['name'])[:60]
        return f'{name}_{kind}_{datetime.now().strftime("%Y%m%d_%H%M%S")}_{secrets.token_hex(3)}'

    def cancel(self, ident, source, batch=False):
        found = []
        with self.guard:
            for t in self.tasks.values():
                if (t['batch'] if batch else t['id']) == ident and t['status'] in ('queued','running','cancelling'):
                    t.update(cancelRequested=True,status='cancelling',stage='正在取消；已送出變更無法撤回')
                    self.store.save('tasks',t)
                    proc = self.processes.get(t['id'])
                    if proc:
                        proc.terminate()
                    self.store.event('cancel_requested',t['id'],t['device'],source)
                    found.append(t['id'])
        return found

    def logs(self, ident):
        self.get_device(ident)
        if self.mode == 'mock':
            tick = int(time.time())
            return [{'id':f'{tick}-{i}','text':f'{datetime.now().strftime("%m-%d %H:%M:%S")}.000  1204  1204 {level} {tag}: [模擬] {msg}',
                     'level':level,'tag':tag,'package':self.package if tag=='Ultron' else 'system'}
                    for i,(level,tag,msg) in enumerate([('I','Ultron','播放服務正常'),('D','Ultron','心跳已送出'),('W','Network','連線延遲樣本')])]
        # Full recent ring buffer, incrementally deduplicated by the client; no device log clearing.
        output = self.run_adb(ident,['logcat','-b','all','-d','-t','800','-v','threadtime'])
        try:
            pid = self.run_adb(ident,['shell','pidof',self.package]).split()[0]
        except (Problem,IndexError):
            pid = None
        result = []
        occurrences = {}
        for line in output.splitlines():
            occurrences[line] = occurrences.get(line,0)+1
            m = re.match(r'\S+\s+\S+\s+(\d+)\s+\d+\s+([VDIWEF])\s+([^:]+):',line)
            result.append({'id':hashlib.sha256(f'{occurrences[line]}:{line}'.encode()).hexdigest(),'text':line,'level':m[2] if m else 'I',
                           'tag':m[3] if m else '', 'package':self.package if m and m[1]==pid else 'system'})
        return result

    def log_stream(self, ident):
        self.get_device(ident)
        if self.mode != 'real' or not self.adb:
            raise Problem('即時 Logcat 串流僅適用已安裝 ADB 的真實模式')
        try:
            pid = self.run_adb(ident,['shell','pidof',self.package]).split()[0]
        except (Problem,IndexError):
            pid = None
        proc = subprocess.Popen([self.adb,'-s',ident,'logcat','-b','all','-v','threadtime','-T','800'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        with self.guard:
            if len(self.log_processes)>=8:
                proc.terminate();proc.communicate()
                raise Problem('同時 Logcat 串流數量已達上限',429)
            self.log_processes.add(proc)
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout,selectors.EVENT_READ)
        deadline = time.monotonic()+45
        buffer = b''
        occurrences = {}
        try:
            while time.monotonic()<deadline and not self.stopped.is_set():
                if not selector.select(timeout=1):
                    yield {'heartbeat':True}
                    continue
                chunk = os.read(proc.stdout.fileno(),65536)
                if not chunk:
                    if proc.poll() not in (None,0):
                        yield {'error':'Logcat 程序結束，設備可能斷線或不支援 all buffers'}
                    break
                buffer += chunk
                while b'\n' in buffer:
                    line,buffer=buffer.split(b'\n',1)
                    text=line.decode(errors='replace').rstrip('\r')
                    occurrences[text]=occurrences.get(text,0)+1
                    m=re.match(r'\S+\s+\S+\s+(\d+)\s+\d+\s+([VDIWEF])\s+([^:]+):',text)
                    yield {'id':hashlib.sha256(f'{occurrences[text]}:{text}'.encode()).hexdigest(),'text':text,
                           'level':m[2] if m else 'I','tag':m[3] if m else '', 'package':self.package if m and m[1]==pid else 'system'}
        finally:
            selector.close()
            proc.terminate()
            proc.communicate()
            with self.guard:
                self.log_processes.discard(proc)

    def upload(self, data, filename, source):
        if not filename.lower().endswith('.apk'):
            raise Problem('僅接受 APK 檔案')
        ident = secrets.token_hex(16)
        path = self.apkdir/(ident+'.apk')
        path.write_bytes(data)
        try:
            info = inspect_apk(path)
            if not PKG.fullmatch(info['package']):
                raise Problem('Package Name 無效')
        except Exception as exc:
            path.unlink(missing_ok=True)
            raise Problem('APK 解析失敗：'+str(exc))
        item = {'id':ident,'filename':Path(filename).name,**info,'uploaded':now(),'drive':'local','mock':False}
        self.store.save('apks',item)
        self.store.event('apk_upload',f'{item["filename"]} / SHA-256 {item["sha256"]}',source=source)
        return item

    def apk_list(self):
        items = self.store.all('apks')
        if self.mode == 'mock':
            items += [{'id':'demo-12040','filename':'ultron-1.2.4-demo.apk','package':self.package,'versionCode':'12040','versionName':'1.2.4','size':32890412,'uploaded':now(),'sha256':'模擬資料：沒有真實 APK 雜湊','mock':True,'drive':'模擬'},
                      {'id':'demo-12030','filename':'ultron-1.2.3-demo.apk','package':self.package,'versionCode':'12030','versionName':'1.2.3','size':31980412,'uploaded':now(),'sha256':'模擬資料：沒有真實 APK 雜湊','mock':True,'drive':'模擬'}]
        return items

    def drive(self, method='GET', file=None):
        token = os.environ.get('GOOGLE_DRIVE_ACCESS_TOKEN')
        folder = os.environ.get('GOOGLE_DRIVE_FOLDER_ID')
        if not token or not folder:
            raise Problem('Google Drive 未設定：請在本機服務環境設定公司資料夾 ID 與具權限的 OAuth access token；不會假裝上傳成功',503)
        if not re.fullmatch(r'[A-Za-z0-9_-]+',folder):
            raise Problem('Google Drive 資料夾 ID 格式錯誤')
        headers = {'Authorization':'Bearer '+token}
        if method == 'GET':
            query = parse.urlencode({'q':f"'{folder}' in parents and trashed = false",'fields':'nextPageToken,files(id,name,size,createdTime,appProperties)','pageSize':1000,'supportsAllDrives':'true','includeItemsFromAllDrives':'true'})
            url = 'https://www.googleapis.com/drive/v3/files?'+query
            body = None
        else:
            if not file or file.get('mock'):
                raise Problem('模擬 APK 無法上傳 Drive')
            metadata = {'name':file['filename'],'parents':[folder], 'appProperties':{k:str(file[k]) for k in ('package','versionCode','versionName','sha256')}}
            boundary = 'ultron-'+secrets.token_hex(16)
            body = (f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'+json.dumps(metadata)+'\r\n'+f'--{boundary}\r\nContent-Type: application/vnd.android.package-archive\r\n\r\n').encode()+(self.apkdir/(file['id']+'.apk')).read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
            headers['Content-Type']='multipart/related; boundary='+boundary
            url='https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&supportsAllDrives=true&fields=id,name'
        try:
            with request.urlopen(request.Request(url,data=body,headers=headers,method=method),timeout=60) as response:
                result = json.load(response)
        except Exception as exc:
            raise Problem('Google Drive 請求失敗，請檢查憑證／資料夾權限：'+str(exc),502)
        if file:
            file.update(drive='uploaded',driveId=result['id'])
            self.store.save('apks',file)
        return result

    def drive_download(self, file_id, source):
        if not isinstance(file_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',file_id):
            raise Problem('Drive 檔案 ID 無效')
        token=os.environ.get('GOOGLE_DRIVE_ACCESS_TOKEN')
        folder=os.environ.get('GOOGLE_DRIVE_FOLDER_ID')
        if not token or not folder:
            raise Problem('Google Drive 憑證與公司資料夾尚未設定',503)
        headers={'Authorization':'Bearer '+token}
        base='https://www.googleapis.com/drive/v3/files/'+file_id
        try:
            with request.urlopen(request.Request(base+'?supportsAllDrives=true&fields=id,name,size,parents,trashed',headers=headers),timeout=30) as response:
                metadata=json.load(response)
            if metadata.get('trashed') or folder not in metadata.get('parents',[]) or not metadata.get('name','').lower().endswith('.apk'):
                raise Problem('僅能下載設定的公司資料夾內 APK')
            if int(metadata.get('size',0))>512*1024*1024:
                raise Problem('Drive APK 超過 512 MB 限制')
            with request.urlopen(request.Request(base+'?alt=media&supportsAllDrives=true',headers=headers),timeout=120) as response:
                data=response.read(512*1024*1024+1)
            if len(data)>512*1024*1024:
                raise Problem('Drive APK 超過 512 MB 限制')
        except Problem:
            raise
        except Exception as exc:
            raise Problem('Drive 下載失敗：'+str(exc),502)
        item=self.upload(data,metadata['name'],source)
        item.update(drive='uploaded',driveId=file_id)
        self.store.save('apks',item)
        self.store.event('drive_download',file_id,source=source)
        return item
