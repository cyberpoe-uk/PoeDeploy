"""Security choices remain explicit and independent of the dashboard installer."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('security_choices', ROOT / 'installer/security-tools.py')
security = importlib.util.module_from_spec(spec)
spec.loader.exec_module(security)


class SecurityChoices(unittest.TestCase):
    def test_optional_actions_only_call_the_selected_installer(self):
        from unittest.mock import MagicMock
        for choice, method in [('blackarch', 'ensure_blackarch'), ('burp', 'install_burp'), ('security-tools', 'install_packages')]:
            with self.subTest(choice=choice):
                tools = MagicMock()
                with patch.object(security.sys, 'argv', ['security-tools.py', choice, '--dry-run']), patch.multiple(security, ensure_blackarch=tools.ensure_blackarch, install_burp=tools.install_burp, install_packages=tools.install_packages, PACMAN_CONFIG=tools.PACMAN_CONFIG):
                    self.assertEqual(security.main(), 0)
                getattr(tools, method).assert_called_once()
                for other in {'ensure_blackarch', 'install_burp', 'install_packages'} - {method}:
                    getattr(tools, other).assert_not_called()

    def test_tools_without_repository_fail_before_installation(self):
        from unittest.mock import MagicMock
        tools = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            tools.PACMAN_CONFIG = Path(tmp) / 'pacman.conf'
            with patch.object(security.sys, 'argv', ['security-tools.py', 'security-tools']), patch.multiple(security, ensure_blackarch=tools.ensure_blackarch, install_burp=tools.install_burp, install_packages=tools.install_packages, PACMAN_CONFIG=tools.PACMAN_CONFIG):
                with self.assertRaisesRegex(RuntimeError, 'optional BlackArch'):
                    security.main()
            tools.install_packages.assert_not_called()
            tools.ensure_blackarch.assert_not_called()
