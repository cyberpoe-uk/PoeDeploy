from pathlib import Path
import subprocess
import unittest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = next(REPO.glob('**/scripts/update.sh'))


class DashboardUpdate(unittest.TestCase):
    def test_embedded_update_uses_latest_stable_poedeploy(self):
        result = subprocess.run(['bash', '-n', str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = SCRIPT.read_text()
        self.assertNotIn('curl', text)
        self.assertNotIn('cyberpoe.uk', text)
        self.assertIn('cyberpoe-uk/PoeDeploy.git', text)
        self.assertIn('--install-dashboard pendash', text)
        self.assertNotIn('cyberpoe-uk/PenDash', text)
