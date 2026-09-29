"""Strict, shared configuration validation. Commands are argv arrays, never eval."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMES = ('burp', 'firefox', 'terminal', 'code', 'wireshark')


def load(root=ROOT):
    data = json.loads((Path(root) / 'settings.json').read_text())
    def require(condition, message):
        if not condition:
            raise ValueError('settings.json: ' + message)
    def integer(value, low, high):
        return type(value) is int and low <= value <= high
    require(set(data) == {'monitor', 'layout', 'launchers', 'web_ctf'}, 'unexpected or missing top-level keys')
    m = data['monitor']
    require(integer(m, 0, 100) or (isinstance(m, str) and bool(m) and '\n' not in m), 'monitor must be an index or output name')
    layout = data['layout']
    require(set(layout) == {'scale', 'system_width', 'network_width', 'lower_height'}, 'invalid layout keys')
    scale = layout['scale']
    require(scale == 'auto' or (type(scale) in (int, float) and .5 <= scale <= 2), 'scale must be auto or 0.5–2')
    for k in ('system_width', 'network_width', 'lower_height'):
        require(integer(layout[k], 100, 1500), k + ' must be an integer from 100 to 1500')
    require(set(data['launchers']) == set(NAMES), 'keep all five launcher IDs')
    for name, app in data['launchers'].items():
        require(set(app) == {'label', 'workspace', 'command', 'classes'}, name + ': invalid keys')
        require(isinstance(app['label'], str) and 0 < len(app['label']) <= 30 and '${' not in app['label'] and not any(ord(c) < 32 for c in app['label']), name + ': invalid label')
        require(integer(app['workspace'], 2, 99), name + ': workspace must be 2–99 (1 is reserved)')
        for key in ('command', 'classes'):
            require(isinstance(app[key], list) and all(isinstance(x, str) and x and not any(ord(c) < 32 for c in x) for x in app[key]), name + ': ' + key + ' must be an array of nonempty strings')
        require(bool(app['classes']), name + ': provide window classes for reuse')
        require(bool(app['command']) or name in ('burp', 'firefox', 'code'), name + ': command is required')
    web = data['web_ctf']
    require(set(web) == {'apps', 'workspace'}, 'invalid web_ctf keys')
    require(isinstance(web['apps'], list) and bool(web['apps']) and all(x in NAMES for x in web['apps']), 'web_ctf.apps must contain known launcher IDs')
    require(integer(web['workspace'], 2, 99), 'web_ctf.workspace must be 2–99')
    return data
