"""Strict PoeDash configuration validation."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
def load(root=ROOT):
    data = json.loads((Path(root) / 'settings.json').read_text())
    def require(condition, message):
        if not condition:
            raise ValueError('settings.json: ' + message)
    def integer(value, low, high):
        return type(value) is int and low <= value <= high
    require(set(data) == {'name', 'monitor', 'calendar'}, 'unexpected or missing top-level keys')
    name = data['name']
    require(isinstance(name, str) and 1 <= len(name.strip()) <= 32 and
            not any(ord(c) < 32 for c in name), 'name must contain 1–32 printable characters')
    m = data['monitor']
    require(integer(m, 0, 100) or (isinstance(m, str) and bool(m) and '\n' not in m), 'monitor must be an index or output name')
    calendar = data['calendar']
    require(isinstance(calendar, str) and 1 <= len(calendar) <= 200 and not any(ord(c) < 32 for c in calendar), 'calendar must be an application ID, auto or google')
    data['name'] = name.strip()
    return data
