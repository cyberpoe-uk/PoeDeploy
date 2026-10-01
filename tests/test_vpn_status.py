"""Exercise both VPN collectors with installed/missing and login states."""
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ('apps/poedash/assets/scripts/vpn.sh', 'apps/pendash/dashboard/scripts/vpn.sh')


class VpnStatus(unittest.TestCase):
    def test_missing_disconnected_and_connected_clients(self):
        for installed, backend, expected in (
                (False, '', 'Not installed'),
                (True, 'Stopped', 'Disconnected'),
                (True, 'NeedsLogin', 'Login required'),
                (True, 'Running', 'Connected')):
            for script in SCRIPTS:
                with self.subTest(script=script, backend=backend, installed=installed):
                    body = r'''
command() {
    if [[ "$1" == -v ]]; then
        case "$2" in tailscale|protonvpn-app|protonvpn|proton-vpn) [[ "$installed" == true ]]; return ;; esac
    fi
    builtin command "$@"
}
pacman() { return 1; }
ip() { echo '[]'; }
timeout() { shift; "$@"; }
tailscale() { printf '{"BackendState":"%s"}\n' "$backend"; }
source "$collector"
'''
                    result = subprocess.run(['bash', '-c', body], text=True,
                        capture_output=True, check=True, timeout=5,
                        env=os.environ | {
                            'installed': str(installed).lower(), 'backend': backend,
                            'collector': str(ROOT / script)})
                    data = json.loads(result.stdout)
                    self.assertEqual(data['tailscale_state'], expected)
                    self.assertEqual(data['proton_state'], 'Disconnected' if installed else 'Not installed')
                    self.assertEqual(data['tailscale'], backend == 'Running')
