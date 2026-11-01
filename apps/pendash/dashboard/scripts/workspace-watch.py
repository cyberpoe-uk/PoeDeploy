#!/usr/bin/env python3
"""Compatibility entry point for older PenDash configurations."""
import os
from pathlib import Path
import sys

if __name__ == '__main__':
    os.execv(sys.executable, [sys.executable, str(Path(__file__).with_name('workspace.py')), '--listen'])
