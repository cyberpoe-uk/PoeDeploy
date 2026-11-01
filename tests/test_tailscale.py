"""Tailscale desktop integration with no package, privilege or session changes."""
import os
from pathlib import Path
import tempfile
import unittest
from test_workflows import run_bash


class TailscaleDesktop(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.fixture = r'''
original_user_runner=$(declare -f tailscale_as_user)
TS_TEST_HOME=HOME_PLACEHOLDER
id() { case "$1" in -u) echo "${TEST_UID:-1000}" ;; -un) echo alice ;; esac; }
getent() { printf 'alice:x:1000:1000:Alice:%s:/bin/bash\n' "$TS_TEST_HOME"; }
loginctl() { return 1; }
pgrep() { return 1; }
unset XDG_CONFIG_HOME DISPLAY WAYLAND_DISPLAY
systemctl() { [[ "${TEST_DAEMON:-yes}" == yes ]]; }
tailscale() {
    case "$*" in
        version) echo "${TEST_VERSION:-1.88.0}" ;;
        'systray --help'|'configure systray --help') [[ "${TEST_HELP:-yes}" == yes ]] ;;
        *) echo "TS:$*" ;;
    esac
}
sudo() { echo "PRIV:$*"; [[ "${TEST_OPERATOR:-yes}" == yes ]]; }
tailscale_as_user() {
    printf 'USER:%s:%s\n' "$TS_USER" "$*"
    [[ "$*" != 'systemctl --user daemon-reload' || "${TEST_BUS:-yes}" == yes ]]
}
'''.replace('HOME_PLACEHOLDER', "'" + str(self.home) + "'")

    def check(self, body):
        r = run_bash(self.fixture + body)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout + r.stderr

    def desktop(self):
        (self.home / '.config/hypr').mkdir(parents=True)
        (self.home / '.config/hypr/hyprland.lua').touch()

    def test_current_user_and_sudo_target_detection(self):
        self.check('tailscale_desktop_user\n[[ "$TS_USER:$TS_UID" == alice:1000 ]]\nTEST_UID=0\nSUDO_USER=alice\ntailscale_desktop_user\n[[ "$TS_USER" == alice ]]')

    def test_invalid_root_system_and_missing_users_are_rejected(self):
        self.check(r'''
TEST_UID=0
for SUDO_USER in root nobody '' '-bad' 'alice;command'; do
    if tailscale_desktop_user; then exit 91; fi
done
SUDO_USER=alice
getent() { echo 'alice:x:99:99:Service:/tmp:/usr/bin/nologin'; }
if tailscale_desktop_user; then exit 92; fi
getent() { return 2; }
if tailscale_desktop_user; then exit 93; fi
''')

    def test_operator_and_official_service_before_authentication_are_idempotent(self):
        self.desktop()
        out = self.check('configure_tailscale_desktop\nconfigure_tailscale_desktop')
        self.assertEqual(out.count('PRIV:tailscale set --operator=alice'), 2)
        self.assertEqual(out.count('USER:alice:tailscale configure systray --enable-startup=systemd'), 2)
        self.assertEqual(out.count('USER:alice:systemctl --user start tailscale-systray.service'), 2)
        self.assertIn('systemctl --user enable tailscale-systray.service', out)
        self.assertNotIn('tailscale up', out)
        self.assertNotIn('logout', out)
        self.assertNotIn('reset', out)
        self.assertIn('without sudo', out)
        self.assertIn('Restart=on-failure', out)

    def test_old_version_or_missing_commands_keep_operator_and_networking(self):
        self.desktop()
        for setting in ('TEST_VERSION=1.86.5', 'TEST_HELP=no', 'TEST_VERSION=invalid'):
            out = self.check(setting + '\nconfigure_tailscale_desktop')
            self.assertIn('set --operator=alice', out)
            self.assertIn('1.88', out)
            self.assertNotIn('USER:alice:tailscale configure', out)

    def test_headless_and_chroot_skip_desktop_integration(self):
        out = self.check('configure_tailscale_desktop\nPOEDEPLOY_IN_CHROOT=true\nconfigure_tailscale_desktop')
        self.assertIn('No graphical desktop', out)
        self.assertIn('deferred until boot', out)
        self.assertNotIn('PRIV:', out)
        self.assertNotIn('USER:', out)

    def test_daemon_required_and_missing_binary_is_actionable(self):
        out = self.check('TEST_DAEMON=no\nconfigure_tailscale_desktop\nunset -f tailscale\ncommand() { return 1; }\nconfigure_tailscale_desktop')
        self.assertIn('tailscaled is not running', out)
        self.assertIn('binary is missing', out)
        self.assertNotIn('PRIV:', out)

    def test_unavailable_bus_defers_start_until_login(self):
        self.desktop()
        out = self.check('TEST_BUS=no\nconfigure_tailscale_desktop')
        self.assertIn('default.target.wants', out)
        self.assertIn('next desktop login', out)
        self.assertNotIn('USER:alice:systemctl --user start', out)

    def test_existing_autostart_and_manual_instance_do_not_duplicate(self):
        self.desktop()
        directory = self.home / '.config/autostart'
        directory.mkdir()
        entry = directory / 'tailscale-systray.desktop'
        entry.touch()
        out = self.check('configure_tailscale_desktop')
        self.assertIn('existing Tailscale tray autostart', out)
        self.assertNotIn('USER:', out)
        entry.unlink()
        out = self.check("pgrep() { return 0; }\ntailscale_as_user() { echo \"USER:$*\"; [[ \"$*\" != 'systemctl --user is-active --quiet tailscale-systray.service' ]]; }\nconfigure_tailscale_desktop")
        self.assertIn('manually started', out)
        self.assertNotIn('USER:systemctl --user start', out)

    def test_operator_failure_is_optional(self):
        self.desktop()
        out = self.check('TEST_OPERATOR=no\nconfigure_tailscale_desktop')
        self.assertIn('Could not set', out)
        self.assertIn('USER:alice:tailscale configure', out)

    def test_user_runner_sets_correct_home_and_session_environment(self):
        self.check(r'''
eval "$original_user_runner"
tailscale_desktop_user
tailscale_as_user sh -c 'test "$HOME" = "$XDG_CONFIG_HOME/.." || test "$XDG_CONFIG_HOME" = "$HOME/.config"; test "$USER" = alice; test "$XDG_RUNTIME_DIR" = /run/user/1000; test "$DBUS_SESSION_BUS_ADDRESS" = unix:path=/run/user/1000/bus'
TEST_UID=0
sudo() { printf 'IDENTITY:%s\n' "$*"; }
result=$(tailscale_as_user true)
[[ "$result" == *'-H -u alice -- env HOME='* ]]
''')

    def test_repeated_setup_writes_one_identical_dropin(self):
        self.desktop()
        self.check(r'''
tailscale_as_user() {
    if [[ "$1" == sh ]]; then
        env HOME="$TS_HOME" XDG_CONFIG_HOME="$TS_CONFIG" "$@"
    fi
}
configure_tailscale_desktop
before=$(cat "$TS_TEST_HOME/.config/systemd/user/tailscale-systray.service.d/poedeploy.conf")
configure_tailscale_desktop
[[ "$before" == "$(cat "$TS_TEST_HOME/.config/systemd/user/tailscale-systray.service.d/poedeploy.conf")" ]]
''')
        files = list((self.home / '.config/systemd/user').rglob('*'))
        self.assertEqual([p.name for p in files if p.is_file()], ['poedeploy.conf'])

    def test_existing_official_service_is_reused_and_custom_service_is_preserved(self):
        self.desktop()
        directory = self.home / '.config/systemd/user'
        directory.mkdir(parents=True)
        service = directory / 'tailscale-systray.service'
        service.write_text('[Service]\nExecStart=/usr/bin/tailscale systray\n')
        out = self.check('configure_tailscale_desktop')
        self.assertNotIn('USER:alice:tailscale configure', out)
        self.assertIn('systemctl --user enable', out)
        service.write_text('[Service]\nExecStart=/custom/tray\n')
        out = self.check('configure_tailscale_desktop')
        self.assertIn('custom tailscale-systray.service', out)
        self.assertEqual(service.read_text(), '[Service]\nExecStart=/custom/tray\n')

    def test_offline_enablement_creates_one_link_without_a_session_bus(self):
        self.desktop()
        directory = self.home / '.config/systemd/user'
        directory.mkdir(parents=True)
        service = directory / 'tailscale-systray.service'
        service.write_text('[Service]\nExecStart=/usr/bin/tailscale systray\n[Install]\nWantedBy=default.target\n')
        out = self.check(r'''
tailscale_as_user() {
    if [[ "$1" == sh ]]; then
        env HOME="$TS_HOME" XDG_CONFIG_HOME="$TS_CONFIG" "$@"
    elif [[ "$*" == 'systemctl --user daemon-reload' ]]; then
        return 1
    else
        echo "UNEXPECTED:$*"
        return 99
    fi
}
configure_tailscale_desktop
configure_tailscale_desktop
''')
        self.assertEqual(out.count('next desktop login'), 2)
        self.assertNotIn('UNEXPECTED:', out)
        links = list((directory / 'default.target.wants').iterdir())
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].resolve(), service)

    def test_optional_configuration_failure_keeps_installation_flow_successful(self):
        self.desktop()
        out = self.check(r'''
tailscale_as_user() { return 1; }
configure_tailscale_desktop
echo INSTALLATION_CONTINUES
''')
        self.assertIn('Optional tray configuration failed', out)
        self.assertIn('INSTALLATION_CONTINUES', out)
