#!/usr/bin/env python3
"""Intel desktop + NVIDIA PRIME/RTD3 setup for this Legion Y540. Standard library only."""
import argparse
import datetime
import grp
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

INTEL = '0000:00:02.0'
PCI_DEVICES = Path('/sys/bus/pci/devices')
MESA = '/usr/share/glvnd/egl_vendor.d/50_mesa.json'
GRAPHICS = ['AQ_DRM_DEVICES', '__EGL_VENDOR_LIBRARY_FILENAMES', 'GBM_BACKEND',
            '__GLX_VENDOR_LIBRARY_NAME', 'LIBVA_DRIVER_NAME', 'WLR_DRM_DEVICES',
            'DRI_PRIME', '__NV_PRIME_RENDER_OFFLOAD', '__VK_LAYER_NV_optimus']
SESSION = ['DISPLAY', 'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR', 'XAUTHORITY',
           'DBUS_SESSION_BUS_ADDRESS', 'HYPRLAND_INSTANCE_SIGNATURE'] + GRAPHICS
MATCH = re.compile(r'NVIDIA|GBM_BACKEND|GLX_VENDOR|LIBVA|WLR_DRM|AQ_DRM|DRM_DEVICES|renderD|card[01]|EGL_VENDOR|DRI_PRIME|nvidia-smi|nvtop|gpustat', re.I)
ENV_BLOCK = '''# BEGIN nvidia-offload-setup
# Intel-only desktop; prime-run restores EGL discovery for explicit offload.
unset GBM_BACKEND __GLX_VENDOR_LIBRARY_NAME LIBVA_DRIVER_NAME WLR_DRM_DEVICES
unset DRI_PRIME __NV_PRIME_RENDER_OFFLOAD __VK_LAYER_NV_optimus
export AQ_DRM_DEVICES="/dev/dri/intel-igpu"
export __EGL_VENDOR_LIBRARY_FILENAMES="/usr/share/glvnd/egl_vendor.d/50_mesa.json"
# END nvidia-offload-setup
'''
WRAPPER = '''#!/bin/sh
# Restore EGL vendor discovery for offloaded apps; retain Arch's PRIME setup.
exec env -u __EGL_VENDOR_LIBRARY_FILENAMES /usr/bin/prime-run "$@"
'''
PASSIVE = '''#!/usr/bin/env bash
# Passive monitoring: periodic nvidia-smi queries wake the GPU and prevent RTD3.
gpu=
for device in /sys/bus/pci/devices/*; do
    [ "$(cat "$device/vendor" 2>/dev/null)" = 0x10de ] || continue
    case "$(cat "$device/class" 2>/dev/null)" in
        0x030000|0x030200) gpu=$device; break ;;
    esac
done
state=$(cat "$gpu/power/runtime_status" 2>/dev/null)
label=--
case "$state" in
    suspended) label=Asleep ;;
    active) label=Active ;;
    suspending|resuming) label=Transition ;;
esac
jq -cn --arg label "$label" '{usage:0,label:$label,temperature:"--"}'
'''
XCONF = '''# SDDM-only configuration: keep its background Xorg server on Intel.
Section "ServerFlags"
    Option "AutoAddGPU" "false"
    Option "AutoBindGPU" "false"
EndSection
Section "Device"
    Identifier "Intel iGPU"
    Driver "modesetting"
    BusID "PCI:0:2:0"
EndSection
Section "Screen"
    Identifier "Intel Screen"
    Device "Intel iGPU"
EndSection
Section "ServerLayout"
    Identifier "Intel Greeter"
    Screen "Intel Screen"
EndSection
'''
SCONF = '[X11]\nServerArguments=-nolisten tcp -config /etc/X11/sddm-intel.conf\n'


def read(path):
    try:
        return Path(path).read_text(errors='replace').strip()
    except OSError:
        return ''


def env_update(old):
    # Preserve unrelated settings, including custom UWSM setup.
    old = re.sub(r'(?ms)^# BEGIN nvidia-offload-setup\n.*?^# END nvidia-offload-setup\n?', '', old)
    return old.rstrip() + '\n\n' + ENV_BLOCK


def discover_nvidia_devices(root=PCI_DEVICES):
    """Return the NVIDIA display function and same-slot NVIDIA functions."""
    displays = [device for device in root.glob('*')
                if read(device / 'vendor') == '0x10de'
                and read(device / 'class') in ('0x030000', '0x030200')]
    if len(displays) != 1:
        raise RuntimeError(f'Expected one NVIDIA display device, found {len(displays)}.')
    gpu = displays[0]
    slot = gpu.name.rsplit('.', 1)[0]
    siblings = sorted(p for p in root.glob(slot + '.*') if read(p / 'vendor') == '0x10de')
    return gpu, siblings


def dynamic_power_management(path='/proc/driver/nvidia/params'):
    match = re.search(r'^DynamicPowerManagement:\s*(\d+)\s*$', read(path), re.M)
    return int(match.group(1)) if match else None


class Setup:
    def __init__(self, args):
        self.args = args
        self.account = pwd.getpwnam(args.user)
        self.home = Path(self.account.pw_dir)
        self.gpu, self.nvidia_devices = discover_nvidia_devices()
        self.nvidia = self.gpu.name
        self.power = self.gpu / 'power'
        self.lines = []
        self.changed = []
        self.restart = []
        self.unresolved = []
        self.stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        self.state = self.home / '.local/state/nvidia-offload-setup'
        self.backup = self.state / 'backups' / self.stamp
        self.manifest = []
        self.user_env = {k: v for k, v in os.environ.items() if k in SESSION}
        self.user_env.update(HOME=str(self.home), USER=args.user, LOGNAME=args.user,
                             PATH=f'{self.home}/.local/bin:/usr/bin:/bin', LC_ALL='C')
        self.user_env.setdefault('XDG_RUNTIME_DIR', f'/run/user/{self.account.pw_uid}')
        self.user_env.setdefault('DBUS_SESSION_BUS_ADDRESS', f'unix:path={self.user_env["XDG_RUNTIME_DIR"]}/bus')
        # Also work when launched through pkexec, which clears session variables.
        rc, imported = self.run(['systemctl', '--user', 'show-environment'], user=True)
        if rc == 0:
            for line in imported.splitlines():
                key, sep, value = line.partition('=')
                if sep and key in SESSION:
                    self.user_env.setdefault(key, value)

    def log(self, text):
        print(text, flush=True)
        self.lines.append(text)

    def run(self, argv, user=False, timeout=45):
        kw = {}
        if user:
            groups = [g.gr_gid for g in grp.getgrall() if self.args.user in g.gr_mem]
            kw.update(user=self.account.pw_uid, group=self.account.pw_gid,
                      extra_groups=groups, env=self.user_env, cwd=str(self.home))
        try:
            p = subprocess.run(argv, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=timeout, **kw)
            return p.returncode, p.stdout.strip()
        except (OSError, subprocess.TimeoutExpired) as e:
            return 124, str(e)

    def owned_dir(self, path):
        missing = []
        p = path
        while not p.exists():
            missing.append(p)
            p = p.parent
        for p in reversed(missing):
            p.mkdir(mode=0o700)
            os.chown(p, self.account.pw_uid, self.account.pw_gid)

    def write(self, path, content, mode=0o644, user=False):
        path = Path(path)
        # Preserve dotfile symlinks and edit their targets.
        target = path.resolve()
        if target.exists() and target.read_text() == content and stat.S_IMODE(target.stat().st_mode) == mode:
            return False
        self.owned_dir(self.backup)
        entry = {'path': str(path), 'target': str(target), 'existed': target.exists()}
        if target.exists():
            dest = self.backup / str(len(self.manifest))
            shutil.copy2(target, dest)
            os.chmod(dest, 0o600)
            os.chown(dest, self.account.pw_uid, self.account.pw_gid)
            entry['backup'] = str(dest)
            entry['mode'] = stat.S_IMODE(target.stat().st_mode)
        self.manifest.append(entry)
        manifest = self.backup / 'manifest.json'
        manifest.write_text(json.dumps(self.manifest, indent=2) + '\n')
        os.chown(manifest, self.account.pw_uid, self.account.pw_gid)
        if user:
            self.owned_dir(target.parent)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
        # Replace complete files atomically, while leaving the logical symlink intact.
        fd, temporary = tempfile.mkstemp(prefix='.' + target.name + '.', dir=target.parent)
        try:
            with os.fdopen(fd, 'w') as out:
                out.write(content)
                out.flush()
                os.fsync(out.fileno())
            os.chmod(temporary, mode)
            if user:
                os.chown(temporary, self.account.pw_uid, self.account.pw_gid)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self.changed.append(str(path))
        self.log(f'CHANGED {path}')
        return True

    def prerequisites(self):
        if read(PCI_DEVICES / INTEL / 'vendor') != '0x8086':
            raise RuntimeError(f'Expected Intel GPU at {INTEL} not found. This script targets the Legion Y540 mapping.')
        if read(self.gpu / 'device') != '0x2191':
            raise RuntimeError('Expected GTX 1660 Ti Mobile (10de:2191). Refusing another hardware configuration.')
        self.log(f'Detected NVIDIA display device: {self.nvidia}')
        self.log('Detected NVIDIA same-slot functions: ' + ', '.join(p.name for p in self.nvidia_devices))
        required = {'glxinfo': 'mesa-utils', 'prime-run': 'nvidia-prime', 'jq': 'jq'}
        missing = sorted({pkg for cmd, pkg in required.items() if not Path('/usr/bin', cmd).exists()})
        if missing and self.args.apply and self.args.install_missing:
            self.log('Installing missing utilities: ' + ', '.join(missing))
            subprocess.run(['/usr/bin/pacman', '-S', '--needed', *missing], check=True)
            missing = []
        if missing:
            raise RuntimeError('Missing utilities: ' + ', '.join(missing) + '. Install them or use --apply --install-missing.')
        if not Path(MESA).exists() or not Path('/proc/driver/nvidia/version').exists():
            raise RuntimeError('Mesa EGL and a working, loaded NVIDIA driver are prerequisites. No driver replacement is attempted.')

    def audit(self):
        self.log('Inspecting configuration (matches in unused presets/backups are not necessarily active):')
        roots = [self.home / p for p in ['.config/hypr', '.config/uwsm', '.config/environment.d',
                 '.config/eww', '.config/waybar', '.config/systemd/user', '.profile', '.bash_profile',
                 '.zprofile', '.bashrc', '.zshrc']]
        roots += [Path(p) for p in ['/etc/environment', '/etc/environment.d', '/etc/profile.d',
                  '/etc/modprobe.d', '/usr/lib/modprobe.d', '/etc/udev/rules.d', '/etc/sddm.conf.d']]
        for root in roots:
            files = [root] if root.is_file() else sorted(root.rglob('*')) if root.exists() else []
            for p in files:
                if not p.is_file() or any(x in p.parts for x in ['backups', '.git']):
                    continue
                if p.stat().st_size > 500_000:
                    continue
                for n, line in enumerate(read(p).splitlines(), 1):
                    if MATCH.search(line):
                        self.log(f'  {p}:{n}: {line[:300]}')
        for m in ['nvidia', 'nvidia_modeset', 'nvidia_drm', 'nvidia_uvm']:
            self.log(f'  {m} module references: {read(f"/sys/module/{m}/refcnt") or "not loaded"}')
        self.log('Power services: ' + self.run(['systemctl', 'is-active', 'tlp', 'power-profiles-daemon',
                 'upower', 'nvidia-persistenced'])[1].replace('\n', ', '))
        self.log('No nvidia-smi polling, forced module unloading, or service disabling is used.')

    def apply(self):
        env = self.home / '.config/uwsm/env-hyprland'
        if self.write(env, env_update(env.read_text() if env.exists() else ''), user=True):
            self.restart.append('New UWSM environment takes effect on the next login.')
        wrapper = self.home / '.local/bin/prime-run'
        old = read(wrapper)
        shell_lines = '\n'.join(s.strip() for s in old.splitlines() if s.strip() and not s.lstrip().startswith('#'))
        known_wrapper = 'exec env -u __EGL_VENDOR_LIBRARY_FILENAMES /usr/bin/prime-run "$@"'
        if old and shell_lines != known_wrapper:
            self.unresolved.append(f'Unrecognized custom launcher {wrapper}; preserved. Remove the EGL restriction before invoking /usr/bin/prime-run.')
        else:
            self.write(wrapper, WRAPPER, 0o755, user=True)
        rule = Path('/etc/udev/rules.d/intel-igpu-dev-path.rules')
        if not rule.exists():
            self.write(rule, f'SUBSYSTEM=="drm", KERNEL=="card[0-9]*", KERNELS=="{INTEL}", SYMLINK+="dri/intel-igpu"\n')
        # Preserve the existing working symlink rule exactly.
        pm = Path('/etc/modprobe.d/nvidia-pm.conf')
        old = pm.read_text() if pm.exists() else ''
        if re.search(r'NVreg_DynamicPowerManagement\s*=\s*(?:0x0?2|2)\b', old):
            changed_pm = False
        elif 'NVreg_DynamicPowerManagement' in old:
            self.unresolved.append(f'{pm} contains a different RTD3 mode; inspect it before changing it.')
            changed_pm = False
        else:
            changed_pm = self.write(pm, old.rstrip() + '\noptions nvidia NVreg_DynamicPowerManagement=0x02\n')
        # Apply to all four PCI functions, including USB and audio, without removing devices.
        rule_pm = Path('/etc/udev/rules.d/81-nvidia-offload-runtime.rules')
        slot = self.nvidia.rsplit('.', 1)[0]
        self.write(rule_pm, '# Runtime PM for the detected laptop GPU and its companion PCI functions.\n'
                   f'ACTION=="add|bind", SUBSYSTEM=="pci", KERNEL=="{slot}.*", ATTR{{vendor}}=="0x10de", TEST=="power/control", ATTR{{power/control}}="auto"\n')
        rc, out = self.run(['udevadm', 'control', '--reload-rules'])
        if rc:
            raise RuntimeError('Cannot reload udev rules: ' + out)
        for p in Path('/sys/class/drm').glob('card[0-9]*'):
            if '-' not in p.name and (p / 'device').resolve().name == INTEL:
                rc, out = self.run(['udevadm', 'trigger', '--action=add', str(p)])
                if rc:
                    raise RuntimeError(out)
        self.run(['udevadm', 'settle'])
        for p in self.nvidia_devices:
            if (p / 'power/control').exists():
                (p / 'power/control').write_text('auto\n')
        if self.run(['systemctl', 'is-active', '--quiet', 'sddm'])[0] == 0:
            if self.write('/etc/X11/sddm-intel.conf', XCONF) | self.write('/etc/sddm.conf.d/90-intel-greeter.conf', SCONF):
                self.restart.append('SDDM configuration changed; save work and reboot to activate it if its Xorg still uses NVIDIA.')
        # The proven dashboard fix. Do not rewrite unrelated scripts based on a keyword.
        gpu = self.home / '.config/eww/scripts/gpu.sh'
        old = read(gpu)
        if 'nvidia-smi --query-gpu=utilization.gpu,temperature.gpu' in old and 'temperature:$temperature' in old:
            self.write(gpu, PASSIVE, 0o755, user=True)
        elif re.search(r'^[^#\n]*nvidia-smi', old, re.M):
            self.unresolved.append(f'Unrecognized NVIDIA poller {gpu}; replace its active GPU queries with passive runtime_status reads.')
        lua = self.home / '.config/hypr/conf/environment.lua'
        old = lua.read_text() if lua.exists() else ''
        # Handle the known ML4W selector, retaining all other Lua configuration.
        new = re.sub(r'(local\s+name\s*=\s*[\"\'])nvidia\.lua([\"\'])', r'\1default.lua\2', old)
        if new != old and (lua.parent / 'environments/default.lua').exists():
            self.write(lua, new, user=True)
            self.restart.append('Disabled the ML4W NVIDIA preset; start a fresh UWSM login.')
        if changed_pm:
            self.restart.append('RTD3 module option changed; reboot to load it.')
            self.log('Rebuilding initramfs for the new module option...')
            rc, out = self.run(['mkinitcpio', '-P'], timeout=600)
            self.log(out)
            if rc:
                raise RuntimeError('Initramfs rebuild failed. Fix the reported error before rebooting.')

    def clients(self):
        devices = set()
        for p in list(Path('/dev').glob('nvidia*')) + list(Path('/dev/dri/by-path').glob(f'pci-{self.nvidia}-*')):
            try:
                s = p.stat()
                if stat.S_ISCHR(s.st_mode):
                    devices.add(s.st_rdev)
            except OSError:
                pass
        found = []
        for proc in Path('/proc').glob('[0-9]*'):
            handles = set()
            try:
                for fd in (proc / 'fd').iterdir():
                    try:
                        s = fd.stat()
                        if stat.S_ISCHR(s.st_mode) and s.st_rdev in devices:
                            handles.add(os.readlink(fd))
                    except OSError:
                        pass
                # mmap can retain a device after its descriptor has been closed.
                for line in read(proc / 'maps').splitlines():
                    if re.search(r'/dev/nvidia(?:\d|ctl|modeset|uvm)', line):
                        handles.add(line.split()[-1])
            except (OSError, ProcessLookupError):
                continue
            if handles:
                found.append(f'{proc.name} {read(proc / "comm")}: {", ".join(sorted(handles))}')
        return found

    def desktop(self):
        good = True
        procs = []
        for p in Path('/proc').glob('[0-9]*'):
            try:
                if read(p / 'comm') == 'Hyprland' and p.stat().st_uid == self.account.pw_uid:
                    procs.append(p)
            except OSError:
                continue  # Processes can exit between listing /proc and stat().
        if not procs:
            self.log('FAIL: no live Hyprland process for this user. Run verification from the desktop.')
            return False
        for p in procs:
            try:
                env = dict(x.split('=', 1) for x in (p / 'environ').read_text().split('\0') if '=' in x)
            except OSError as e:
                self.log(f'FAIL: cannot inspect Hyprland: {e}')
                return False
            for key, wanted in [('AQ_DRM_DEVICES', '/dev/dri/intel-igpu'), ('__EGL_VENDOR_LIBRARY_FILENAMES', MESA)]:
                self.log(f'Hyprland {p.name}: {key}={env.get(key, "<unset>")}')
                good &= env.get(key) == wanted
        intel_node = Path('/dev/dri/intel-igpu').resolve()
        good &= (Path('/sys/class/drm') / intel_node.name / 'device').resolve().name == INTEL
        clients = self.clients()
        for c in clients:
            self.log('NVIDIA client: ' + c)
        if any(' Hyprland:' in c or ' Xorg:' in c for c in clients):
            good = False
        if not good:
            self.log('FAIL: compositor/display-manager setup is not fully active; inspect clients and start a fresh session/reboot as needed.')
        return good

    def idle(self, label):
        self.log(f'{label}: waiting up to {self.args.wait}s for NVIDIA to suspend (passive sysfs checks).')
        deadline = time.monotonic() + self.args.wait
        while time.monotonic() < deadline:
            statuses = {p.name: read(p / 'power/runtime_status') for p in self.nvidia_devices}
            controls = {p.name: read(p / 'power/control') for p in self.nvidia_devices}
            if statuses and all(value == 'auto' for value in controls.values()) and all(value == 'suspended' for value in statuses.values()):
                before = {p.name: int(read(p / 'power/runtime_suspended_time')) for p in self.nvidia_devices}
                time.sleep(5)
                after = {p.name: int(read(p / 'power/runtime_suspended_time')) for p in self.nvidia_devices}
                # Require essentially all five seconds asleep, not just a brief transition.
                statuses = {p.name: read(p / 'power/runtime_status') for p in self.nvidia_devices}
                if all(value == 'suspended' for value in statuses.values()) and all(after[k] - before[k] >= 4500 for k in before):
                    self.log(f'PASS {label}: all NVIDIA functions suspended.')
                    for p in self.nvidia_devices:
                        self.log(f'PASS {p.name}: control={read(p / "power/control")}, status={statuses[p.name]}, suspended_ms={before[p.name]} -> {after[p.name]}')
                    return True
            time.sleep(1)
        self.log(f'FAIL {label}: NVIDIA functions did not all remain suspended.')
        for p in self.nvidia_devices:
            self.log(f'  {p.name}: control={read(p / "power/control")}, status={read(p / "power/runtime_status")}, suspended_ms={read(p / "power/runtime_suspended_time")}')
        for c in self.clients():
            self.log('NVIDIA client: ' + c)
        power_state = read('/proc/driver/nvidia/gpus/' + self.nvidia + '/power')
        if power_state:
            self.log(power_state)
        else:
            self.log('SKIP NVIDIA /proc power state is unavailable; sysfs remains authoritative.')
        return False

    def driver_state(self):
        value = dynamic_power_management()
        if value == 2:
            self.log('PASS loaded NVIDIA driver: DynamicPowerManagement=2')
            return True
        shown = 'unavailable' if value is None else str(value)
        self.log(f'REBOOT REQUIRED: loaded NVIDIA driver reports DynamicPowerManagement={shown}, expected 2.')
        self.log('CONFIGURED: NVIDIA PRIME/RTD3 settings installed or already correct.')
        self.log('POST-REBOOT VERIFICATION: pending; runtime suspension retries were skipped.')
        self.log('Expected after reboot: DynamicPowerManagement=2, Runtime D3 enabled, and NVIDIA functions suspended while idle.')
        return False

    def configuration_state(self):
        module_config = read('/etc/modprobe.d/nvidia-pm.conf')
        rule_config = read('/etc/udev/rules.d/81-nvidia-offload-runtime.rules')
        slot = self.nvidia.rsplit('.', 1)[0]
        module_ok = bool(re.search(r'NVreg_DynamicPowerManagement\s*=\s*(?:0x0?2|2)\b', module_config))
        rule_ok = f'KERNEL=="{slot}.*"' in rule_config and 'ATTR{power/control}="auto"' in rule_config
        if module_ok and rule_ok:
            self.log('PASS configuration installed: NVIDIA DynamicPowerManagement=2 and same-slot runtime-PM rule.')
            return True
        self.log('FAIL configuration incomplete: expected NVIDIA module option and detected-slot runtime-PM rule.')
        return False

    def proc_power(self):
        text = read('/proc/driver/nvidia/gpus/' + self.nvidia + '/power')
        if not text:
            self.log('SKIP NVIDIA /proc power state is unavailable; verified with sysfs instead.')
            return True
        rtd3 = re.search(r'^Runtime D3 status:\s*(.+)$', text, re.M)
        memory = re.search(r'^Video Memory:\s*(.+)$', text, re.M)
        rtd3_ok = bool(rtd3 and rtd3.group(1).strip().lower().startswith('enabled'))
        memory_ok = bool(memory and memory.group(1).strip().lower() == 'off')
        self.log(('PASS' if rtd3_ok else 'FAIL') + ' NVIDIA RTD3: ' + (rtd3.group(1).strip() if rtd3 else 'unknown'))
        self.log(('PASS' if memory_ok else 'FAIL') + ' NVIDIA video memory idle state: ' + (memory.group(1).strip() if memory else 'unknown'))
        return rtd3_ok and memory_ok

    def verify(self):
        desktop_ok = self.desktop()
        rc, output = self.run(['/usr/bin/glxinfo', '-B'], user=True)
        renderers = [s for s in output.splitlines() if 'OpenGL renderer' in s]
        self.log('Normal: ' + ('; '.join(renderers) or output))
        intel_ok = rc == 0 and any('Intel' in s for s in renderers)
        idle_before = self.idle('Before offload')
        proc_before = self.proc_power() if idle_before else False
        wrapper = self.home / '.local/bin/prime-run'
        launcher = str(wrapper) if wrapper.exists() else '/usr/bin/prime-run'
        rc, output = self.run([launcher, '/usr/bin/glxinfo', '-B'], user=True)
        renderers = [s for s in output.splitlines() if 'OpenGL renderer' in s]
        self.log('PRIME: ' + ('; '.join(renderers) or output))
        prime_ok = rc == 0 and any('NVIDIA' in s for s in renderers)
        self.log(('PASS' if intel_ok else 'FAIL') + ' Intel is primary renderer')
        self.log(('PASS' if prime_ok else 'FAIL') + ' NVIDIA PRIME offload works')
        idle_after = self.idle('After offload')
        proc_after = self.proc_power() if idle_after else False
        clients = self.clients()
        if clients:
            self.log('Remaining NVIDIA clients:\n' + '\n'.join(clients))
        good = all([desktop_ok, intel_ok, prime_ok, idle_before, idle_after, proc_before, proc_after, not clients])
        self.log('PASS: Intel desktop, NVIDIA PRIME and return to idle suspend verified.' if good else 'FAIL: full offload/suspend behavior not yet verified.')
        return good

    def report(self):
        self.owned_dir(self.state)
        path = self.state / f'report-{self.stamp}.txt'
        path.write_text('\n'.join(self.lines) + '\n')
        os.chmod(path, 0o600)
        os.chown(path, self.account.pw_uid, self.account.pw_gid)
        print(f'Report: {path}')
        if self.manifest:
            print(f'Backups and restore manifest: {self.backup}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='Back up and install known fixes, then verify.')
    mode.add_argument('--check', action='store_true', help='Audit and verify without changing configuration (default).')
    mode.add_argument('--retry', action='store_true', help='Repeat verification after logout/reboot or closing GPU apps; no config edits.')
    parser.add_argument('--user', default=os.environ.get('SUDO_USER') or pwd.getpwuid(os.getuid()).pw_name)
    parser.add_argument('--attempts', type=int, default=1, help='Bounded verification attempts, 1–10 (default 1).')
    parser.add_argument('--wait', type=int, default=45, help='Seconds allowed for each idle transition, 10–300 (default 45).')
    parser.add_argument('--install-missing', action='store_true', help='With --apply, offer pacman installation of missing test utilities only.')
    args = parser.parse_args()
    if not 1 <= args.attempts <= 10 or not 10 <= args.wait <= 300:
        parser.error('--attempts must be 1–10 and --wait 10–300')
    if args.user == 'root':
        parser.error('Run from your normal desktop terminal, or specify --user cyberpoe.')
    if os.geteuid() != 0:
        # Administrator visibility is essential: plain lsof misses SDDM's root-owned Xorg.
        os.execvp('sudo', ['sudo', '--preserve-env=' + ','.join(SESSION),
                          '/usr/bin/python3', str(Path(__file__).resolve()), *sys.argv[1:], '--user', args.user])
    setup = Setup(args)
    code = 4
    try:
        setup.log('NVIDIA offload setup: ' + ('APPLY' if args.apply else 'CHECK / RETRY'))
        setup.prerequisites()
        setup.audit()
        if args.apply:
            setup.apply()
        if not setup.configuration_state():
            code = 2
            for note in setup.unresolved:
                setup.log('REVIEW: ' + note)
            return code
        if not setup.driver_state():
            if not any('RTD3 module option' in note for note in setup.restart):
                setup.restart.append('Loaded NVIDIA module predates the RTD3 configuration; reboot to activate it.')
            code = 3
            for note in setup.restart:
                setup.log('NEXT LOGIN/BOOT: ' + note)
            for note in setup.unresolved:
                setup.log('REVIEW: ' + note)
            return code
        for attempt in range(1, args.attempts + 1):
            setup.log(f'Verification attempt {attempt}/{args.attempts}')
            if setup.verify():
                code = 0 if not setup.unresolved else 2
                break
            code = 3 if setup.restart else 2
            if attempt < args.attempts:
                setup.log('Retrying in 5 seconds; no driver unload or desktop restart.')
                time.sleep(5)
        for note in setup.restart:
            setup.log('NEXT LOGIN/BOOT: ' + note)
        for note in setup.unresolved:
            setup.log('REVIEW: ' + note)
        if code:
            setup.log('Next: close GPU workloads/monitors, resolve reported active overrides, then rerun --retry --attempts 3 --wait 60.')
            setup.log('If desktop environment or module settings are stale, save work and reboot first. Retries cannot update a running compositor environment.')
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as e:
        setup.log('ERROR: ' + str(e))
        code = 4
    except KeyboardInterrupt:
        setup.log('Interrupted. Applied changes and backups are retained; no background retry is running.')
        code = 130
    finally:
        setup.report()
    return code


if __name__ == '__main__':
    sys.exit(main())
