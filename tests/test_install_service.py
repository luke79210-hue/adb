from pathlib import Path
import plistlib
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'scripts'))
from install_service import prepare_install


class InstallTests(unittest.TestCase):
    def test_bundle_uses_application_support_style_target_and_preserves_data_on_update(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);source=base/'Documents'/'project';target=base/'Application Support'/'Ultron'
            for name in ('server','web','scripts','.runtime'):(source/name).mkdir(parents=True,exist_ok=True)
            (source/'server'/'app.py').write_text('print("fixture")')
            (source/'web'/'index.html').write_text('<title>fixture</title>')
            (source/'scripts'/'run-service.sh').write_text('#!/bin/zsh\n')
            (source/'.env').write_text('ULTRON_ALLOWED_ORIGINS=https://luke79210-hue.github.io\n')
            db=sqlite3.connect(source/'.runtime'/'ultron-mock.sqlite3')
            db.execute('PRAGMA journal_mode=WAL');db.execute('CREATE TABLE sample(value TEXT)');db.execute("INSERT INTO sample VALUES ('saved')");db.commit()
            plist=base/'LaunchAgents'/'test.plist'
            bundle,data=prepare_install(source,target,sys.executable,'mock',plist)
            try:
                self.assertTrue((bundle/'web'/'index.html').exists())
                with sqlite3.connect(data/'ultron-mock.sqlite3') as snapshot:
                    self.assertEqual(snapshot.execute('SELECT value FROM sample').fetchone()[0],'saved')
                config=plistlib.loads(plist.read_bytes())
                self.assertNotIn('Documents',str(config))
                self.assertEqual(config['EnvironmentVariables']['ULTRON_DATA'],str(data))
                self.assertNotIn('ULTRON_ALLOWED_ORIGINS',str(config))
                (data/'keep.txt').write_text('user data')
                (source/'web'/'index.html').write_text('updated')
                prepare_install(source,target,sys.executable,'mock',plist)
                self.assertEqual((data/'keep.txt').read_text(),'user data')
                self.assertEqual((bundle/'web'/'index.html').read_text(),'updated')
                self.assertEqual((bundle/'.env').stat().st_mode&0o777,0o600)
            finally:
                db.close()
