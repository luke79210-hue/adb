import io
import json
import os
from pathlib import Path
import sqlite3
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib import request, error
import zipfile

from server.core import Service, Problem, Store
from server.app import create_server
from server.apk import inspect_apk, manifest_metadata


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = Service(self.tmp.name)
        self.ids = list(self.s.devices)
        self.source = ('127.0.0.1','test-session')

    def tearDown(self):
        self.s.stopped.set()
        self.s.pool.shutdown(wait=True)
        self.s.store.db.close()
        self.s.instance_lock.close()
        self.tmp.cleanup()

    def wait(self, tasks):
        end = time.monotonic()+6
        while any(t['status'] in ('queued','running','cancelling') for t in tasks):
            if time.monotonic()>end:
                self.fail('任務逾時')
            time.sleep(.02)
        return tasks

    def confirmed(self, body):
        c = self.s.confirmation(body,self.source)
        return {**body,**{k:c[k] for k in ('challenge','phrase')}}

    def test_endpoint_rejects_shell_and_public_hosts(self):
        for ip in ['8.8.8.8','127.0.0.1','0.0.0.0','192.168.1.2;reboot','192.168.1.1:0','192.168.1.1:99999','example.com','192.168.1.1:5555:55']:
            with self.subTest(ip=ip), self.assertRaises(Problem):
                self.s.endpoint(ip)
        self.assertEqual(self.s.endpoint('192.168.1.9'),'192.168.1.9:5555')

    def test_key_allowlist_and_arbitrary_action_rejected(self):
        for body in [{'action':'shell','devices':self.ids}, {'action':'key','devices':self.ids,'params':{'key':'home;reboot'}}]:
            with self.assertRaises(Problem): self.s.submit(body,self.source)

    def test_all_devices_execute_and_conflicts_require_manual_action(self):
        tasks = self.s.submit({'action':'key','devices':self.ids,'params':{'key':'home'}},self.source)
        self.assertEqual(len(tasks),3)
        with self.assertRaises(Problem) as e:
            self.s.submit({'action':'key','devices':self.ids,'params':{'key':'ok'}},self.source)
        self.assertEqual(e.exception.status,409)
        self.wait(tasks)
        self.assertTrue(all(t['status']=='succeeded' for t in tasks))
        self.assertTrue(all('模擬' in t['result'] for t in tasks))

    def test_risky_confirmation_bound_to_payload_session_and_single_use(self):
        body = {'action':'clear_data','devices':[self.ids[0]]}
        with self.assertRaises(Problem): self.s.submit(body,self.source)
        confirmed = self.confirmed(body)
        with self.assertRaises(Problem): self.s.submit(confirmed,('127.0.0.1','other'))
        confirmed = self.confirmed(body)
        with self.assertRaises(Problem): self.s.submit({**confirmed,'devices':[self.ids[1]]},self.source)
        confirmed = self.confirmed(body)
        self.wait(self.s.submit(confirmed,self.source))
        with self.assertRaises(Problem): self.s.submit(confirmed,self.source)

    def test_time_bounds_and_no_app_restart(self):
        for stamp in ['1989-12-31T23:59:59+08:00','2101-01-01T00:00:00+00:00','2026-10-27T12:00:00','invalid']:
            with self.assertRaises(Problem):
                self.s.submit({'action':'set_time','devices':self.ids,'params':{'time':stamp}},self.source)
        tasks = self.s.submit({'action':'set_time','devices':self.ids,'params':{'time':'1990-01-01T00:00:01+08:00'}},self.source)
        self.wait(tasks)
        self.assertTrue(all(t['status']=='succeeded' for t in tasks))
        self.assertTrue(all(d['app']=='running' for d in self.s.devices.values()))
        self.assertTrue(all(d['deviceTime'].startswith('1989-12-31') for d in self.s.devices.values()))

    def test_downgrade_needs_explicit_allowance_and_two_confirmations(self):
        body = {'action':'install','devices':self.ids,'params':{'apk':'demo-12030'}}
        with self.assertRaises(Problem): self.s.confirmation(body,self.source)
        body['params']['allowDowngrade'] = True
        tasks = self.s.submit(self.confirmed(body),self.source)
        self.wait(tasks)
        self.assertTrue(all(t['oldVersion']=='12040' for t in tasks))
        self.assertTrue(all(d['versionCode']=='12030' for d in self.s.devices.values()))

    def test_sync_computer_uses_execution_time(self):
        self.s.devices[self.ids[0]]['timeOffset']=-100000
        tasks=self.s.submit({'action':'set_time','devices':[self.ids[0]],'params':{'syncComputer':True}},self.source)
        self.wait(tasks)
        self.assertEqual(tasks[0]['status'],'succeeded')
        self.assertEqual(self.s.devices[self.ids[0]]['timeOffset'],0)
        self.assertEqual(self.s.devices[self.ids[0]]['app'],'running')

    def test_string_false_is_not_explicit_downgrade_permission(self):
        with self.assertRaises(Problem):
            self.s.confirmation({'action':'install','devices':self.ids,'params':{'apk':'demo-12030','allowDowngrade':'false'}},self.source)

    def test_cancel_single_and_batch(self):
        tasks = self.s.submit({'action':'key','devices':self.ids,'params':{'key':'ok'}},self.source)
        self.s.cancel(tasks[0]['id'],self.source)
        self.s.cancel(tasks[0]['batch'],self.source,batch=True)
        self.wait(tasks)
        self.assertTrue(all(t['status']=='cancelled' for t in tasks))

    def test_restart_marks_incomplete_tasks_interrupted(self):
        self.s.store.save('tasks',{'id':'old-job','status':'running'})
        self.s.instance_lock.close()  # Simulate termination of the previous process.
        s2 = Service(self.tmp.name)
        self.assertEqual(s2.tasks['old-job']['status'],'interrupted')
        s2.pool.shutdown(); s2.store.db.close(); s2.instance_lock.close()

    def test_duplicate_instance_does_not_interrupt_active_tasks(self):
        self.s.store.save('tasks',{'id':'active','status':'running'})
        with self.assertRaises(Problem):Service(self.tmp.name)
        self.assertEqual(next(t for t in self.s.store.all('tasks') if t['id']=='active')['status'],'running')

    def test_mock_and_real_database_are_isolated(self):
        self.s.store.save('tasks',{'id':'demo-job','status':'succeeded'})
        real=Service(self.tmp.name,mode='real')
        try:
            self.assertFalse(real.devices)
            self.assertNotIn('demo-job',real.tasks)
            self.assertNotEqual(real.store.path,self.s.store.path)
        finally:
            real.pool.shutdown();real.store.db.close();real.instance_lock.close()

    def test_sqlite_backup_restore_integrity(self):
        data = self.s.store.backup()
        self.s.store.event('test','new event')
        self.s.store.restore(data)
        self.assertFalse(any(e['kind']=='test' for e in self.s.store.events()))
        with self.assertRaises(Exception): self.s.store.restore(b'not a database')
        self.assertEqual(len(self.s.store.all('devices')),3)

    def test_mock_never_fakes_recording_or_drive(self):
        tasks=self.s.submit({'action':'record','devices':[self.ids[0]]},self.source)
        self.wait(tasks)
        self.assertEqual(tasks[0]['status'],'failed')
        with patch.dict(os.environ,{},clear=True),self.assertRaises(Problem): self.s.drive()

    def test_real_time_refuses_nonroot_before_mutation(self):
        self.s.mode='real'
        calls=[]
        def fake(serial,args,*a,**kw):
            calls.append(args)
            return '2000' if args==['shell','id','-u'] else ''
        self.s.run_adb=fake
        tasks=self.s.submit({'action':'set_time','devices':[self.ids[0]],'params':{'time':'2026-10-27T12:00:00+08:00'}},self.source)
        self.wait(tasks)
        self.assertEqual(tasks[0]['status'],'failed')
        self.assertEqual(calls,[['shell','id','-u']])

    def test_apk_plain_manifest_and_sha256(self):
        path=Path(self.tmp.name)/'valid.apk'
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('AndroidManifest.xml','<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.ultron.app" android:versionCode="123" android:versionName="1.2.3"/>')
        item=self.s.upload(path.read_bytes(),'valid.apk',self.source)
        self.assertEqual(item['versionCode'],'123')
        self.assertEqual(len(item['sha256']),64)
        self.assertEqual(item['package'],'com.ultron.app')
        with self.assertRaises(Problem):self.s.upload(b'bad','broken.apk',self.source)

    def test_binary_android_manifest_parser(self):
        strings=['manifest','package','versionCode','versionName','com.ultron.app','1.2.3']
        encoded=b'';offsets=[]
        for s in strings:
            raw=s.encode();offsets.append(len(encoded));encoded+=bytes([len(s),len(raw)])+raw+b'\0'
        while len(encoded)%4:encoded+=b'\0'
        start=28+4*len(strings)
        pool=struct.pack('<HHI5I',1,28,start+len(encoded),len(strings),0,256,start,0)+struct.pack('<'+'I'*len(strings),*offsets)+encoded
        attrs=b''.join(struct.pack('<IIIHBBI',0xffffffff,k,raw,8,0,typ,val) for k,raw,typ,val in [(1,4,3,4),(2,0xffffffff,16,123),(3,5,3,5)])
        node=struct.pack('<HHIII',0x102,16,36+len(attrs),1,0xffffffff)+struct.pack('<II6H',0xffffffff,0,20,20,3,0,0,0)+attrs
        data=struct.pack('<HHI',3,8,8+len(pool)+len(node))+pool+node
        result=manifest_metadata(data)
        self.assertEqual(result,{'package':'com.ultron.app','versionCode':'123','versionName':'1.2.3'})

    def test_real_subprocess_adapter_and_logcat_stream(self):
        """Execute a fake executable, covering argv transport and stream cleanup, no device."""
        binary=Path(self.tmp.name)/'fake-adb'
        trace=Path(self.tmp.name)/'argv.jsonl'
        binary.write_text('#!/usr/bin/env python3\nimport sys,json\n'
                          +f'with open({str(trace)!r},"a") as f:f.write(json.dumps(sys.argv[1:])+"\\n")\n'
                          +'a=sys.argv[3:] if sys.argv[1:2]==["-s"] else sys.argv[1:]\n'
                          +'if a==["shell","pidof","com.ultron.app"]:print("1204")\n'
                          +'elif a and a[0]=="logcat":print("10-27 12:00:00.001  1204  1204 I Ultron: fixture")\n'
                          +'elif a[:3]==["shell","input","keyevent"]:print("OK")\n')
        binary.chmod(0o700)
        self.s.mode='real';self.s.adb=str(binary)
        tasks=self.s.submit({'action':'key','devices':[self.ids[0]],'params':{'key':'home'}},self.source)
        self.wait(tasks)
        self.assertEqual(tasks[0]['status'],'succeeded')
        lines=list(self.s.log_stream(self.ids[0]))
        self.assertEqual(lines[0]['package'],'com.ultron.app')
        self.assertEqual(lines[0]['level'],'I')
        calls=[json.loads(line) for line in trace.read_text().splitlines()]
        self.assertIn(['-s',self.ids[0],'shell','input','keyevent','3'],calls)
        self.assertIn(['-s',self.ids[0],'logcat','-b','all','-v','threadtime','-T','800'],calls)
        self.assertFalse(self.s.log_processes)

    def test_real_factory_reset_explicitly_unsupported(self):
        self.s.mode='real'
        self.s.run_adb=lambda *a,**kw:self.fail('Must never send unverified factory reset command')
        tasks=self.s.submit(self.confirmed({'action':'factory_reset','devices':[self.ids[0]]}),self.source)
        self.wait(tasks)
        self.assertEqual(tasks[0]['status'],'failed')
        self.assertIn('不支援',tasks[0]['error'])

    def test_real_install_records_old_version_and_verifies_after_install(self):
        path=Path(self.tmp.name)/'install.apk'
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('AndroidManifest.xml','<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.ultron.app" android:versionCode="12050" android:versionName="1.2.5"/>')
        apk=self.s.upload(path.read_bytes(),'install.apk',self.source)
        self.s.mode='real';installed=False;calls=[]
        def fake(serial,args,*a,**kw):
            nonlocal installed
            calls.append(args)
            if args==['shell','dumpsys','package','com.ultron.app']:
                return 'versionCode='+('12050' if installed else '12040')+' versionName=1.2.5'
            if args==['shell','pm','path','com.ultron.app']:return 'package:/data/app/com.ultron/base.apk'
            if args[0]=='pull':Path(args[2]).write_bytes(b'old-apk');return ''
            if args[0]=='install':installed=True;return 'Success'
            if args[:2]==['shell','pidof']:return '1204'
            if args[:2]==['shell','monkey']:return 'Events injected: 1'
            if args[0]=='logcat':return 'I Ultron: healthy'
            if args==['get-state']:return 'device'
            if args[:2]==['shell','getprop']:return '[ro.product.model]: [Test Box]'
            if args[:2]==['shell','date']:return '2026-10-27T09:00:00Z'
            return ''
        self.s.run_adb=fake
        tasks=self.s.submit(self.confirmed({'action':'install','devices':[self.ids[0]],'params':{'apk':apk['id']}}),self.source)
        self.wait(tasks)
        self.assertEqual(tasks[0]['status'],'succeeded',tasks[0].get('error'))
        self.assertEqual(tasks[0]['oldVersion'],'12040')
        self.assertTrue(tasks[0]['backupFiles'])
        self.assertTrue((self.s.media/tasks[0]['backupFiles'][0]).exists())
        self.assertFalse(any('-d' in args for args in calls if args[0]=='install'))

    def test_drive_download_cannot_escape_company_folder(self):
        class Response(io.BytesIO):
            def __enter__(self):return self
            def __exit__(self,*a):self.close()
        with patch.dict(os.environ,{'GOOGLE_DRIVE_ACCESS_TOKEN':'test-only','GOOGLE_DRIVE_FOLDER_ID':'company-folder'}):
            with patch('server.core.request.urlopen',return_value=Response(json.dumps({'name':'test.apk','parents':['other-folder'],'size':'10'}).encode())) as net:
                with self.assertRaises(Problem):self.s.drive_download('safe-file-id',self.source)
                self.assertEqual(net.call_count,1)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.s=Service(self.tmp.name)
        self.http=create_server(self.s,0)
        self.port=self.http.server_address[1]
        self.base=f'http://127.0.0.1:{self.port}'
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.s.pool.shutdown(wait=True);self.s.store.db.close();self.s.instance_lock.close();self.tmp.cleanup()

    def req(self,path,body=None,headers=None,auth=True):
        h={'X-Ultron-Token':self.s.token} if auth else {}
        h.update(headers or {})
        data=None if body is None else json.dumps(body).encode()
        return request.urlopen(request.Request(self.base+path,data=data,headers=h),timeout=10)

    def test_real_http_static_and_api(self):
        with self.req('/') as r:self.assertIn('裝置資訊',r.read().decode())
        with self.req('/api/state') as r:self.assertEqual(len(json.load(r)['devices']),3)

    def test_unauthorized_origin_host_and_no_shell_endpoint(self):
        for path,h,auth,status in [('/api/state',{},False,401),('/api/session',{'Origin':'https://evil.example'},False,403),('/api/state',{'Host':'evil.example'},True,403),('/api/shell',{},True,404)]:
            with self.subTest(path=path,h=h),self.assertRaises(error.HTTPError) as e:self.req(path,headers=h,auth=auth)
            self.assertEqual(e.exception.code,status)

    def test_pages_origin_can_pair_but_cannot_read_local_session_token(self):
        origin='https://luke79210-hue.github.io'
        with patch.dict(os.environ,{'ULTRON_ALLOWED_ORIGINS':origin}):
            pages_server=create_server(self.s,0)
        threading.Thread(target=pages_server.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{pages_server.server_address[1]}'
        try:
            req=request.Request(base+'/api/state',headers={'Origin':origin,'X-Ultron-Token':self.s.token})
            with request.urlopen(req,timeout=5) as response:
                self.assertEqual(response.headers['Access-Control-Allow-Origin'],origin)
                self.assertEqual(json.load(response)['mode'],'mock')
            req=request.Request(base+'/api/state',headers={'Origin':origin})
            with self.assertRaises(error.HTTPError) as exc:request.urlopen(req,timeout=5)
            self.assertEqual(exc.exception.code,401)
            req=request.Request(base+'/api/session',headers={'Origin':origin})
            with self.assertRaises(error.HTTPError) as exc:request.urlopen(req,timeout=5)
            self.assertEqual(exc.exception.code,403)
            req=request.Request(base+'/api/tasks',method='OPTIONS',headers={'Origin':origin,'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'X-Ultron-Token'})
            with request.urlopen(req,timeout=5) as response:
                self.assertEqual(response.status,204)
                self.assertEqual(response.headers['Access-Control-Allow-Origin'],origin)
        finally:
            pages_server.shutdown();pages_server.server_close()

    def test_session_and_http_task_cancellation(self):
        with self.req('/api/session',auth=False) as r:self.assertEqual(json.load(r)['token'],self.s.token)
        with self.req('/api/tasks',{'action':'key','devices':list(self.s.devices),'params':{'key':'home'}}) as r:
            self.assertEqual(r.status,202);tasks=json.load(r)
        with self.req('/api/cancel',{'id':tasks[0]['batch'],'batch':True}) as r:self.assertEqual(len(json.load(r)['cancelled']),3)

    def test_mock_screen_honest_and_sqlite_backup(self):
        ident=list(self.s.devices)[0]
        with self.assertRaises(error.HTTPError) as e:self.req('/api/screen?device='+ident)
        self.assertEqual(e.exception.code,409)
        with self.req('/api/backup') as r:self.assertTrue(r.read().startswith(b'SQLite format 3'))

    def test_screenshot_real_api_saves_png_and_returns_download_filename(self):
        import base64
        from urllib.parse import unquote
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ1kAAAAASUVORK5CYII=')
        ident=list(self.s.devices)[0]
        self.s.mode='real'
        calls=[]
        def fake(serial,args,**kwargs):
            calls.append((serial,args,kwargs))
            return png
        self.s.run_adb=fake
        with self.req('/api/screenshot?device='+ident) as response:
            self.assertEqual(response.headers['Content-Type'],'image/png')
            self.assertEqual(response.read(),png)
            filename=unquote(response.headers['Content-Disposition'].split("UTF-8''")[1])
        self.assertEqual((self.s.media/filename).read_bytes(),png)
        self.assertEqual(calls,[(ident,['exec-out','screencap','-p'],{'binary':True})])
        self.assertTrue(any(e['kind']=='screenshot' for e in self.s.store.events()))

    def test_screenshot_rejects_invalid_image_without_saving(self):
        self.s.mode='real'
        self.s.run_adb=lambda *a,**kw:b'invalid image'
        with self.assertRaises(error.HTTPError) as exc:
            self.req('/api/screenshot?device='+list(self.s.devices)[0])
        self.assertEqual(exc.exception.code,400)
        self.assertFalse(list(self.s.media.glob('*.png')))
        self.assertFalse(any(e['kind']=='screenshot' for e in self.s.store.events()))

    def test_mock_screenshot_api_never_pretends_to_capture_a_real_device(self):
        with self.assertRaises(error.HTTPError) as exc:
            self.req('/api/screenshot?device='+list(self.s.devices)[0])
        self.assertEqual(exc.exception.code,409)
        self.assertFalse(list(self.s.media.glob('*.png')))

    def test_csv_formula_injection_neutralized(self):
        self.s.store.event('test','=HYPERLINK("bad")')
        with self.req('/api/export') as r:self.assertIn("'=HYPERLINK",r.read().decode())

    def test_restore_requires_confirmation_and_restores_without_replaying(self):
        with self.req('/api/backup') as r:data=r.read()
        with self.assertRaises(error.HTTPError) as e:
            self.req('/api/restore',{})
        self.assertEqual(e.exception.code,403)
        self.s.store.event('later','must disappear')
        with self.req('/api/restore/confirm',{}) as r:confirmation=json.load(r)
        from urllib.parse import urlencode
        url=self.base+'/api/restore?'+urlencode(confirmation)
        with request.urlopen(request.Request(url,data=data,headers={'X-Ultron-Token':self.s.token}),timeout=10) as r:
            self.assertTrue(json.load(r)['ok'])
        self.assertFalse(any(e['kind']=='later' for e in self.s.store.events()))
        self.assertTrue(list(Path(self.tmp.name).glob('pre-restore-*.sqlite3')))


if __name__=='__main__': unittest.main()
