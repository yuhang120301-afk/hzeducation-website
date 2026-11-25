"""Boss and teacher pay pages must render without a missing function."""
import subprocess
import unittest
from pathlib import Path


class PayPageSmokeTests(unittest.TestCase):
    def test_boss_and_teacher_pay_views_render(self):
        script = Path(__file__).resolve().parent / 'test_pay_smoke.js'
        completed = subprocess.run(['node', str(script)], capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == '__main__':
    unittest.main()
