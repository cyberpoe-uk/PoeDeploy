"""Persistent dashboard profiles, edit transactions, geometry and local history.

This module has no GUI dependencies so validation and layout behaviour can be
checked without a running compositor.
"""
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import time

CARDS = {
    'arch': ('Arch', 'Packages, updates and uptime'),
    'system': ('System', 'Hardware and operating system'),
    'performance': ('Performance', 'Usage, temperatures and history'),
    'processes': ('Top Processes', 'Sort, filter and inspect running processes'),
    'connectivity': ('Connectivity', 'Addresses, VPNs and network traffic'),
    'player': ('Player', 'Media controls, artwork and audio visualiser'),
    'shares': ('Mounted Shares', 'Open mounted SMB and NFS folders'),
    'session': ('Session & Idle', 'Screen, lock and suspend timers'),
    'power': ('Power', 'Source, profile, battery and consumption'),
    'calendar': ('Calendar', 'Month and Thunderbird agenda'),
    'notes': ('Notes', 'A private note saved on this machine'),
    'tasks': ('Tasks', 'A local checklist'),
    'weather': ('Weather', 'Forecast for a town or city you choose'),
    'feeds': ('RSS Feeds', 'Headlines from your RSS or Atom feeds'),
    'containers': ('Containers', 'Local Docker container status'),
    'nas': ('NAS', 'Storage and status from a configured JSON endpoint'),
    'remote': ('Remote Machine', 'Metrics from a configured JSON endpoint'),
}
BASE_CARDS = list(CARDS)[:10]
REFRESH = {'cpu': 2, 'cpu_temperature': 5, 'ram': 3, 'gpu': 5,
           'network': 5, 'vpn': 5, 'power': 5, 'processes': 3,
           'shares': 15, 'arch': 60, 'media': 5, 'system_info': 300,
           'packages': 1800, 'updates': 1800, 'calendar': 60, 'session': 5,
           'health': 30, 'weather': 900, 'feeds': 600, 'containers': 15,
           'nas': 30, 'remote': 30}
SOURCES = {
    'arch': ('arch', 'packages', 'updates'), 'system': ('system_info',),
    'performance': ('cpu', 'cpu_temperature', 'ram', 'gpu'),
    'processes': ('processes',), 'connectivity': ('network', 'vpn'),
    'player': ('media',), 'shares': ('shares',), 'session': ('session',),
    'power': ('power',), 'calendar': ('calendar',),
    **{key: (key,) for key in ('weather', 'feeds', 'containers', 'nas', 'remote')},
}
SOURCE_TITLES = {'cpu': 'CPU usage', 'cpu_temperature': 'CPU temperature', 'ram': 'RAM',
                 'gpu': 'GPU usage / temperature', 'network': 'Network / traffic',
                 'vpn': 'VPNs', 'arch': 'Kernel / uptime', 'packages': 'Package count',
                 'updates': 'Available updates', 'media': 'Player metadata',
                 'system_info': 'Specifications', 'calendar': 'Agenda', 'health': 'Health checks'}
DEFAULT_APPEARANCE = {'scale': 1.0, 'opacity': .70, 'font_size': 14, 'spacing': 10, 'graphs': True,
                      'history_minutes': 15, 'snap': True, 'grid_size': 12,
                      'recent_text_size': 14, 'recent_icon_size': 40}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_json(path, fallback=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return deepcopy(fallback)


def defaults():
    profiles = {}
    for name in ('Daily', 'Monitoring', 'Minimal'):
        visible = BASE_CARDS.copy()
        if name == 'Minimal':
            visible = ['arch', 'performance', 'calendar', 'player', 'power']
        profiles[name] = {'visible': visible, 'layouts': {}, 'refresh': deepcopy(REFRESH),
                          'appearance': deepcopy(DEFAULT_APPEARANCE)}
    return {'version': 1, 'active_profile': 'Daily', 'profiles': profiles,
            'integrations': {'weather': {'latitude': '', 'longitude': '', 'location': ''},
                             'feeds': {'urls': ''}, 'nas': {'url': '', 'token': ''},
                             'remote': {'url': '', 'token': ''}},
            'expected_shares': [], 'expected_vpns': [], 'notes': '', 'tasks': []}


def number(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def validate(data):
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('Unsupported dashboard settings version')
    profiles = data.get('profiles')
    if not isinstance(profiles, dict) or not 1 <= len(profiles) <= 30:
        raise ValueError('Keep between 1 and 30 profiles')
    if data.get('active_profile') not in profiles:
        raise ValueError('Choose an existing profile')
    for name, profile in profiles.items():
        if not isinstance(name, str) or not name.strip() or len(name) > 40 or any(ord(c) < 32 for c in name):
            raise ValueError('Profile names must contain 1–40 printable characters')
        visible = profile.get('visible')
        if not isinstance(visible, list) or len(visible) != len(set(visible)) or any(c not in CARDS for c in visible):
            raise ValueError('Unknown or repeated card')
        for source, seconds in profile.get('refresh', {}).items():
            if source not in REFRESH or type(seconds) is not int or not 1 <= seconds <= 86400:
                raise ValueError('Refresh intervals must be whole seconds from 1 to 86400')
        appearance = profile.get('appearance', {})
        appearance.setdefault('scale', 1.0)
        appearance.setdefault('recent_text_size', appearance.get('font_size', 14))
        appearance.setdefault('recent_icon_size', DEFAULT_APPEARANCE['recent_icon_size'])
        for key, low, high in [('scale', .5, 2), ('opacity', .15, 1), ('font_size', 9, 24), ('spacing', 4, 24), ('grid_size', 4, 40),
                               ('recent_text_size', 9, 24), ('recent_icon_size', 16, 80)]:
            if not number(appearance.get(key), low, high):
                raise ValueError('Invalid appearance setting: ' + key)
        if appearance.get('history_minutes') not in (5, 15, 30, 60):
            raise ValueError('History range must be 5, 15, 30 or 60 minutes')
        if any(type(appearance.get(key)) is not bool for key in ('graphs', 'snap')):
            raise ValueError('Graph and snap settings must be enabled or disabled')
        layouts = profile.get('layouts', {})
        if not isinstance(layouts, dict):
            raise ValueError('Invalid saved monitor layouts')
        for display, layout in layouts.items():
            if not isinstance(display, str) or not isinstance(layout, dict):
                raise ValueError('Invalid display layout')
            for card, rect in layout.items():
                if card not in CARDS or not valid_rect(rect):
                    raise ValueError('Invalid card position or size')
        sizes=profile.get('layout_sizes',{})
        if not isinstance(sizes,dict):raise ValueError('Invalid layout canvas sizes')
        for display,size in sizes.items():
            if not isinstance(display,str) or not isinstance(size,(list,tuple)) or len(size)!=2 or not all(number(v,1,1000000) for v in size):raise ValueError('Invalid layout canvas size')
    integrations = data.get('integrations', {})
    for key in ('nas', 'remote'):
        cfg = integrations.get(key, {})
        url = cfg.get('url', '')
        if not isinstance(url, str) or (url and not url.startswith(('http://', 'https://'))):
            raise ValueError('Endpoint must start with http:// or https://')
        if not isinstance(cfg.get('token', ''), str) or len(cfg.get('token', '')) > 4096:
            raise ValueError('Invalid endpoint token')
    weather = integrations.get('weather', {})
    if not isinstance(weather.get('location',''),str) or len(weather.get('location',''))>300:
        raise ValueError('Invalid weather location')
    for key, low, high in [('latitude', -90, 90), ('longitude', -180, 180)]:
        value = weather.get(key, '')
        if value != '':
            try:
                if not number(float(value), low, high): raise ValueError()
            except (TypeError, ValueError):
                raise ValueError('Invalid weather ' + key) from None
    urls = integrations.get('feeds', {}).get('urls', '')
    if not isinstance(urls, str) or any(not url.startswith(('http://', 'https://')) for url in urls.splitlines() if url.strip()):
        raise ValueError('Use one http:// or https:// feed URL per line')
    if len(urls.splitlines()) > 20:
        raise ValueError('Use at most 20 feeds')
    if not isinstance(data.get('notes', ''), str) or len(data.get('notes', '')) > 100000:
        raise ValueError('Note is too long')
    tasks = data.get('tasks', [])
    if not isinstance(tasks, list) or len(tasks) > 500 or any(not isinstance(t, dict) or not isinstance(t.get('text'), str) or not 1 <= len(t['text']) <= 1000 or type(t.get('done')) is not bool for t in tasks):
        raise ValueError('Invalid task list')
    if not isinstance(data.get('expected_vpns', []), list) or any(v not in ('tailscale', 'proton') for v in data.get('expected_vpns', [])):
        raise ValueError('Unknown monitored VPN')
    expected = data.get('expected_shares', [])
    if not isinstance(expected, list) or any(not isinstance(p, str) or not p.startswith('/') for p in expected):
        raise ValueError('Expected shares must be absolute mount paths')
    return data


class Settings:
    def __init__(self, root):
        self.path = Path(root) / 'dashboard.json'
        raw = read_json(self.path)
        self.error = ''
        try:
            self.data = validate(raw) if raw is not None else defaults()
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            self.error = str(exc)
            self.data = defaults()
            # Preserve an invalid configuration for recovery before a later save.
            if self.path.exists():
                recovery = self.path.with_name('dashboard.invalid-' + str(time.time_ns()) + '.json')
                recovery.write_bytes(self.path.read_bytes())
                recovery.chmod(0o600)

    def save(self, data=None):
        value = deepcopy(data if data is not None else self.data)
        validate(value)
        atomic_json(self.path, value)
        self.data = value

    @property
    def profile(self):
        return self.data['profiles'][self.data['active_profile']]


class Transaction:
    """Undo/redo across all changes in an editing session; save is explicit."""
    def __init__(self, data):
        self.original = deepcopy(data)
        self.data = deepcopy(data)
        self.undo_stack, self.redo_stack = [], []

    def checkpoint(self):
        self.undo_stack.append(deepcopy(self.data))
        self.undo_stack = self.undo_stack[-100:]
        self.redo_stack.clear()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(deepcopy(self.data))
            self.data = self.undo_stack.pop()
            return True
        return False

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(deepcopy(self.data))
            self.data = self.redo_stack.pop()
            return True
        return False


def valid_rect(rect):
    return (isinstance(rect, (list, tuple)) and len(rect) == 4
            and all(number(n, 0, 1) for n in rect) and rect[2] > 0 and rect[3] > 0
            and rect[0] + rect[2] <= 1.000001 and rect[1] + rect[3] <= 1.000001)


def overlaps(a, b, tolerance=.0005):
    return (a[0] < b[0] + b[2] - tolerance and a[0] + a[2] > b[0] + tolerance
            and a[1] < b[1] + b[3] - tolerance and a[1] + a[3] > b[1] + tolerance)


def valid_move(card, rect, layout):
    return valid_rect(rect) and all(not overlaps(rect, other) for key, other in layout.items() if key != card)


def swap_target(card, proposed, layout):
    """Dropping onto one occupied slot swaps complete slots without overlaps."""
    cx, cy = proposed[0]+proposed[2]/2, proposed[1]+proposed[3]/2
    target = next((key for key,rect in layout.items() if key != card and rect[0] <= cx <= rect[0]+rect[2] and rect[1] <= cy <= rect[1]+rect[3]), None)
    if target is None: return None
    result = deepcopy(layout)
    result[card], result[target] = result[target], result[card]
    return target if all(valid_move(key,rect,result) for key,rect in result.items()) else None


def spaced(a,b,width,height,gap):
    """Whether two rectangles leave at least the configured physical gap."""
    gx,gy=gap/max(1,width),gap/max(1,height)
    return (a[0]+a[2]+gx<=b[0]+.5/max(1,width) or b[0]+b[2]+gx<=a[0]+.5/max(1,width)
            or a[1]+a[3]+gy<=b[1]+.5/max(1,height) or b[1]+b[3]+gy<=a[1]+.5/max(1,height))


def insert_card(card,layout,width,height,gap=10,minimums=None):
    """Use free space or share height across a column without growing the canvas."""
    result=deepcopy(layout)
    if card in result:return result,height
    minimums=minimums or {}
    minw,minh=min(220,width),min(max(100,minimums.get(card,100)),height)
    preferredw,preferredh=min(360,width),max(minh,min(280,height))
    pixels=[[r[0]*width,r[1]*height,r[2]*width,r[3]*height] for r in result.values()]
    xs=sorted({0.0,*[r[0]+r[2]+gap for r in pixels]})
    ys=sorted({0.0,*[r[1]+r[3]+gap for r in pixels]})
    for y in ys:
        for x in xs:
            widths={min(preferredw,width-x),minw}
            heights={min(preferredh,height-y),minh}
            widths.update(min(preferredw,r[0]-gap-x) for r in pixels if r[0]>x)
            heights.update(min(preferredh,r[1]-gap-y) for r in pixels if r[1]>y)
            candidates=[]
            for w in widths:
                for h in heights:
                    rect=[x/width,y/height,w/width,h/height]
                    if w>=minw and h>=minh and valid_rect(rect) and all(spaced(rect,r,width,height,gap) for r in result.values()):candidates.append(rect)
            if candidates:
                result[card]=max(candidates,key=lambda r:r[2]*r[3]);return result,height
    # Distribute the reduction equally across a suitable column,
    # respecting each card's minimum and keeping its horizontal position.
    columns={}
    for key,rect in result.items():columns.setdefault((round(rect[0]*width),round(rect[2]*width)),[]).append(key)
    options=[]
    for (x,w),keys in columns.items():
        if w<minw:continue
        keys.sort(key=lambda k:result[k][1]);top=result[keys[0]][1]*height
        heights=[result[k][3]*height for k in keys]
        floors=[min(h,max(100,minimums.get(key,100))) for key,h in zip(keys,heights)]
        room=height-top-gap*len(keys)
        if room<sum(floors)+minh:continue
        newh=min(preferredh,max(minh,room/(len(keys)+1)))
        reductions=[0.0]*len(keys);remaining=max(0,sum(heights)+newh-room)
        for _ in keys:
            active=[i for i,h in enumerate(heights) if h-reductions[i]>floors[i]+1e-7]
            if not active or remaining<1e-7:break
            amount=min(remaining/len(active),min(heights[i]-reductions[i]-floors[i] for i in active))
            for i in active:reductions[i]+=amount
            remaining-=amount*len(active)
        if remaining>1e-5:continue
        plan=deepcopy(result);y=top
        for i,key in enumerate(keys):
            plan[key]=[result[key][0],y/height,result[key][2],(heights[i]-reductions[i])/height]
            y+=heights[i]-reductions[i]+gap
        plan[card]=[result[keys[0]][0],y/height,result[keys[0]][2],newh/height]
        if all(valid_move(k,r,plan) for k,r in plan.items()) and valid_rect(plan[card]):options.append((sum(reductions),plan))
    if options:return min(options,key=lambda item:item[0])[1],height
    return None,height


def fit_layout_height(layout,width,oldheight,height,gap=10,minimums=None):
    """Keep saved pixel geometry when it fits; otherwise share height reductions."""
    if not layout:return {},height
    minimums=minimums or {}
    pixels={key:[r[0]*width,r[1]*oldheight,r[2]*width,r[3]*oldheight] for key,r in layout.items()}
    order=sorted(pixels,key=lambda k:pixels[k][1])
    floors={k:max(100,minimums.get(k,100)) for k in pixels}
    # Extra room must not move card origins while keeping their heights fixed:
    # that stretches each gap by a different amount. Keep the saved pixel
    # geometry whenever it still fits, including layouts saved by older editors.
    unchanged=deepcopy(layout) if abs(oldheight-height)<.01 else {
        key:[x,y*oldheight/height,w,h*oldheight/height] for key,(x,y,w,h) in layout.items()}
    if all(r[3]*height>=floors[k]-.01 and valid_move(k,r,unchanged) for k,r in unchanged.items()) and all(spaced(a,b,width,height,gap) for i,a in enumerate(unchanged.values()) for b in list(unchanged.values())[i+1:]):return unchanged,height
    def attempt(scale):
        plan={};bottoms={}
        for key in order:
            x,original_y,w,h=pixels[key]
            h=floors[key]+scale*max(0,h-floors[key])
            y=original_y*height/oldheight
            for previous in plan:
                ox,oy,ow,oh=pixels[previous]
                if min(x+w,ox+ow)>max(x,ox) and oy+oh<=original_y+.5:y=max(y,bottoms[previous]+gap)
            if y+h>height+.01:return None
            plan[key]=[x/width,y/height,w/width,h/height];bottoms[key]=y+h
        return plan if all(valid_move(k,r,plan) for k,r in plan.items()) else None
    complete=attempt(1)
    if complete is not None:return complete,height
    best=attempt(0)
    if best is None:return None,height
    low,high=0.0,1.0
    for _ in range(25):
        mid=(low+high)/2;candidate=attempt(mid)
        if candidate is None:high=mid
        else:low=mid;best=candidate
    return best,height


def fill_layout(layout,width,height,gap=10,minimums=None):
    """Fill the canvas at exact spacing, keeping existing rows/columns when possible.

    Interior excess gaps are shared equally between neighboring cells. Space
    after the last cell extends that cell to the right/bottom, leaving earlier
    cards alone. An unsliceable arrangement is packed in spatial reading order.
    """
    if not layout:return {}
    if width<=0 or height<=0 or gap<0 or any(not valid_rect(r) for r in layout.values()):return None
    minimums=minimums or {}
    pixels={k:[r[0]*width,r[1]*height,r[2]*width,r[3]*height] for k,r in layout.items()}
    floors={k:minimums.get(k,(80,100)) for k in layout}

    def lengths(bases,limits,available,shared=0):
        if available<sum(limits)-1e-7:return None
        sizes=[max(base,limit) for base,limit in zip(bases,limits)]
        delta=available-sum(sizes)
        if delta>=0:
            growth=min(shared,delta)
            sizes=[size+growth/len(sizes) for size in sizes]
            sizes[-1]+=delta-growth
        else:
            remaining=-delta
            while remaining>1e-7:
                active=[i for i,size in enumerate(sizes) if size>limits[i]+1e-7]
                if not active:return None
                step=min(remaining/len(active),min(sizes[i]-limits[i] for i in active))
                for i in active:sizes[i]-=step
                remaining-=step*len(active)
        # Absorb roundoff at the outer edge so repeated fitting is stable.
        sizes[-1]+=available-sum(sizes)
        return sizes

    def bounds(keys,axis):
        return min(pixels[k][axis] for k in keys),max(pixels[k][axis]+pixels[k][axis+2] for k in keys)

    def groups(keys,axis):
        result=[];edge=-math.inf
        for key in sorted(keys,key=lambda k:(pixels[k][axis],pixels[k][axis+2],k)):
            start=pixels[key][axis];end=start+pixels[key][axis+2]
            if not result or start>=edge-1e-7:result.append([key])
            else:result[-1].append(key)
            edge=max(edge,end)
        return result

    def tree(keys):
        if len(keys)==1:return {'keys':keys,'minimum':floors[keys[0]]}
        for axis in (0,1):
            parts=groups(keys,axis)
            if len(parts)==1:continue
            children=[tree(part) for part in parts]
            if any(child is None for child in children):return None
            minimum=[0,0]
            minimum[axis]=sum(child['minimum'][axis] for child in children)+gap*(len(children)-1)
            minimum[1-axis]=max(child['minimum'][1-axis] for child in children)
            return {'keys':keys,'axis':axis,'children':children,'minimum':minimum}
        return None

    def place(node,rect,result):
        if rect[2]<node['minimum'][0]-1e-7 or rect[3]<node['minimum'][1]-1e-7:return False
        if 'children' not in node:
            result[node['keys'][0]]=rect
            return True
        axis=node['axis'];children=node['children']
        spans=[bounds(child['keys'],axis) for child in children]
        shared=sum(max(0,after[0]-before[1]-gap) for before,after in zip(spans,spans[1:]))
        sizes=lengths([end-start for start,end in spans],[child['minimum'][axis] for child in children],
                      rect[axis+2]-gap*(len(children)-1),shared)
        if sizes is None:return False
        offset=rect[axis]
        for child,size in zip(children,sizes):
            cell=list(rect);cell[axis]=offset;cell[axis+2]=size
            if not place(child,cell,result):return False
            offset+=size+gap
        return True

    def packed():
        # Some staggered mosaics have no straight separator. Choose a feasible
        # row packing with the least movement, rather than leaving empty holes.
        keys=sorted(pixels,key=lambda k:(pixels[k][1],pixels[k][0],k))
        options=[]
        for columns in range(1,len(keys)+1):
            rows=[keys[i:i+columns] for i in range(0,len(keys),columns)]
            available=height-gap*(len(rows)-1)
            heights=lengths([max(pixels[k][3] for k in row) for row in rows],
                            [max(floors[k][1] for k in row) for row in rows],available,shared=max(0,available))
            if heights is None:continue
            result={};y=0
            for row,h in zip(rows,heights):
                available=width-gap*(len(row)-1)
                widths=lengths([pixels[k][2] for k in row],[floors[k][0] for k in row],available,shared=max(0,available))
                if widths is None:break
                x=0
                for key,w in zip(row,widths):result[key]=[x,y,w,h];x+=w+gap
                y+=h+gap
            if len(result)!=len(keys):continue
            cost=sum(((r[0]+r[2]/2-pixels[k][0]-pixels[k][2]/2)/width)**2
                     +((r[1]+r[3]/2-pixels[k][1]-pixels[k][3]/2)/height)**2 for k,r in result.items())
            options.append((cost,result))
        return min(options,key=lambda item:item[0])[1] if options else None

    root=tree(list(layout));result={}
    if root is None or not place(root,[0,0,width,height],result):result=packed()
    if result is None:return None
    fitted={key:[x/width,y/height,w/width,h/height] for key,(x,y,w,h) in result.items()}
    if not all(valid_move(k,r,fitted) for k,r in fitted.items()):return None
    if not all(spaced(a,b,width,height,gap) for i,a in enumerate(fitted.values()) for b in list(fitted.values())[i+1:]):return None
    if all(abs(a-b)<1e-9 for k,r in fitted.items() for a,b in zip(r,layout[k])):return deepcopy(layout)
    return fitted


def central_drop_target(card,proposed,layout,point=None):
    """A swap requires a deliberate drop inside the target's central 65%."""
    cx,cy=point if point is not None else (proposed[0]+proposed[2]/2,proposed[1]+proposed[3]/2)
    for key,(x,y,w,h) in layout.items():
        if key!=card and overlaps(proposed,layout[key]) and x+.175*w<=cx<=x+.825*w and y+.175*h<=cy<=y+.825*h:return key
    return None


def measure_gaps(card,rect,layout,width,height,maximum=120):
    """Nearest visible horizontal/vertical gap in each direction, in pixels."""
    x,y,w,h=[rect[0]*width,rect[1]*height,rect[2]*width,rect[3]*height]
    nearest={}
    for key,other in layout.items():
        if key==card:continue
        ox,oy,ow,oh=other[0]*width,other[1]*height,other[2]*width,other[3]*height
        choices=[]
        if min(y+h,oy+oh)>max(y,oy):
            middle=(max(y,oy)+min(y+h,oy+oh))/2
            if ox>=x+w:choices.append(('e',x+w,middle,ox,middle,ox-x-w))
            if x>=ox+ow:choices.append(('w',ox+ow,middle,x,middle,x-ox-ow))
        if min(x+w,ox+ow)>max(x,ox):
            middle=(max(x,ox)+min(x+w,ox+ow))/2
            if oy>=y+h:choices.append(('s',middle,y+h,middle,oy,oy-y-h))
            if y>=oy+oh:choices.append(('n',middle,oy+oh,middle,y,y-oy-oh))
        for direction,*values in choices:
            if values[-1]<=maximum and (direction not in nearest or values[-1]<nearest[direction][-1]):nearest[direction]=values
    return list(nearest.values())


def resolve_layout(card, proposed, layout, edge, width, height, gap=10, allow_swap=True, drop_point=None):
    """Plan a whole drag without mutating saved layout; preserve usable neighbours."""
    if card not in layout or not valid_rect(proposed): return None
    original=layout[card]
    def valid(plan):
        return all(valid_move(key,rect,plan) for key,rect in plan.items())
    if not edge:
        result=deepcopy(layout);result[card]=list(proposed)
        if valid(result) and all(spaced(proposed,r,width,height,gap) for key,r in layout.items() if key!=card):return result
        if not allow_swap:return None
        target=central_drop_target(card,proposed,layout,drop_point)
        if target is None:return None
        result=deepcopy(layout);result[card],result[target]=list(layout[target]),list(original)
        # Exchanging existing slots preserves their geometry and existing gaps.
        return result if valid(result) else None
    gx,gy=gap/max(1,width),gap/max(1,height)
    def attempt(rect):
        result=deepcopy(layout);result[card]=list(rect)
        for key,other in layout.items():
            if key==card or spaced(rect,other,width,height,gap):continue
            x,y,w,h=other; right,bottom=x+w,y+h
            candidates=[]
            if 'e' in edge and x>=original[0]+original[2]-.001:
                left=rect[0]+rect[2]+gx;candidates.append([left,y,right-left,h])
            if 'w' in edge and right<=original[0]+.001:
                candidates.append([x,y,rect[0]-gx-x,h])
            if 's' in edge and y>=original[1]+original[3]-.001:
                top=rect[1]+rect[3]+gy;candidates.append([x,top,w,bottom-top])
            if 'n' in edge and bottom<=original[1]+.001:
                candidates.append([x,y,w,rect[1]-gy-y])
            candidates=[r for r in candidates if valid_rect(r) and r[2]>=min(180/max(1,width),w)-1e-8 and r[3]>=min(100/max(1,height),h)-1e-8]
            if not candidates:return None
            result[key]=max(candidates,key=lambda r:r[2]*r[3])
        return result if valid(result) and all(spaced(rect,r,width,height,gap) for key,r in result.items() if key!=card) else None
    result=attempt(proposed)
    if result is not None:return result
    # Stop the dragged edge at the neighbours' usable minimum instead of rejecting it.
    lower,upper=0.0,1.0;best=attempt(original)
    if best is None:return None
    for _ in range(24):
        middle=(lower+upper)/2
        rect=[a+(b-a)*middle for a,b in zip(original,proposed)]
        candidate=attempt(rect)
        if candidate is None:upper=middle
        else:lower=middle;best=candidate
    return best


def transform(rect, dx, dy, edge, width, height, grid=0, others=(), gap=0):
    """Move/resize in pixels, snap edges, return a bounded normalised rectangle."""
    x, y, w, h = [rect[0]*width, rect[1]*height, rect[2]*width, rect[3]*height]
    left, top, right, bottom = x, y, x+w, y+h
    if not edge:
        left += dx; right += dx; top += dy; bottom += dy
    else:
        if 'w' in edge: left += dx
        if 'e' in edge: right += dx
        if 'n' in edge: top += dy
        if 's' in edge: bottom += dy
    guides = []
    if grid:
        # Snap only nearby, spatially relevant edges. Do not round free motion to a grid.
        tolerance=grid/2
        lefts,rights,tops,bottoms=[0],[width],[0],[height]
        for other in others:
            ox,oy,ow,oh=other[0]*width,other[1]*height,other[2]*width,other[3]*height
            vertical=min(bottom,oy+oh)-max(top,oy)
            horizontal=min(right,ox+ow)-max(left,ox)
            if vertical>0:
                lefts.append(ox+ow+gap);rights.append(ox-gap)
            elif -vertical<=gap+tolerance:
                lefts.append(ox);rights.append(ox+ow)
            if horizontal>0:
                tops.append(oy+oh+gap);bottoms.append(oy-gap)
            elif -horizontal<=gap+tolerance:
                tops.append(oy);bottoms.append(oy+oh)
        def adjust(pairs):
            options=[(abs(anchor-value),anchor-value,anchor) for value,anchors in pairs for anchor in anchors]
            distance,delta,anchor=min(options)
            return (delta,anchor) if distance<=tolerance else (0,None)
        if not edge:
            sx,gx=adjust(((left,lefts),(right,rights)));sy,gy=adjust(((top,tops),(bottom,bottoms)))
            left+=sx;right+=sx;top+=sy;bottom+=sy
        else:
            sx,gx=adjust(((left,lefts),)) if 'w' in edge else adjust(((right,rights),)) if 'e' in edge else (0,None)
            sy,gy=adjust(((top,tops),)) if 'n' in edge else adjust(((bottom,bottoms),)) if 's' in edge else (0,None)
            if 'w' in edge:left+=sx
            if 'e' in edge:right+=sx
            if 'n' in edge:top+=sy
            if 's' in edge:bottom+=sy
        if gx is not None:guides.append(('x',gx))
        if gy is not None:guides.append(('y',gy))
    minw, minh = min(180, width), min(100, height)
    if not edge:
        left = min(max(0, left), max(0, width-w)); top = min(max(0, top), max(0, height-h))
        right, bottom = left+w, top+h
    else:
        if 'w' in edge: left = max(0, min(left, right-minw))
        if 'e' in edge: right = min(width, max(right, left+minw))
        if 'n' in edge: top = max(0, min(top, bottom-minh))
        if 's' in edge: bottom = min(height, max(bottom, top+minh))
    return [left/width, top/height, (right-left)/width, (bottom-top)/height], guides


def default_layout(visible, width, height, gap=10, preset='Daily'):
    """Three balanced columns or a narrow-screen list; all cards fit the canvas."""
    if not visible: return {}
    columns = 3 if width >= 850 else 2 if width >= 550 else 1
    groups = [['arch','system','connectivity','session','power'],
              ['performance','processes','shares'], ['calendar','player']]
    optional = [c for c in visible if c not in BASE_CARDS]
    if columns < 3:
        groups = [visible[i::columns] for i in range(columns)]
    else:
        groups = [[c for c in group if c in visible] for group in groups]
        for card in optional:
            groups[min(range(3), key=lambda i: len(groups[i]))].append(card)
    ratios = [.30, .40, .30] if columns == 3 else [1/columns]*columns
    result, x = {}, 0
    weights = {'arch': 1.1, 'system': 1.5, 'connectivity': 1.8, 'session': 1.6,
               'power': 2.0, 'performance': 1.6, 'processes': 3.5, 'shares': 2.2,
               'calendar': 3, 'player': 2}
    if preset == 'Monitoring':
        weights.update(performance=3, processes=3, shares=2)
    for group, ratio in zip(groups, ratios):
        cw = (width-(columns-1)*gap)*ratio
        if group:
            room = height-(len(group)-1)*gap
            total = sum(weights.get(c, 1.6) for c in group)
            y = 0
            for card in group:
                ch = room*weights.get(card, 1.6)/total
                result[card] = [x/width, y/height, cw/width, ch/height]
                y += ch+gap
        x += cw+gap
    return result


class History:
    """Local, bounded one-hour history; timestamps are wall-clock seconds."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.path.chmod(0o600)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS samples (metric TEXT, time INTEGER, value REAL, PRIMARY KEY(metric,time))')
        self.db.execute('CREATE INDEX IF NOT EXISTS samples_time ON samples(time)')
        self.last_prune = 0

    def add(self, values, now=None):
        now = int(time.time() if now is None else now)
        for metric, value in values.items():
            if number(value, -1e15, 1e15):
                self.db.execute('INSERT OR REPLACE INTO samples VALUES (?,?,?)', (metric, now, value))
        if now-self.last_prune >= 60:
            self.db.execute('DELETE FROM samples WHERE time < ?', (now-3600,))
            self.last_prune = now
        self.db.commit()

    def series(self, metric, minutes=15, now=None, limit=240):
        now = time.time() if now is None else now
        rows = self.db.execute('SELECT time,value FROM samples WHERE metric=? AND time>=? ORDER BY time', (metric, now-minutes*60)).fetchall()
        step = max(1, math.ceil(len(rows)/limit))
        return [(rows[i][0], sum(v for _,v in rows[i:i+step])/len(rows[i:i+step])) for i in range(0,len(rows),step)]

    def close(self):
        self.db.close()
