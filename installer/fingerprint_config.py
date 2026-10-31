#!/usr/bin/env python3
"""Configure only SDDM or Hyprlock; preserve passwords and back up before editing."""
import argparse
import glob
import os
from datetime import datetime
from pathlib import Path
import re
import shutil

BEGIN = '# BEGIN POEDEPLOY FINGERPRINT'
END = '# END POEDEPLOY FINGERPRINT'
SDDM = '''# Keep login restrictions before the fingerprint success shortcut.
auth        requisite   pam_shells.so
auth        requisite   pam_nologin.so
auth        sufficient  pam_fprintd.so max-tries=1 timeout=10'''
HYPRLOCK = '''auth {
    pam {
        enabled = true
    }
    fingerprint {
        enabled = true
        ready_message = Touch your right index finger to unlock
        present_message = Scanning fingerprint...
        retry_delay = 250
    }
}'''


def configured(text, kind):
    block = f'{BEGIN}\n{SDDM if kind == "sddm" else HYPRLOCK}\n{END}'
    if BEGIN in text or END in text:
        pattern = re.escape(BEGIN) + r'\n.*?\n' + re.escape(END)
        if text.count(BEGIN) != 1 or text.count(END) != 1 or not re.search(pattern, text, re.S):
            raise ValueError('Malformed managed fingerprint block; inspect the configuration first')
        return re.sub(pattern, lambda _: block, text, flags=re.S)
    active = '\n'.join(line.split('#', 1)[0] for line in text.splitlines())
    if kind == 'sddm':
        if 'pam_fprintd.so' in active:
            raise ValueError('Existing fingerprint PAM setup; inspect it before replacing')
        match = re.search(r'^auth\s+include\s+system-login\s*$', text, re.M)
        if not match:
            raise ValueError('Unrecognized SDDM auth stack; no changes made')
        return text[:match.start()] + block + '\n\n' + text[match.start():]
    if re.search(r'^\s*auth\s*\{', active, re.M):
        # Included files may already define authentication. Never guess at it.
        raise ValueError('Existing auth block; merge fingerprint settings manually')
    return text.rstrip() + '\n\n' + block + '\n'


def check_includes(path, text, visited=None):
    visited = set() if visited is None else visited
    visited.add(path.resolve())
    active = '\n'.join(line.split('#', 1)[0] for line in text.splitlines())
    for source in re.findall(r'^\s*source\s*=\s*(.+?)\s*$', active, re.M):
        expanded = os.path.expanduser(os.path.expandvars(source))
        if '$' in expanded:
            raise ValueError('Cannot inspect variable-based include; merge authentication manually')
        pattern = Path(expanded)
        if not pattern.is_absolute():
            pattern = path.parent / pattern
        matches = glob.glob(str(pattern))
        if not matches:
            raise ValueError(f'Cannot inspect included file: {source}')
        for match in matches:
            included = Path(match)
            if included.resolve() in visited:
                raise ValueError('Repeated or cyclic include; inspect authentication manually')
            contents = included.read_text()
            uncommented = '\n'.join(line.split('#', 1)[0] for line in contents.splitlines())
            if re.search(r'^\s*auth\s*\{', uncommented, re.M):
                raise ValueError(f'Authentication configured in {included}; merge manually')
            check_includes(included, contents, visited)


def update(path, kind):
    original = path.read_text()
    if kind == 'hyprlock':
        check_includes(path, original)
    result = configured(original, kind)
    if result == original:
        print(f'Already configured: {path}')
        return
    backup = path.with_name(path.name + '.backup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    shutil.copy2(path, backup)
    path.write_text(result)
    print(f'Updated {path}; backup: {backup}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--sddm', type=Path)
    group.add_argument('--hyprlock', type=Path)
    args = parser.parse_args()
    kind = 'sddm' if args.sddm else 'hyprlock'
    try:
        update(getattr(args, kind), kind)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Fingerprint configuration stopped: {exc}\n')


if __name__ == '__main__':
    main()
