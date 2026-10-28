from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'scripts'))
from check_release import verify
from configure_pages_service import configure, pages_origin


class ReleaseTests(unittest.TestCase):
    def test_current_public_artifact_contains_only_static_assets(self):
        files=verify()
        self.assertIn('index.html',files)
        self.assertIn('screenshots.js',files)
        self.assertIn('.nojekyll',files)
        self.assertFalse(any(name.endswith(('.apk','.sqlite3','.env')) for name in files))

    def test_release_rejects_secret_and_absolute_asset_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            web=root/'web';web.mkdir()
            (web/'index.html').write_text('<script src="/app.js"></script>')
            (web/'app.js').write_text('')
            with self.assertRaises(ValueError):verify(root)
            (web/'index.html').write_text('<script src="app.js"></script>')
            (web/'.env').write_text('placeholder-not-a-real-secret')
            with self.assertRaises(ValueError):verify(root)

    def test_pages_origin_rejects_untrusted_hosts_and_unsafe_urls(self):
        self.assertEqual(pages_origin('https://luke79210-hue.github.io/adb/'),'https://luke79210-hue.github.io')
        for value in ['http://owner.github.io/repo/','https://github.io.evil.example/','https://owner.github.io.evil.example/','https://user:pass@owner.github.io/','https://owner.github.io/?secret=bad']:
            with self.subTest(value=value),self.assertRaises(ValueError):pages_origin(value)

    def test_local_config_preserves_existing_credentials_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'.env'
            original="GOOGLE_DRIVE_ACCESS_TOKEN='fixture-not-a-token'\nULTRON_ALLOWED_ORIGINS='https://existing.example'\n"
            path.write_text(original)
            configure(path,'https://luke79210-hue.github.io/adb/')
            once=path.read_text()
            self.assertIn("GOOGLE_DRIVE_ACCESS_TOKEN='fixture-not-a-token'",once)
            self.assertIn('https://existing.example',once)
            self.assertIn('https://luke79210-hue.github.io',once)
            configure(path,'https://luke79210-hue.github.io/adb/')
            self.assertEqual(path.read_text(),once)
            self.assertEqual((path.parent/'.runtime'/'env-before-pages-setup').read_text(),original)
            self.assertEqual(path.stat().st_mode&0o777,0o600)

    def test_config_does_not_evaluate_shell_expressions(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'.env'
            text='ULTRON_ALLOWED_ORIGINS="$(printf should-not-run)"\n'
            path.write_text(text)
            with self.assertRaises(ValueError):configure(path,'https://owner.github.io/repo/')
            self.assertEqual(path.read_text(),text)
