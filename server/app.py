"""Loopback-only HTTP API + static client. python3 -m server.app --mode mock"""
import argparse
import csv
from datetime import datetime
import io
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from .core import ROOT, Service, Problem, now


class Handler(BaseHTTPRequestHandler):
    server_version = 'UltronLocal/1.0'

    def log_message(self, fmt, *args):
        # Never put tokens, query strings, or request bodies in access logs.
        pass

    @property
    def service(self):
        return self.server.service

    def origin_check(self):
        host = self.headers.get('Host','')
        if host not in self.server.hosts:
            raise Problem('Host 不在本機白名單（DNS rebinding 防護）',403)
        origin = self.headers.get('Origin')
        if origin and origin not in self.server.origins:
            raise Problem('來源網站未授權；請使用本機介面或明確設定 ULTRON_ALLOWED_ORIGINS',403)
        if self.client_address[0] not in ('127.0.0.1','::1'):
            raise Problem('僅接受本機連線',403)

    def authorize(self):
        if not secrets.compare_digest(self.headers.get('X-Ultron-Token',''),self.service.token):
            raise Problem('本機服務權杖無效，請從本機頁面取得配對權杖',401)

    def source(self):
        # The bearer token is the sole local session, persist only a non-secret fingerprint.
        return (self.client_address[0],__import__('hashlib').sha256(self.service.token.encode()).hexdigest()[:16])

    def send(self, value, status=200, mime='application/json; charset=utf-8', filename=None):
        data = json.dumps(value,ensure_ascii=False).encode() if mime.startswith('application/json') else value
        self.send_response(status)
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; connect-src 'self' http://127.0.0.1:* http://localhost:*; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; object-src 'none'; frame-ancestors 'none'")
        origin = self.headers.get('Origin')
        if origin in self.server.origins:
            self.send_header('Access-Control-Allow-Origin',origin)
            self.send_header('Vary','Origin')
            self.send_header('Access-Control-Expose-Headers','Content-Disposition')
        if filename:
            from urllib.parse import quote
            self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(filename))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        try:
            self.origin_check()
            self.send_response(204)
            self.send_header('Access-Control-Allow-Origin',self.headers.get('Origin',''))
            self.send_header('Access-Control-Allow-Methods','GET,POST,OPTIONS')
            self.send_header('Access-Control-Allow-Headers','Content-Type,X-Ultron-Token,X-Filename')
            self.send_header('Access-Control-Allow-Private-Network','true')
            self.end_headers()
        except Problem as exc:
            self.send({'error':str(exc)},exc.status)

    def do_GET(self):
        self.dispatch('GET')

    def do_POST(self):
        self.dispatch('POST')

    def dispatch(self, method):
        try:
            self.origin_check()
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)
            if path == '/api/session' and method=='GET':
                # Remote static frontends must pair manually; never disclose a token across origins.
                origin = self.headers.get('Origin')
                if origin and origin not in self.server.local_origins:
                    raise Problem('請在本機頁面複製配對權杖，再貼到前端',403)
                if self.headers.get('Sec-Fetch-Site') in ('cross-site',):
                    raise Problem('跨站來源不可取得本機配對權杖',403)
                return self.send({'token':self.service.token,'mode':self.service.mode})
            if not path.startswith('/api/'):
                if method!='GET':
                    raise Problem('Method not allowed',405)
                target = (ROOT/'web'/('index.html' if path=='/' else path.lstrip('/'))).resolve()
                if not target.is_relative_to(ROOT/'web') or not target.is_file():
                    raise Problem('找不到頁面',404)
                import mimetypes
                return self.send(target.read_bytes(),mime=mimetypes.guess_type(target)[0] or 'application/octet-stream')
            self.authorize()
            body = {}
            if method=='POST':
                try:
                    length = int(self.headers.get('Content-Length','0'))
                except ValueError:
                    raise Problem('Content-Length 無效')
                limit = 512*1024*1024 if path in ('/api/apks/upload','/api/restore') else 1024*1024
                if length<0 or length>limit:
                    raise Problem('檔案超過限制',413)
                raw = self.rfile.read(length)
                if len(raw)!=length:
                    raise Problem('請求中斷')
                if path not in ('/api/apks/upload','/api/restore'):
                    try:
                        body = json.loads(raw or b'{}')
                        if not isinstance(body,dict):
                            raise ValueError()
                    except (ValueError,UnicodeError):
                        raise Problem('JSON 格式無效')
            s = self.service
            source = self.source()
            if method=='GET':
                ident = query.get('device',[''])[0]
                if path=='/api/state':
                    return self.send({'mode':s.mode,'devices':[d for d in s.store.all('devices') if d.get('mode')==s.mode],'tasks':sorted(s.store.all('tasks'),key=lambda t:t.get('created',''),reverse=True)[:200],
                                      'apks':s.apk_list(),'package':s.package,'serverTime':now()})
                if path=='/api/diagnostics':
                    return self.send({'mode':s.mode,'adb':s.adb or '未安裝','package':s.package,'database':str(s.store.path),
                        'binding':'127.0.0.1（僅本機）','driveConfigured':bool(os.environ.get('GOOGLE_DRIVE_ACCESS_TOKEN') and os.environ.get('GOOGLE_DRIVE_FOLDER_ID')),
                        'allowedOrigins':sorted(self.server.origins),'version':'1.0.0','capabilities':{'screen':'PNG 輪詢（非 scrcpy 音訊串流）','factoryReset':'不支援／待設備驗證','time':'真實設備須 root；網路時間實際同步待驗證','publicIP':'待驗證','drive':'OAuth access token；過期需人工更新','restore':'僅 SQLite；APK / media 需另行備份'}})
                if path=='/api/events':
                    return self.send(s.store.events())
                if path=='/api/logs':
                    return self.send(s.logs(ident))
                if path=='/api/logs/stream':
                    s.get_device(ident)
                    if s.mode!='real' or not s.adb:
                        raise Problem('Logcat 串流需要真實 ADB 模式',409)
                    self.send_response(200)
                    self.send_header('Content-Type','application/x-ndjson; charset=utf-8')
                    self.send_header('Cache-Control','no-store')
                    origin=self.headers.get('Origin')
                    if origin in self.server.origins:
                        self.send_header('Access-Control-Allow-Origin',origin)
                    self.end_headers()
                    self.connection.settimeout(10)
                    try:
                        for line in s.log_stream(ident):
                            self.wfile.write((json.dumps(line,ensure_ascii=False)+'\n').encode())
                            self.wfile.flush()
                    except (BrokenPipeError,ConnectionResetError,TimeoutError):
                        pass
                    except Problem as exc:
                        self.wfile.write((json.dumps({'error':str(exc)},ensure_ascii=False)+'\n').encode())
                    return
                if path=='/api/screen':
                    s.get_device(ident)
                    if s.mode=='mock':
                        raise Problem('模擬模式：沒有真實 Android 畫面',409)
                    png = s.run_adb(ident,['exec-out','screencap','-p'],timeout=10,binary=True)
                    if not png.startswith(b'\x89PNG\r\n\x1a\n'):
                        raise Problem('設備未回傳有效 PNG')
                    return self.send(png,mime='image/png')
                if path=='/api/screenshot':
                    d = s.get_device(ident)
                    if s.mode=='mock':
                        raise Problem('模擬模式不產生假截圖',409)
                    data = s.run_adb(ident,['exec-out','screencap','-p'],binary=True)
                    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
                        raise Problem('截圖格式無效')
                    filename = s.filename(d,'screenshot')+'.png'
                    (s.media/filename).write_bytes(data)
                    s.store.event('screenshot',filename,ident,source)
                    return self.send(data,mime='image/png',filename=filename)
                if path=='/api/file':
                    name = query.get('name',[''])[0]
                    if Path(name).name!=name or not name or Path(name).suffix not in ('.mp4','.apk','.png'):
                        raise Problem('檔名無效')
                    target = s.media/name
                    if not target.is_file():
                        raise Problem('檔案不存在',404)
                    return self.send(target.read_bytes(),mime='application/octet-stream',filename=name)
                if path=='/api/backup':
                    s.store.event('backup','手動 SQLite 備份',source=source)
                    return self.send(s.store.backup(),mime='application/octet-stream',filename='ultron-backup-'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.sqlite3')
                if path=='/api/export':
                    out = io.StringIO()
                    writer = csv.writer(out)
                    writer.writerow(['ID','時間 UTC','類型','設備','內容','來源 IP','Session'])
                    for row in s.store.events():
                        # Avoid spreadsheet formula injection on arbitrary device/log labels.
                        writer.writerow([("'"+str(v)) if str(v).startswith(('=','+','-','@','\t','\r')) else v for v in row.values()])
                    return self.send(('\ufeff'+out.getvalue()).encode(),mime='text/csv; charset=utf-8',filename='ultron-events.csv')
                if path=='/api/drive':
                    return self.send(s.drive())
            else:
                if path=='/api/connect':
                    return self.send(s.connect(body.get('ip',''),source))
                if path=='/api/discover':
                    return self.send(s.discover(body.get('cidr',''),source))
                if path=='/api/device':
                    d = s.get_device(body.get('id'))
                    for key in ('name','brand','store'):
                        if key in body:
                            if not isinstance(body[key],str) or not body[key].strip() or len(body[key])>80:
                                raise Problem('名稱、品牌、店家須為 1～80 字')
                            d[key] = body[key].strip()
                    if 'autoReconnect' in body:
                        if not isinstance(body['autoReconnect'],bool):
                            raise Problem('autoReconnect 須為布林值')
                        d['autoReconnect'] = body['autoReconnect']
                    s.store.save('devices',d)
                    s.store.event('device_edit','更新設備資訊',d['id'],source)
                    return self.send(d)
                if path=='/api/refresh':
                    return self.send(s.refresh(body.get('id')) if body.get('id') else [s.refresh(i) for i in list(s.devices)])
                if path=='/api/confirm':
                    return self.send(s.confirmation(body,source))
                if path=='/api/tasks':
                    return self.send(s.submit(body,source),202)
                if path=='/api/cancel':
                    return self.send({'cancelled':s.cancel(body.get('id'),source,body.get('batch',False))})
                if path=='/api/apks/upload':
                    return self.send(s.upload(raw,unquote(self.headers.get('X-Filename','upload.apk')),source),201)
                if path=='/api/drive/upload':
                    item = next((a for a in s.store.all('apks') if a['id']==body.get('id')),None)
                    if not item:
                        raise Problem('找不到本機 APK',404)
                    result = s.drive('POST',item)
                    s.store.event('drive_upload',item['filename'],source=source)
                    return self.send(result)
                if path=='/api/drive/download':
                    return self.send(s.drive_download(body.get('id'),source),201)
                if path=='/api/restore/confirm':
                    challenge = secrets.token_urlsafe(24)
                    import time
                    s.confirmations[challenge] = (time.monotonic()+120,'restore',source,'確認還原資料庫')
                    return self.send({'challenge':challenge,'phrase':'確認還原資料庫'})
                if path=='/api/restore':
                    import time
                    item = s.confirmations.pop(query.get('challenge',[''])[0],None)
                    phrase = query.get('phrase',[''])[0]
                    if not item or item[0]<time.monotonic() or item[1]!='restore' or item[2]!=source or phrase!=item[3]:
                        raise Problem('還原須雙重確認',403)
                    with s.guard:
                        if any(t['status'] in ('queued','running','cancelling') for t in s.tasks.values()):
                            raise Problem('執行中有任務，禁止還原',409)
                        # Recovery snapshot lives outside the database being replaced.
                        (s.data_dir/('pre-restore-'+secrets.token_hex(8)+'.sqlite3')).write_bytes(s.store.backup())
                        try:
                            s.store.restore(raw)
                        except Exception as exc:
                            raise Problem('還原失敗：'+str(exc))
                        s.tasks = {t['id']:t for t in s.store.all('tasks')}
                        for t in s.tasks.values():
                            if t.get('status') in ('running','queued','cancelling'):
                                t.update(status='interrupted',stage='從備份還原；須人工檢查並重試')
                                s.store.save('tasks',t)
                        s.devices = {d['id']:d for d in s.store.all('devices') if d.get('mode')==s.mode}
                        if s.mode=='real':
                            for d in s.devices.values():
                                d.update(adb='disconnected',app='unknown')
                        s.store.event('restore','資料庫已還原；APK 與媒體須另行備份',source=source)
                    return self.send({'ok':True})
            raise Problem('找不到 API 或 Method 不符',404)
        except Problem as exc:
            self.send({'error':str(exc)},exc.status)
        except (BrokenPipeError,ConnectionResetError):
            pass
        except Exception as exc:
            self.service.store.event('api_error',str(exc),source=self.source())
            self.send({'error':'服務處理失敗：'+str(exc)},500)


def create_server(service, port=8765):
    httpd = ThreadingHTTPServer(('127.0.0.1',port),Handler)
    httpd.daemon_threads = True
    httpd.service = service
    actual = httpd.server_address[1]
    httpd.hosts = {f'127.0.0.1:{actual}',f'localhost:{actual}'}
    httpd.local_origins = {'http://'+h for h in httpd.hosts}
    extra = set(filter(None,os.environ.get('ULTRON_ALLOWED_ORIGINS','').split(',')))
    for origin in extra:
        p = urlparse(origin)
        if p.scheme!='https' or not p.netloc or p.path not in ('','/') or p.query or p.fragment:
            raise Problem('ULTRON_ALLOWED_ORIGINS 僅接受完整 HTTPS origin（不含路徑）')
    httpd.origins = httpd.local_origins|extra
    return httpd


def main():
    parser = argparse.ArgumentParser(description='Ultron ADB QA 本機服務')
    parser.add_argument('--mode',choices=['mock','real'],default='mock')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--data-dir')
    args = parser.parse_args()
    service = Service(args.data_dir,args.mode)
    httpd = create_server(service,args.port)
    threading.Thread(target=service.monitor,daemon=True).start()
    print(f'Ultron ADB QA V1.0 | {args.mode.upper()} | http://127.0.0.1:{httpd.server_address[1]}',flush=True)
    print('僅綁定 loopback；本機介面可查看配對權杖。Ctrl+C 停止。',flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.stopped.set()
        # Stop active subprocesses; next startup marks unfinished tasks interrupted.
        for proc in list(service.processes.values())+list(service.log_processes):
            proc.terminate()
        httpd.server_close()
        service.pool.shutdown(wait=True,cancel_futures=True)
        service.store.db.close()
        service.instance_lock.close()


if __name__=='__main__':
    main()
