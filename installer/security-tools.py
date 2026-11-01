#!/usr/bin/env python3
"""Explicit optional security installations, independent of dashboard refreshes."""
import argparse
import importlib.util
from pathlib import Path
import re
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('choice', choices=['blackarch', 'security-tools', 'burp'])
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    # Reuse the verified download/install routines retained for legacy callers.
    source = Path(__file__).resolve().parents[1] / 'apps/pendash/pendash.py'
    spec = importlib.util.spec_from_file_location('security_installer', source)
    tools = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tools)
    if args.choice == 'blackarch':
        tools.ensure_blackarch(args.dry_run)
    elif args.choice == 'burp':
        tools.install_burp(args.dry_run)
    else:
        if not args.dry_run and not (tools.PACMAN_CONFIG.is_file() and
                re.search(r'(?m)^\s*\[blackarch\]\s*(?:#.*)?$', tools.PACMAN_CONFIG.read_text())):
            raise RuntimeError('Select the optional BlackArch repository before installing this tool collection.')
        tools.install_packages(tools.CURATED, args.dry_run)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print('Security tools: ' + str(exc), file=sys.stderr)
        sys.exit(1)
