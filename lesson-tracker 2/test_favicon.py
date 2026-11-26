"""The portal tab icon is the school logo, not the old drawn mark."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parent


class FaviconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        env = {**os.environ, 'LESSON_DEMO': '0', 'LESSON_DB': str(Path(cls.tmp.name) / 'favicon.sqlite3'), 'LESSON_SECURE_COOKIE': '0'}
        cls.proc = subprocess.Popen(
            [sys.executable, str(ROOT / 'server.py'), '--port', '8771'],
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(60):
            try:
                urllib.request.urlopen('http://127.0.0.1:8771/health', timeout=0.2)
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError(cls.proc.stderr.read().decode()[-500:])

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.communicate(timeout=5)
        cls.tmp.cleanup()

    def get(self, path):
        try:
            response = urllib.request.urlopen('http://127.0.0.1:8771' + path, timeout=3)
            return response.status, response.read(), response.headers.get('Content-Type', '')
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers.get('Content-Type', '')

    def test_home_links_the_logo_icons(self):
        status, body, content_type = self.get('/')
        page = body.decode()
        self.assertEqual(status, 200)
        self.assertIn('text/html', content_type)
        self.assertIn('<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">', page)
        self.assertIn('<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16.png">', page)
        self.assertIn('<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">', page)
        self.assertNotIn('favicon.svg', page)
        for path, mime in (('/favicon.ico', 'image/x-icon'), ('/favicon-32.png', 'image/png'), ('/favicon-16.png', 'image/png'), ('/apple-touch-icon.png', 'image/png')):
            code, blob, kind = self.get(path)
            self.assertEqual(code, 200, path)
            self.assertIn(mime, kind)
            self.assertGreater(len(blob), 100)
        missing, _, _ = self.get('/favicon.svg')
        self.assertEqual(missing, 404)


if __name__ == '__main__':
    unittest.main()
