#!/usr/bin/env python3
"""PoeDash's editable GTK/Wayland desktop surface."""
import argparse
import calendar
from copy import deepcopy
import datetime
import fcntl
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import threading
import time

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, Gdk, GLib, GLibUnix, GdkPixbuf, Pango, GtkLayerShell

from dashboard_model import (CARDS, BASE_CARDS, REFRESH, SOURCES, SOURCE_TITLES,
    DEFAULT_APPEARANCE, Settings, Transaction, History, atomic_json, read_json,
    default_layout, valid_move, swap_target, transform, validate)
from dashboard_collect import Engine, health_issues

ROOT = Path(__file__).resolve().parent.parent


def box(vertical=True, spacing=6):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL, spacing=spacing)


def label(text='', style='', wrap=False):
    widget = Gtk.Label(label=str(text), xalign=0)
    widget.set_selectable(False)
    widget.set_width_chars(1)
    widget.set_line_wrap(wrap)
    widget.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if not wrap: widget.set_ellipsize(Pango.EllipsizeMode.END)
    if style: widget.get_style_context().add_class(style)
    return widget


def button(text, callback, tip=None):
    widget = Gtk.Button(label=text)
    widget.connect('clicked', lambda *_: callback())
    if tip: widget.set_tooltip_text(tip)
    return widget


def reveal(widget):
    """Show an intentionally hidden subtree, including its container."""
    widget.set_no_show_all(False)
    widget.show_all()
    widget.set_no_show_all(True)


def clear(widget):
    for child in widget.get_children(): widget.remove(child)


def row(parent, name, value):
    line = box(False, 12)
    key, val = label(name, 'muted'), label(value)
    val.set_xalign(1)
    val.set_selectable(True)
    val.set_tooltip_text(str(value))
    line.pack_start(key, True, True, 0)
    line.pack_end(val, True, True, 0)
    parent.pack_start(line, False, False, 0)
    return val


def scroll(child):
    widget = Gtk.ScrolledWindow()
    widget.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    widget.set_min_content_width(0)
    widget.set_min_content_height(0)
    widget.add(child)
    return widget


def rate(value):
    try: number = float(value)
    except (TypeError, ValueError): return '—'
    for unit in ('B/s', 'KiB/s', 'MiB/s', 'GiB/s'):
        if abs(number) < 1024: return f'{number:.1f} {unit}'
        number /= 1024
    return f'{number:.1f} TiB/s'


class Graph(Gtk.DrawingArea):
    def __init__(self, app, metrics, maximum=None):
        super().__init__()
        self.app, self.metrics, self.maximum = app, metrics, maximum
        self.set_size_request(-1, round(65*app.profile['appearance'].get('scale',1)))
        self.connect('draw', self.draw_graph)
        self.set_tooltip_text('Local history · ' + ', '.join(name for _, name in metrics))

    def draw_graph(self, widget, cr):
        width, height = self.get_allocated_width(), self.get_allocated_height()
        cr.set_source_rgba(.65,.62,.72,.15)
        cr.set_line_width(1)
        for y in (height*.25, height*.5, height*.75):
            cr.move_to(0,y); cr.line_to(width,y)
        cr.stroke()
        now = time.time()
        minutes = self.app.profile['appearance']['history_minutes']
        colors = [(.80,.69,.98),(.45,.82,.74),(.95,.69,.45)]
        for index, (metric, _) in enumerate(self.metrics):
            points = self.app.history.series(metric, minutes, now)
            if not points: continue
            maximum = self.maximum or max(1, max(v for _,v in points)*1.15)
            cr.set_source_rgba(*colors[index % len(colors)], .95)
            cr.set_line_width(1.8)
            previous = None
            dots=[]
            for stamp, value in points:
                x = max(0, min(width, (stamp-(now-minutes*60))/(minutes*60)*width))
                y = height-4-max(0,min(1,value/maximum))*(height-8)
                # Leave a gap when collection paused instead of implying continuity.
                if previous is None or stamp-previous > 90: cr.move_to(x,y)
                else: cr.line_to(x,y)
                previous = stamp; dots.append((x,y))
            cr.stroke()
            for x,y in dots:
                cr.arc(x,y,1.2,0,2*math.pi); cr.fill()
        return False


class Card(Gtk.EventBox):
    def __init__(self, app, key):
        super().__init__()
        self.app, self.key = app, key
        self.get_style_context().add_class('card')
        self.overlay = Gtk.Overlay()
        self.add(self.overlay)
        self.content = box(True, round(7*app.profile['appearance'].get('scale',1)))
        self.content.set_border_width(round(12*app.profile['appearance'].get('scale',1)))
        self.overlay.add(self.content)
        heading = box(False, 6)
        self.title = label(CARDS[key][0].upper(), 'heading')
        heading.pack_start(self.title, True, True, 0)
        self.refresh_button = button('↻', lambda: app.refresh_card(key), 'Refresh this card now')
        heading.pack_end(self.refresh_button, False, False, 0)
        self.menu_button=button('⋯', lambda: app.card_menu(self), 'Card details and settings')
        heading.pack_end(self.menu_button, False, False, 0)
        self.content.pack_start(heading, False, False, 0)
        self.body = box(True, round((4 if key in ('system','connectivity','power') else 7)*app.profile['appearance'].get('scale',1)))
        self.body_scroll = scroll(self.body)
        self.content.pack_start(self.body_scroll, True, True, 0)
        self.freshness = label('Collecting…', 'freshness')
        self.content.pack_end(self.freshness, False, False, 0)
        self.cover = Gtk.EventBox()
        self.cover.set_visible_window(True)
        self.cover.set_above_child(True)
        self.cover.get_style_context().add_class('edit-cover')
        self.cover.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.cover.connect('button-press-event', self.press)
        self.cover.connect('button-release-event', self.release)
        self.cover.connect('motion-notify-event', self.motion)
        self.cover.connect('leave-notify-event', self.leave)
        self.handles = Gtk.DrawingArea()
        self.handles.connect('draw', self.draw_handles)
        self.cover.add(self.handles)
        self.overlay.add_overlay(self.cover)
        self.overlay.set_overlay_pass_through(self.cover,False)
        self.cover.set_no_show_all(True)
        self.drag = None
        self.render()

    def edge(self, x, y):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        return ('n' if y < 14 else 's' if y > h-14 else '') + ('w' if x < 14 else 'e' if x > w-14 else '')

    def set_editing(self, editing):
        if editing: reveal(self.cover)
        else: self.cover.hide()
        self.content.set_sensitive(not editing)
        self.get_style_context().remove_class('selected')
        self.queue_draw()

    def press(self, widget, event):
        if event.button != 1: return False
        self.app.selected = self.key
        self.app.status.set_text('Drag to move · edges/corners resize · invalid overlaps return to their previous position')
        self.drag = (event.x_root, event.y_root, deepcopy(self.app.layout[self.key]), self.edge(event.x,event.y))
        self.cover.grab_add()
        self.queue_draw()
        return True

    def motion(self, widget, event):
        if not self.app.editing: return False
        if self.drag:
            x, y, original, edge = self.drag
            width, height = self.app.canvas_size
            appearance = self.app.profile['appearance']
            others = [r for key,r in self.app.layout.items() if key != self.key]
            rect, guides = transform(original, event.x_root-x, event.y_root-y, edge, width, height,
                                     appearance['grid_size'] if appearance['snap'] else 0, others)
            self.app.preview = (self.key, rect, valid_move(self.key,rect,self.app.layout))
            self.app.guides = guides
            if not self.app.preview[2] and not edge:
                target=swap_target(self.key,rect,self.app.layout)
                if target: self.app.status.set_text('Release to swap with '+CARDS[target][0])
            self.app.place_card(self.key, rect)
            self.queue_draw()
            self.app.guide_layer.queue_draw()
        else:
            edge = self.edge(event.x,event.y)
            cursor = {'n':'n-resize','s':'s-resize','e':'e-resize','w':'w-resize',
                      'ne':'ne-resize','nw':'nw-resize','se':'se-resize','sw':'sw-resize'}.get(edge,'move')
            if widget.get_window(): widget.get_window().set_cursor(Gdk.Cursor.new_from_name(Gdk.Display.get_default(),cursor))
        return True

    def release(self, widget, event):
        if not self.drag: return False
        self.cover.grab_remove()
        preview = self.app.preview
        if preview and preview[2]:
            self.app.transaction.checkpoint()
            self.app.layout[self.key] = preview[1]
            self.app.store_layout()
            self.app.status.set_text('Layout changed · Save to keep it, or Cancel to restore')
        else:
            target=swap_target(self.key,preview[1],self.app.layout) if preview and not self.drag[3] else None
            if target:
                self.app.transaction.checkpoint()
                self.app.layout[self.key],self.app.layout[target]=self.app.layout[target],self.app.layout[self.key]
                self.app.store_layout()
                self.app.place_card(self.key,self.app.layout[self.key]); self.app.place_card(target,self.app.layout[target])
                self.app.status.set_text('Swapped cards · Save to keep this layout')
            else:
                self.app.place_card(self.key,self.drag[2])
                self.app.status.set_text('That position overlaps another card; move returned to its previous position')
        self.drag = self.app.preview = None
        self.app.guides = []
        self.app.guide_layer.queue_draw()
        self.queue_draw()
        self.app.update_edit_buttons()
        return True

    def leave(self, *_):
        if not self.drag and self.cover.get_window(): self.cover.get_window().set_cursor(None)
        return False

    def draw_handles(self, widget, cr):
        if not self.app.editing: return False
        w,h = self.get_allocated_width(),self.get_allocated_height()
        valid = self.app.preview[2] if self.app.preview and self.app.preview[0] == self.key else True
        cr.set_source_rgba(*((.77,.66,.98,.95) if valid else (1,.35,.4,.95)))
        cr.set_line_width(2)
        cr.rectangle(2,2,w-4,h-4); cr.stroke()
        for x,y in ((4,4),(w/2,4),(w-4,4),(4,h/2),(w-4,h/2),(4,h-4),(w/2,h-4),(w-4,h-4)):
            cr.rectangle(x-3,y-3,6,6); cr.fill()
        return False

    def value(self, source, default=None):
        sample = self.app.samples.get(source, {})
        result = sample.get('value')
        return default if result is None else result

    def text(self, value, style='', wrap=True):
        item = label(value, style, wrap)
        self.body.pack_start(item,False,False,0)
        return item

    def chart(self, metrics, maximum=None):
        if self.app.profile['appearance']['graphs']:
            graph = Graph(self.app,metrics,maximum)
            self.body.pack_start(graph,False,False,0)
            self.text(' · '.join(name for _,name in metrics) + f" · {self.app.profile['appearance']['history_minutes']} min", 'freshness', False)

    def render(self):
        # Keep text editing and process filtering stable while readings change.
        if self.key in ('notes','tasks') and self.body.get_children(): return
        if self.key == 'processes' and hasattr(self, 'process_list'):
            self.render_processes(); return
        adjustment = self.body_scroll.get_vadjustment()
        position = adjustment.get_value()
        clear(self.body)
        key = self.key
        if key == 'arch':
            data = self.value('arch',{})
            for name, value in [('Kernel',data.get('kernel','—')),('Uptime',data.get('uptime','—')),
                                ('Packages',self.value('packages','—')),('Updates',self.value('updates','—'))]: row(self.body,name,value)
        elif key == 'system':
            data = self.value('system_info',{})
            for name, field in [('OS','os'),('CPU','cpu'),('GPU','gpu'),('Memory','memory'),('Home disk','disk')]:
                line=box(False,10)
                key_label=label(name.upper(),'freshness'); key_label.set_size_request(76,-1)
                line.pack_start(key_label,False,False,0)
                value=label(data.get(field,'—'),wrap=True); value.set_selectable(True)
                line.pack_start(value,True,True,0); self.body.pack_start(line,False,False,0)
            detail = Gtk.Expander(label='Storage and service health')
            contents = box()
            for disk in self.value('health',{}).get('disks',[]): row(contents,disk['path'],f"{disk['free_gib']} GiB free · {disk['percent']}% used")
            for unit in self.value('health',{}).get('failed',[]): contents.pack_start(label('Failed: '+unit,wrap=True),False,False,0)
            contents.pack_start(button('Open system monitor',lambda: self.app.run('launch.sh','system')),False,False,0)
            detail.add(contents); self.body.pack_start(detail,False,False,0)
        elif key == 'performance':
            gpu = self.value('gpu',{})
            for name,value,display in [('CPU',self.value('cpu',0),str(self.value('cpu','—'))+'%'),
                                       ('GPU',gpu.get('usage',0),gpu.get('label','—')),
                                       ('RAM',self.value('ram',0),str(self.value('ram','—'))+'%')]:
                line = box(False,8); line.pack_start(label(name),False,False,0)
                meter = Gtk.ProgressBar(); meter.set_fraction(max(0,min(1,float(value or 0)/100)))
                line.pack_start(meter,True,True,0); line.pack_end(label(display),False,False,0)
                self.body.pack_start(line,False,False,0)
            temperature = self.value('cpu_temperature','--')
            row(self.body,'CPU temperature', temperature if temperature != '--' else 'Sensor unavailable')
            if gpu.get('temperature') not in (None,'','--'): row(self.body,'GPU temperature',gpu['temperature'])
            system=self.value('system_info',{})
            if system.get('load'): row(self.body,'Load 1 / 5 / 15m',system['load'])
            self.chart([('cpu','CPU %'),('ram','RAM %'),('temperature','CPU °C')],110)
            self.body.pack_start(button('Open btop',lambda: self.app.run('launch.sh','system')),False,False,0)
        elif key == 'processes':
            controls = box(False,6)
            self.process_filter = Gtk.SearchEntry(); self.process_filter.set_placeholder_text('Filter processes…')
            self.process_filter.connect('search-changed',lambda *_: self.render_processes())
            self.process_sort = Gtk.ComboBoxText()
            for name in ('CPU','RAM','Name'): self.process_sort.append_text(name)
            self.process_sort.set_active(0); self.process_sort.connect('changed',lambda *_: self.render_processes())
            controls.pack_start(self.process_filter,True,True,0); controls.pack_end(self.process_sort,False,False,0)
            self.body.pack_start(controls,False,False,0)
            self.process_list = box(True,4); self.body.pack_start(self.process_list,False,False,0)
            self.render_processes()
        elif key == 'connectivity':
            network,vpn = self.value('network',{}),self.value('vpn',{})
            for name,value in [('Network',network.get('state','—')),
                               ('Address',network.get('ip','—')),
                               ('Tailscale',vpn.get('tailscale_state','—')),('Proton VPN',vpn.get('proton_state','—')),
                               ('Download',rate(network.get('rx_bps'))),('Upload',rate(network.get('tx_bps')))]: row(self.body,name,value)
            self.chart([('rx_bps','Download'),('tx_bps','Upload')])
            details=Gtk.Expander(label='Interface, Tailscale IP and routes')
            contents=box(True,4)
            row(contents,'Interface',network.get('interface','—')); row(contents,'Tailscale IP',network.get('tailscale','—'))
            contents.pack_start(button('Addresses and routes',lambda:self.app.run('launch.sh','network')),False,False,0)
            details.add(contents); self.body.pack_start(details,False,False,0)
        elif key == 'shares':
            shares = self.value('shares',[])
            if not shares: self.text('No SMB or NFS shares mounted','muted')
            for share in shares:
                self.text(share['type'],'freshness',False)
                action = button(share['target'],lambda p=share['target']: self.app.open_folder(p),'Open this mounted folder')
                action.get_child().set_ellipsize(Pango.EllipsizeMode.MIDDLE)
                self.body.pack_start(action,False,False,0)
                self.text('← '+share['source'],'muted')
            expected = self.app.data.get('expected_shares',[])
            current = [s['target'] for s in shares]
            for missing in sorted(set(expected)-set(current)): self.text('Disconnected: '+missing,'warning')
            self.body.pack_start(button('Monitor these mounts',lambda: self.app.remember_shares(current),'Report a health issue if any of these paths disconnect'),False,False,0)
        elif key == 'power':
            data = self.value('power',{})
            profile = self.app.power_profile()
            for name,value in [('Source','Battery' if data.get('on_battery') else 'AC / Desktop'),
                               ('Profile',profile.get('active','Unavailable')),
                               ('Selected by',profile.get('mode','Manual'))]: row(self.body,name,value)
            if data.get('present'):
                for name,field in [('Battery','battery'),('Status','status'),('Consumption','watts'),('Remaining','remaining')]: row(self.body,name,data.get(field) or 'Unavailable')
                self.chart([('watts','Consumption W')])
            else: self.text('No system battery detected','muted')
            if profile.get('supported'):
                choices = box(False,4)
                for name in profile.get('available',[]):
                    if isinstance(name,str): choices.pack_start(button(name,lambda n=name: self.app.run('power-control.py','set',n)),True,True,0)
                self.body.pack_start(choices,False,False,0)
        elif key == 'session':
            data = self.value('session',{})
            for name,field in [('Screen off','screen'),('Lock screen','lock'),('Auto suspend','suspend')]:
                line=box(False,5); line.pack_start(label(name),True,True,0)
                for text,delta in [('−',-1),('+',1)]:
                    action=button(text,lambda f=field,d=delta: self.app.idle_action('adjust',f,str(d)))
                    action.set_sensitive(bool(data.get('supported')))
                    if delta < 0: line.pack_start(action,False,False,0)
                    else: plus=action
                line.pack_start(label(str(data.get(field+'_text',data.get(field,'—')))+' min'),False,False,0)
                line.pack_end(plus,False,False,0); self.body.pack_start(line,False,False,0)
            self.text(data.get('message','Detecting idle manager'),'muted')
            apply=button('Apply idle timers',lambda: self.app.idle_action('apply'))
            apply.set_sensitive(bool(data.get('dirty') and data.get('supported')))
            self.body.pack_start(apply,False,False,0)
        elif key == 'calendar':
            now=datetime.datetime.now()
            self.text(now.strftime('%B %Y'),'heading',False)
            month=Gtk.Label(label=calendar.TextCalendar().formatmonth(now.year,now.month)); month.set_xalign(0)
            month.get_style_context().add_class('month')
            self.body.pack_start(month,False,False,0)
            data=self.value('calendar',{})
            self.text('UPCOMING','freshness',False)
            self.text(data.get('status','Reading Thunderbird calendars'),'muted')
            for event in data.get('events',[]):
                self.text(event.get('when',''),'freshness',False)
                self.text(event.get('title','Untitled event'))
            self.body.pack_start(button('Open Thunderbird Calendar',lambda: self.app.run('desktop.py','calendar')),False,False,0)
        elif key == 'player':
            data=self.value('media',{})
            art=data.get('art','')
            if art and Path(art).is_file():
                try:
                    image=Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(art,round(150*self.app.profile['appearance'].get('scale',1)),round(150*self.app.profile['appearance'].get('scale',1)),True))
                    self.body.pack_start(image,False,False,0)
                except GLib.Error: pass
            self.text(data.get('title','Nothing playing'),'media-title')
            self.text(data.get('artist') or data.get('player',''),'muted')
            self.wave_image=Gtk.Image(); self.body.pack_start(self.wave_image,False,False,0)
            self.update_wave()
            seek=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0,100,1)
            seek.set_draw_value(False); seek.set_value(float(data.get('progress',0)))
            seek.set_sensitive(bool(data.get('available') and data.get('length','0:00') != '0:00'))
            seek.connect('button-release-event',lambda widget,event: self.app.seek(widget.get_value()))
            self.body.pack_start(seek,False,False,0)
            self.text(f"{data.get('position','0:00')} / {data.get('length','0:00')}",'freshness',False)
            controls=box(False,7)
            for text,action in [('⏮','previous'),('⏸' if data.get('status')=='Playing' else '▶','play-pause'),('⏭','next'),('Open','open')]:
                controls.pack_start(button(text,lambda a=action: self.app.run('media-control.sh',a)),True,True,0)
            self.body.pack_start(controls,False,False,0)
        elif key == 'notes':
            self.note=Gtk.TextView(); self.note.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            self.note.get_buffer().set_text(self.app.data.get('notes',''))
            self.note.get_buffer().connect('changed',lambda *_: self.app.schedule_note(self.note.get_buffer()))
            self.body.pack_start(self.note,True,True,0)
        elif key == 'tasks':
            entry=Gtk.Entry(); entry.set_placeholder_text('Add a task and press Enter')
            entry.connect('activate',lambda widget: self.app.add_task(widget))
            self.body.pack_start(entry,False,False,0)
            tasks=self.app.data.get('tasks',[])
            for index,task in enumerate(tasks):
                line=box(False,4); check=Gtk.CheckButton.new_with_label(task['text'])
                check.get_child().set_line_wrap(True); check.get_child().set_max_width_chars(30)
                check.set_active(task['done'])
                check.connect('toggled',lambda widget,i=index: self.app.toggle_task(i,widget.get_active()))
                line.pack_start(check,True,True,0)
                line.pack_end(button('×',lambda i=index: self.app.delete_task(i),'Delete task'),False,False,0)
                self.body.pack_start(line,False,False,0)
            if not tasks: self.text('Your checklist is empty','muted')
        elif key == 'weather':
            data=self.value(key,{})
            if not data.get('configured'): self.configure_hint()
            else:
                current=data.get('current',{})
                self.text(str(current.get('temperature_2m','—'))+' °C','media-title',False)
                for name,field,unit in [('Feels like','apparent_temperature','°C'),('Humidity','relative_humidity_2m','%'),('Wind','wind_speed_10m','km/h')]: row(self.body,name,str(current.get(field,'—'))+' '+unit)
                daily=data.get('daily',{})
                for i,day in enumerate(daily.get('time',[])):
                    row(self.body,day,f"{daily.get('temperature_2m_min',[None]*3)[i]}–{daily.get('temperature_2m_max',[None]*3)[i]} °C")
                self.body.pack_start(button('Weather data: Open-Meteo',lambda: self.app.open_url('https://open-meteo.com/')),False,False,0)
        elif key == 'feeds':
            data=self.value(key,{})
            if not data.get('configured'): self.configure_hint()
            else:
                for item in data.get('items',[]):
                    action=button(item['title'],lambda url=item['url']: self.app.open_url(url))
                    action.get_child().set_line_wrap(True); action.get_child().set_max_width_chars(35)
                    self.body.pack_start(action,False,False,0)
                if data.get('errors'): self.text(f"{data['errors']} feeds unavailable",'warning')
        elif key == 'containers':
            items=self.value(key,[])
            if not items: self.text('No containers. Docker must be installed and accessible to your user.','muted')
            for item in items:
                self.text(item.get('Names','Container'))
                self.text(item.get('Status','Unknown'),'muted')
        elif key in ('nas','remote'):
            data=self.value(key,{})
            if not data.get('configured'): self.configure_hint()
            else:
                for name,value in list(data.get('data',{}).items())[:25]:
                    if isinstance(value,(dict,list)): value=json.dumps(value,ensure_ascii=False)
                    self.text(str(name).replace('_',' ').title(),'freshness',False); self.text(str(value)[:1000])
        self.body.show_all()
        GLib.idle_add(lambda: (adjustment.set_value(min(position,adjustment.get_upper())),False)[1])

    def configure_hint(self):
        self.text('Choose Edit → Cards to configure this card.','muted')
        self.body.pack_start(button('Configure',lambda: self.app.open_settings('Cards')),False,False,0)

    def render_processes(self):
        query=self.process_filter.get_text().lower()
        items=[p for p in self.value('processes',[]) if query in p.get('name','').lower()]
        choice=self.process_sort.get_active_text()
        def numeric(item,field):
            try: return float(str(item.get(field,0)).rstrip('%'))
            except ValueError: return 0
        items.sort(key=(lambda p:p.get('name','').lower()) if choice=='Name' else (lambda p:numeric(p,'memory' if choice=='RAM' else 'cpu')),reverse=choice!='Name')
        clear(self.process_list)
        for process in items:
            text=f"{process.get('name','')}  ·  PID {process.get('pid','')}\nCPU {process.get('cpu','—')}    RAM {process.get('memory','—')}"
            action=button(text,lambda p=deepcopy(process): self.app.process_details(p))
            action.get_child().set_xalign(0); action.get_child().set_ellipsize(Pango.EllipsizeMode.END)
            self.process_list.pack_start(action,False,False,0)
        self.process_list.show_all()

    def update_wave(self):
        if not hasattr(self,'wave_image'): return
        path=self.app.wave.get('path','')
        if path and Path(path).is_file():
            try:
                width=max(80,self.get_allocated_width()-30)
                self.wave_image.set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(path,width,36,False))
            except GLib.Error: pass

    def update_freshness(self):
        sources=SOURCES.get(self.key,())
        samples=[(source,self.app.samples.get(source,{})) for source in sources]
        if not sources:
            message='Saved locally'; self.refresh_button.set_sensitive(False)
        elif self.app.paused: message='Paused on battery · dashboard hidden'
        else:
            errors=[sample.get('error') for _,sample in samples if sample.get('error')]
            updated=[sample.get('updated',0) for _,sample in samples]
            if errors: message=errors[0]
            elif not updated or not min(updated): message='Collecting…'
            else:
                age=max(0,int(time.time()-max(updated)))
                message=f'Updated {age}s ago' if age<60 else f'Updated {age//60}m ago'
                stale=any(time.time()-sample.get('updated',0)>max(15,3*self.app.profile['refresh'].get(source,REFRESH[source])) for source,sample in samples)
                if stale: message+=' · some readings are stale'
        self.freshness.set_text(message)
        self.freshness.set_tooltip_text(message)


class Dashboard:
    def __init__(self, root, preview=False, smoke=False, size=(1440,960)):
        self.root=Path(root)
        self.settings=Settings(root)
        self.transaction=None
        self.editing=False
        self.selected=None
        self.preview=None
        self.guides=[]
        self.samples={}
        self.diagnostic_payload='{}'
        self.cards={}
        self.wave={}
        self.children=[]
        self.closing=False
        self.paused=False
        self.visible=True
        self.preview_window=preview
        self.smoke=smoke
        self.canvas_size=(1200,800)
        self.layout={}
        self.note_timer=None
        self.theme_stamp=None
        self.theme={}
        self.history=History(self.root/'state/history.sqlite3')
        self.window=Gtk.OffscreenWindow() if smoke else Gtk.Window(title='PoeDash')
        self.window.set_app_paintable(True)
        visual=self.window.get_screen().get_rgba_visual()
        if visual: self.window.set_visual(visual)
        self.window.connect('destroy',lambda *_: self.quit())
        self.window.connect('key-press-event',self.key_press)
        self.choose_monitor()
        if not preview and GtkLayerShell.is_supported():
            GtkLayerShell.init_for_window(self.window)
            GtkLayerShell.set_namespace(self.window,'poedash')
            GtkLayerShell.set_layer(self.window,GtkLayerShell.Layer.BOTTOM)
            GtkLayerShell.set_keyboard_mode(self.window,GtkLayerShell.KeyboardMode.ON_DEMAND)
            GtkLayerShell.set_monitor(self.window,self.monitor)
            GtkLayerShell.set_exclusive_zone(self.window,-1)
            for edge in (GtkLayerShell.Edge.TOP,GtkLayerShell.Edge.BOTTOM,GtkLayerShell.Edge.LEFT,GtkLayerShell.Edge.RIGHT):
                GtkLayerShell.set_anchor(self.window,edge,True)
        else:
            self.window.set_default_size(*size)
            if smoke: self.window.set_size_request(*size)
        self.provider=Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(self.window.get_screen(),self.provider,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.overlay=Gtk.Overlay(); self.window.add(self.overlay)
        self.surface=box(True,10); self.surface.set_border_width(16)
        self.surface.get_style_context().add_class('dashboard')
        self.overlay.add(self.surface)
        self.header=box(False,10)
        titlebox=box(True,2)
        self.hostname=label(socket.gethostname(),'hostname'); titlebox.pack_start(self.hostname,False,False,0)
        titlebox.pack_start(label('POEDASH','muted'),False,False,0)
        self.header.pack_start(titlebox,True,True,0)
        self.profile_combo=Gtk.ComboBoxText(); self.profile_combo.connect('changed',self.profile_changed)
        self.header.pack_start(self.profile_combo,False,False,0)
        zoom_controls=box(False,3)
        zoom_controls.pack_start(button('−',lambda:self.change_zoom(-.05),'Zoom out'),False,False,0)
        self.zoom_label=label('100%'); zoom_controls.pack_start(self.zoom_label,False,False,0)
        zoom_controls.pack_start(button('+',lambda:self.change_zoom(.05),'Zoom in'),False,False,0)
        zoom_controls.pack_start(button('↶',lambda:self.change_zoom(reset=True),'Reset dashboard zoom to 100%'),False,False,0)
        self.header.pack_start(zoom_controls,False,False,0)
        self.header.pack_start(button('Packages',lambda: self.run('packages.py','launch')),False,False,0)
        self.edit_button=button('Edit',self.edit_menu)
        self.header.pack_start(self.edit_button,False,False,0)
        self.clock=label('','clock'); self.header.pack_end(self.clock,False,False,0)
        self.surface.pack_start(self.header,False,False,0)
        self.healthbar=box(False,6)
        self.health_label=label('Checking system health…','muted')
        self.healthbar.pack_start(self.health_label,True,True,0)
        self.health_button=button('Details',self.show_health)
        self.healthbar.pack_end(self.health_button,False,False,0)
        self.surface.pack_start(self.healthbar,False,False,0)
        self.toolbar=box(False,6); self.toolbar.set_no_show_all(True)
        for text,callback in [('Save',self.save),('Cancel',self.cancel),('Undo',self.undo),('Redo',self.redo),('Reset layout',self.reset_layout)]:
            control=button(text,callback); self.toolbar.pack_start(control,False,False,0)
            if text=='Undo': self.undo_button=control
            if text=='Redo': self.redo_button=control
        self.snap_check=Gtk.CheckButton.new_with_label('Snap & guides')
        self.snap_check.connect('toggled',self.snap_changed)
        self.toolbar.pack_end(self.snap_check,False,False,0)
        self.surface.pack_start(self.toolbar,False,False,0)
        self.main=box(False,10)
        self.rail_body=box(True,7)
        self.rail=scroll(self.rail_body); self.rail.set_size_request(94,-1)
        self.rail.get_style_context().add_class('rail')
        self.main.pack_start(self.rail,False,False,0)
        self.board=Gtk.Overlay()
        self.fixed=Gtk.Fixed(); self.fixed.set_hexpand(True); self.fixed.set_vexpand(True)
        self.board.add(self.fixed)
        self.guide_layer=Gtk.DrawingArea()
        # A native GdkWindow here intercepts clicks on the cards below it.
        self.guide_layer.set_has_window(False)
        self.guide_layer.connect('draw',self.draw_guides)
        self.board.add_overlay(self.guide_layer); self.board.set_overlay_pass_through(self.guide_layer,True)
        self.board_view=scroll(self.board)
        self.board_view.set_policy(Gtk.PolicyType.AUTOMATIC,Gtk.PolicyType.AUTOMATIC)
        self.board_view.connect('size-allocate',self.allocate)
        self.main.pack_start(self.board_view,True,True,0)
        self.surface.pack_start(self.main,True,True,0)
        self.status=label('','freshness'); self.status.set_no_show_all(True)
        self.surface.pack_end(self.status,False,False,0)
        self.drawer=box(True,10)
        self.drawer.set_border_width(16)
        self.drawer.set_size_request(490,-1)
        self.drawer.set_halign(Gtk.Align.END); self.drawer.set_valign(Gtk.Align.FILL)
        self.drawer.set_margin_top(12); self.drawer.set_margin_bottom(12); self.drawer.set_margin_end(12)
        self.drawer.get_style_context().add_class('drawer')
        self.drawer.set_no_show_all(True)
        self.overlay.add_overlay(self.drawer)
        self.apply_appearance()
        self.populate_profiles()
        self.build_cards()
        self.engine=Engine(root,self.data,lambda payload: GLib.idle_add(self.receive,payload))
        if preview or smoke: self.engine.visibility_override=True
        self.engine.start()
        self.spawn_listener('desktop.py',['listen'],self.receive_apps)
        if not preview and not smoke: self.spawn_listener('workspace.py',['--listen'],self.receive_workspace)
        self.spawn_listener('visualizer.py',[],self.receive_wave)
        self.ipc_path=self.root/'state/native.sock'
        self.start_ipc()
        self.window.show_all()
        self.toolbar.hide(); self.drawer.hide(); self.status.hide()
        for card in self.cards.values(): card.set_editing(False)
        if not preview and (self.root/'state/home-visible').is_file() and (self.root/'state/home-visible').read_text().strip()=='false':
            self.window.hide()
        GLib.timeout_add_seconds(1,self.tick)
        GLib.timeout_add_seconds(5,self.poll_profile)
        if self.settings.error: self.message('Recovered default settings: '+self.settings.error)
        if smoke: GLib.timeout_add_seconds(4,self.smoke_test)

    @property
    def data(self): return self.transaction.data if self.transaction else self.settings.data

    @property
    def profile(self): return self.data['profiles'][self.data['active_profile']]

    def choose_monitor(self):
        display=Gdk.Display.get_default()
        cfg=read_json(self.root/'settings.json',{})
        selector=cfg.get('monitor',0)
        monitors=[]
        try:
            out=subprocess.run(['hyprctl','monitors','-j'],capture_output=True,text=True,timeout=2,check=True)
            monitors=json.loads(out.stdout)
        except (OSError,ValueError,subprocess.SubprocessError): pass
        index=selector if type(selector) is int else next((i for i,m in enumerate(monitors) if m.get('name')==selector),0)
        index=max(0,min(index,display.get_n_monitors()-1))
        self.monitor=display.get_monitor(index)
        monitor_name=monitors[index].get('name','monitor') if index<len(monitors) else self.monitor.get_model() or 'monitor'
        bounds=self.monitor.get_geometry()
        self.display_key=f'{monitor_name}:{bounds.width}x{bounds.height}@{self.monitor.get_scale_factor()}'
        if not getattr(self,'monitor_signal',None):
            self.monitor_signal=self.monitor.connect('notify::geometry',self.monitor_changed)

    def monitor_changed(self,*_):
        self.choose_monitor()
        self.layout={}
        self.reflow()

    def change_zoom(self,delta=0,reset=False):
        if self.note_timer:
            GLib.source_remove(self.note_timer); self.save_note()
        if self.transaction: self.transaction.checkpoint()
        appearance=self.profile['appearance']
        appearance['scale']=1.0 if reset else round(min(2.0,max(.5,appearance.get('scale',1)+delta)),2)
        if not self.transaction:
            try: self.settings.save()
            except (ValueError,OSError) as exc: self.message('Could not save zoom: '+str(exc)); return
        self.apply_appearance(); self.build_cards()
        self.allocate(self.board_view,self.board_view.get_allocation())
        self.message(f"Zoom {round(appearance['scale']*100)}% · ↶ restores 100%"+(' · Save to keep this preview' if self.transaction else ''))
        self.update_edit_buttons()

    def populate_profiles(self):
        self.populating=True
        self.profile_combo.remove_all()
        names=list(self.data['profiles'])
        for name in names: self.profile_combo.append_text(name)
        self.profile_combo.set_active(names.index(self.data['active_profile']))
        self.populating=False

    def profile_changed(self,widget):
        if getattr(self,'populating',True): return
        name=widget.get_active_text()
        if not name or name==self.data['active_profile']: return
        if self.transaction:
            self.message('Save or cancel your edits before switching profiles')
            self.populate_profiles(); return
        self.settings.data['active_profile']=name
        self.settings.save()
        self.layout={}
        self.apply_appearance(); self.build_cards()
        self.engine.configure(self.data)
        self.message('Profile: '+name)

    def apply_appearance(self):
        appearance=self.profile['appearance']
        zoom=appearance.get('scale',1)
        font=round(appearance['font_size']*zoom)
        text=''
        try: text=(self.root/'colors.scss').read_text()
        except OSError: pass
        colors={name:value for name,value in re.findall(r'\$(\w+):\s*(#[0-9a-fA-F]{6})',text)}
        colors={**{'accent':'#d3bbfc','background':'#0f0d13','card':'#1d1b20','foreground':'#e7e0e8','muted':'#948f99','border':'#49454e'},**colors}
        def rgba(color,alpha):
            value=colors[color].lstrip('#')
            return 'rgba('+','.join(str(int(value[i:i+2],16)) for i in (0,2,4))+','+str(alpha)+')'
        css=f'''
        window {{ background: transparent; color: {colors['foreground']}; }}
        .dashboard {{ background: {rgba('background',appearance['opacity'])}; }}
        * {{ font-family: "JetBrains Mono", monospace; font-size: {font}px; }}
        .card, .rail {{ background: {rgba('card', min(1,appearance['opacity']+.12))}; border: 1px solid {colors['border']}; border-radius: 10px; }}
        .edit-cover {{ background: rgba(180,150,240,.035); }}
        .card:hover {{ border-color: {colors['muted']}; }}
        .heading {{ color: {colors['accent']}; font-weight: bold; }}
        .hostname, .clock {{ font-size: {round((appearance['font_size']+12)*zoom)}px; font-weight: bold; }}
        .media-title {{ font-size: {round((appearance['font_size']+5)*zoom)}px; font-weight: bold; }}
        .muted, .freshness {{ color: {colors['muted']}; }}
        .freshness {{ font-size: {max(8,round((appearance['font_size']-3)*zoom))}px; }}
        .month {{ font-family: monospace; }}
        .warning {{ color: #f3a580; }}
        button, combobox, entry, spinbutton {{ color: {colors['foreground']}; background: {rgba('card',.95)}; border: 1px solid {colors['border']}; border-radius: 6px; padding: {max(2,round(4*zoom))}px {max(3,round(7*zoom))}px; }}
        button:hover {{ border-color: {colors['accent']}; }}
        button:disabled {{ opacity: .45; }}
        textview, textview text {{ color: {colors['foreground']}; background: transparent; }}
        progressbar trough {{ min-height: 6px; background: {colors['border']}; }}
        progressbar progress {{ min-height: 6px; background: {colors['accent']}; }}
        .drawer {{ background: {colors['background']}; border: 1px solid {colors['accent']}; border-radius: 10px; }}
        popover, menu {{ background: {colors['background']}; color: {colors['foreground']}; }}
        scrollbar slider {{ min-width: 5px; min-height: 20px; background: {colors['border']}; border-radius: 3px; }}
        '''
        self.provider.load_from_data(css.encode())
        self.surface.set_spacing(round(appearance['spacing']*zoom))
        self.main.set_spacing(round(appearance['spacing']*zoom)) if hasattr(self,'main') else None
        if hasattr(self,'rail'): self.rail.set_size_request(round(94*zoom),-1)
        if hasattr(self,'zoom_label'): self.zoom_label.set_text(f'{round(zoom*100)}%')
        self.theme=colors
        if getattr(self,'app_lists',None): self.receive_apps(self.app_lists)
        if hasattr(self,'cards'):
            for card in self.cards.values(): card.queue_draw()

    def build_cards(self):
        for child in self.fixed.get_children(): self.fixed.remove(child)
        self.cards={}
        self.layout={}
        for key in self.profile['visible']:
            card=Card(self,key)
            self.cards[key]=card
            self.fixed.put(card,0,0)
            card.show_all(); card.set_editing(self.editing)
        self.reflow()

    def reflow(self):
        width,height=self.canvas_size
        if width<2 or height<2: return
        saved=self.profile['layouts'].get(self.display_key,{})
        if set(saved)==set(self.cards): self.layout=deepcopy(saved)
        else:
            self.layout=default_layout(list(self.cards),width,height,round(self.profile['appearance']['spacing']*self.profile['appearance'].get('scale',1)),self.data['active_profile'])
            if width>=850 and all(key in self.layout for key in ('performance','processes','shares')):
                # Shares take space from the scrolling process list as mount text grows.
                shares=self.samples.get('shares',{}).get('value') or []
                share_rect=self.layout['shares']; process_rect=self.layout['processes']
                if abs(share_rect[0]-process_rect[0])<.001:
                    appearance=self.profile['appearance']; font=appearance['font_size']; gap=appearance['spacing']
                    chars=max(12,int((share_rect[2]*width-32)/(font*.65)))
                    lines=sum(3+math.ceil((len(s.get('source',''))+len(s.get('target','')))/chars) for s in shares if isinstance(s,dict))
                    desired=max(share_rect[3]*height,85+lines*(font*1.5+5))
                    extra=min(max(0,desired-share_rect[3]*height),max(0,process_rect[3]*height-140))
                    process_rect[3]-=extra/height
                    share_rect[1]-=extra/height; share_rect[3]+=extra/height
        for key,rect in self.layout.items(): self.place_card(key,rect)
        self.guide_layer.queue_draw()

    def allocate(self,widget,allocation):
        zoom=self.profile['appearance'].get('scale',1)
        count=len(self.profile['visible'])
        virtual_width=max(allocation.width-8,round((allocation.width-8)*zoom))
        columns=3 if virtual_width>=850 else 2 if virtual_width>=550 else 1
        if columns==3:
            visible=self.profile['visible']
            groups=[sum(c in visible for c in group) for group in (('arch','system','connectivity','session','power'),('performance','processes','shares'),('calendar','player'))]
            for key in visible:
                if key not in BASE_CARDS: groups[groups.index(min(groups))]+=1
            max_rows=max(1,max(groups))
        else: max_rows=max(1,math.ceil(count/columns))
        minimum=round((max_rows*(self.profile['appearance']['font_size']*4+70)+max(0,max_rows-1)*self.profile['appearance']['spacing'])*zoom)
        size=(max(1,virtual_width),max(allocation.height,round(allocation.height*zoom),minimum))
        if size!=self.canvas_size:
            self.canvas_size=size
            self.board.set_size_request(*size)
            self.fixed.set_size_request(*size)
            self.reflow()
            atomic_json(self.root/'state/wave-size.json',{'width':max(80,int(size[0]*.3)-30),'height':36})

    def place_card(self,key,rect):
        if key not in self.cards: return
        width,height=self.canvas_size
        x,y,w,h=rect
        card=self.cards[key]
        card.set_size_request(max(1,round(w*width)),max(1,round(h*height)))
        self.fixed.move(card,round(x*width),round(y*height))

    def store_layout(self):
        self.profile['layouts'][self.display_key]=deepcopy(self.layout)

    def draw_guides(self,widget,cr):
        if not self.editing: return False
        width,height=self.canvas_size
        if self.profile['appearance']['snap']:
            cr.set_source_rgba(.8,.72,1,.12)
            step=self.profile['appearance']['grid_size']
            for x in range(0,width,step):
                for y in range(0,height,step): cr.rectangle(x,y,1,1)
            cr.fill()
        cr.set_source_rgba(.45,.9,.75,.9); cr.set_line_width(1)
        for axis,pos in self.guides:
            cr.move_to(pos,0) if axis=='x' else cr.move_to(0,pos)
            cr.line_to(pos,height) if axis=='x' else cr.line_to(width,pos)
        cr.stroke()
        return False

    def begin(self):
        if not self.transaction:
            if self.note_timer:
                GLib.source_remove(self.note_timer); self.save_note()
            self.transaction=Transaction(self.settings.data)

    def edit_menu(self):
        content=self.drawer_page('Edit dashboard',editable=bool(self.transaction))
        content.pack_start(label('Choose what to change. Each editor has visible Save and Cancel controls.',wrap=True),False,False,0)
        self.edit_actions={}
        for text,callback in [('Move & resize cards',self.edit_layout),('Refresh intervals',lambda:self.open_settings('Refresh intervals')),
                              ('Appearance',lambda:self.open_settings('Appearance')),('Add / hide cards',lambda:self.open_settings('Cards')),
                              ('Profiles',lambda:self.open_settings('Profiles'))]:
            control=button(text,callback)
            self.edit_actions[text]=control
            content.pack_start(control,False,False,0)
        reveal(self.drawer)

    def edit_layout(self):
        self.begin(); self.drawer.hide()
        self.editing=True
        reveal(self.toolbar); self.status.show()
        self.snap_check.set_active(self.profile['appearance']['snap'])
        self.store_layout()
        for card in self.cards.values(): card.set_editing(True)
        self.status.set_text('Move cards by dragging inside · resize with any edge or corner · Ctrl+Z undoes')
        self.update_edit_buttons(); self.guide_layer.queue_draw()

    def update_edit_buttons(self):
        if not self.transaction: return
        self.undo_button.set_sensitive(bool(self.transaction.undo_stack))
        self.redo_button.set_sensitive(bool(self.transaction.redo_stack))

    def undo(self):
        if self.transaction and self.transaction.undo():
            self.apply_appearance(); self.build_cards()
            self.allocate(self.board_view,self.board_view.get_allocation())
            self.update_edit_buttons()
            self.snap_check.set_active(self.profile['appearance']['snap'])

    def redo(self):
        if self.transaction and self.transaction.redo():
            self.apply_appearance(); self.build_cards()
            self.allocate(self.board_view,self.board_view.get_allocation())
            self.update_edit_buttons()
            self.snap_check.set_active(self.profile['appearance']['snap'])

    def reset_layout(self):
        if not self.transaction: return
        self.transaction.checkpoint()
        self.profile['layouts'].pop(self.display_key,None)
        self.reflow(); self.store_layout(); self.update_edit_buttons()

    def snap_changed(self,widget):
        if self.transaction:
            self.profile['appearance']['snap']=widget.get_active()
            self.guide_layer.queue_draw()

    def save(self):
        if not self.transaction: return
        if self.note_timer:
            GLib.source_remove(self.note_timer); self.save_note()
        try:
            if self.editing: self.store_layout()
            self.settings.save(self.transaction.data)
        except (ValueError,OSError) as exc:
            self.message('Could not save: '+str(exc)); return
        self.transaction=None
        self.finish_edit()
        self.engine.configure(self.data)
        self.message('Changes saved')

    def cancel(self):
        if self.note_timer:
            GLib.source_remove(self.note_timer); self.note_timer=None
        self.transaction=None
        self.finish_edit()
        self.message('Edits discarded')

    def finish_edit(self):
        self.editing=False; self.guides=[]; self.preview=None
        self.toolbar.hide(); self.drawer.hide()
        self.populate_profiles(); self.apply_appearance(); self.build_cards()
        self.guide_layer.queue_draw()

    def key_press(self,widget,event):
        if not self.transaction: return False
        if event.keyval==Gdk.KEY_Escape: self.cancel(); return True
        if not self.editing: return False
        ctrl=bool(event.state&Gdk.ModifierType.CONTROL_MASK)
        if ctrl and event.keyval in (Gdk.KEY_z,Gdk.KEY_Z):
            self.redo() if event.state&Gdk.ModifierType.SHIFT_MASK else self.undo()
            return True
        if ctrl and event.keyval in (Gdk.KEY_y,Gdk.KEY_Y): self.redo(); return True
        if event.keyval==Gdk.KEY_Escape: self.cancel(); return True
        return False

    def message(self,text):
        self.status.set_text(text); self.status.show()

    def close_panel(self):
        if self.transaction and not self.editing: self.cancel()
        else: self.drawer.hide()

    def drawer_page(self,title,editable=True):
        clear(self.drawer)
        heading=box(False,6); heading.pack_start(label(title,'heading'),True,True,0)
        heading.pack_end(button('×',self.close_panel,'Close panel'),False,False,0)
        self.drawer.pack_start(heading,False,False,0)
        content=box(True,10)
        self.drawer.pack_start(scroll(content),True,True,0)
        controls=box(False,7)
        if editable:
            controls.pack_start(button('Save',self.save),True,True,0)
            controls.pack_start(button('Cancel',self.cancel),True,True,0)
            controls.pack_end(button('Layout',self.edit_layout),False,False,0)
        else: controls.pack_end(button('Close',self.close_panel),False,False,0)
        self.drawer.pack_end(controls,False,False,0)
        return content

    def open_settings(self,section):
        self.begin()
        # Switching panels does not discard a pending layout draft.
        self.editing=False; self.toolbar.hide()
        for card in self.cards.values(): card.set_editing(False)
        content=self.drawer_page(section)
        if section=='Refresh intervals': self.refresh_settings(content)
        elif section=='Appearance': self.appearance_settings(content)
        elif section=='Cards': self.card_settings(content)
        elif section=='Profiles': self.profile_settings(content)
        reveal(self.drawer)
        self.status.show(); self.status.set_text('Changes remain a preview until you Save · Cancel restores previous settings')

    def refresh_settings(self,parent):
        parent.pack_start(label('Intervals are in seconds. Hidden dashboards pause on battery; your chosen intervals are retained.',wrap=True),False,False,0)
        for card in self.profile['visible']:
            sources=SOURCES.get(card,())
            if not sources: continue
            section=box(True,6)
            for source in sources:
                line=box(False,6)
                line.pack_start(label(SOURCE_TITLES.get(source,CARDS[card][0])),True,True,0)
                spin=Gtk.SpinButton.new_with_range(1,86400,1)
                spin.set_value(self.profile['refresh'].get(source,REFRESH[source]))
                spin.set_numeric(True); spin.set_width_chars(6)
                spin.connect('value-changed',lambda widget,s=source:self.set_interval(s,widget.get_value_as_int()))
                line.pack_end(spin,False,False,0)
                section.pack_start(line,False,False,0)
            frame=Gtk.Expander(label=CARDS[card][0]); frame.set_expanded(True); frame.add(section)
            parent.pack_start(frame,False,False,0)
        line=box(False,6); line.pack_start(label('Health checks'),True,True,0)
        spin=Gtk.SpinButton.new_with_range(1,86400,1); spin.set_value(self.profile['refresh']['health'])
        spin.connect('value-changed',lambda widget:self.set_interval('health',widget.get_value_as_int()))
        line.pack_end(spin,False,False,0); parent.pack_start(line,False,False,0)
        parent.pack_start(button('Restore default intervals',self.reset_intervals),False,False,0)

    def set_interval(self,source,value): self.profile['refresh'][source]=value

    def reset_intervals(self):
        self.transaction.checkpoint(); self.profile['refresh']=deepcopy(REFRESH)
        self.open_settings('Refresh intervals')

    def appearance_settings(self,parent):
        parent.pack_start(label('Changes preview immediately. Appearance is saved separately for each profile.',wrap=True),False,False,0)
        appearance=self.profile['appearance']
        parent.pack_start(label('Dashboard zoom: use − / + beside the profile selector; ↶ resets it to 100%. Zoom is saved per profile.',wrap=True),False,False,0)
        for title,key,low,high,step in [('Background opacity','opacity',.15,1,.05),('Font size','font_size',9,24,1),
                                       ('Card spacing','spacing',4,24,1),('Snap grid','grid_size',4,40,1)]:
            line=box(False,8); line.pack_start(label(title),True,True,0)
            spin=Gtk.SpinButton.new_with_range(low,high,step); spin.set_digits(2 if key=='opacity' else 0); spin.set_value(appearance[key])
            def changed(widget,k=key):
                appearance[k]=widget.get_value() if k=='opacity' else widget.get_value_as_int()
                self.apply_appearance()
                if k=='spacing' and self.display_key not in self.profile['layouts']: self.reflow()
            spin.connect('value-changed',changed); line.pack_end(spin,False,False,0); parent.pack_start(line,False,False,0)
        for title,key in [('Show history graphs','graphs'),('Snap cards and show alignment guides','snap')]:
            check=Gtk.CheckButton.new_with_label(title); check.set_active(appearance[key])
            def toggled(widget,k=key):
                appearance[k]=widget.get_active()
                if k=='graphs':
                    for card in self.cards.values():
                        if card.key in ('performance','connectivity','power'): card.render()
            check.connect('toggled',toggled); parent.pack_start(check,False,False,0)
        combo=Gtk.ComboBoxText()
        for minutes in (5,15,30,60): combo.append_text(str(minutes)+' minutes of history')
        combo.set_active((5,15,30,60).index(appearance['history_minutes']))
        combo.connect('changed',lambda widget:appearance.update(history_minutes=(5,15,30,60)[widget.get_active()]))
        parent.pack_start(combo,False,False,0)
        parent.pack_start(button('Restore appearance defaults',self.reset_appearance),False,False,0)

    def reset_appearance(self):
        self.transaction.checkpoint(); self.profile['appearance']=deepcopy(DEFAULT_APPEARANCE)
        self.apply_appearance(); self.build_cards(); self.open_settings('Appearance')

    def card_settings(self,parent):
        parent.pack_start(label('Choose cards for this profile. Adding or hiding a card resets this profile’s layout on the current display; other display layouts remain saved.',wrap=True),False,False,0)
        for key,(title,description) in CARDS.items():
            check=Gtk.CheckButton.new_with_label(title); check.set_active(key in self.profile['visible'])
            check.set_tooltip_text(description)
            check.connect('toggled',lambda widget,k=key:self.toggle_card(k,widget.get_active()))
            parent.pack_start(check,False,False,0)
        parent.pack_start(Gtk.Separator(),False,False,4)
        parent.pack_start(label('INTEGRATIONS','heading'),False,False,0)
        parent.pack_start(label('Optional cards make requests only when enabled and configured. Notes and tasks stay local.',wrap=True),False,False,0)
        integrations=self.data['integrations']
        fields=[('Weather latitude','weather','latitude',False),('Weather longitude','weather','longitude',False),
                ('RSS / Atom URLs (one per line)','feeds','urls',False),
                ('NAS JSON URL','nas','url',False),('NAS bearer token (optional)','nas','token',True),
                ('Remote machine JSON URL','remote','url',False),('Remote bearer token (optional)','remote','token',True)]
        for title,card,field,secret in fields:
            parent.pack_start(label(title,'muted'),False,False,0)
            if field=='urls':
                text=Gtk.TextView(); text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR); text.set_size_request(-1,90)
                text.get_buffer().set_text(integrations[card].get(field,''))
                def edited(buffer,c=card,f=field):
                    integrations[c][f]=buffer.get_text(buffer.get_start_iter(),buffer.get_end_iter(),True)
                text.get_buffer().connect('changed',edited); parent.pack_start(text,False,False,0)
            else:
                entry=Gtk.Entry(); entry.set_text(str(integrations[card].get(field,''))); entry.set_visibility(not secret)
                entry.connect('changed',lambda widget,c=card,f=field:integrations[c].update({f:widget.get_text().strip()}))
                parent.pack_start(entry,False,False,0)
        parent.pack_start(label('NAS and remote endpoints return a JSON object, for example: {"host":"server", "cpu":18, "disk_free_gib":240, "status":"healthy"}. Fields appear as readable details. Docker uses your existing local Docker access.',wrap=True),False,False,0)
        parent.pack_start(label('MONITORED SHARE PATHS','heading'),False,False,0)
        expected=Gtk.Entry(); expected.set_text(', '.join(self.data.get('expected_shares',[])))
        expected.set_placeholder_text('/mnt/media, /mnt/backups')
        expected.connect('changed',lambda widget:self.data.update(expected_shares=[p.strip() for p in widget.get_text().split(',') if p.strip()]))
        parent.pack_start(expected,False,False,0)
        parent.pack_start(label('VPN CONNECTIONS TO MONITOR','heading'),False,False,0)
        for key,title in [('tailscale','Tailscale'),('proton','Proton VPN')]:
            check=Gtk.CheckButton.new_with_label(title)
            check.set_active(key in self.data.get('expected_vpns',[]))
            def changed(widget,name=key):
                monitored=self.data.setdefault('expected_vpns',[])
                if widget.get_active() and name not in monitored: monitored.append(name)
                elif not widget.get_active() and name in monitored: monitored.remove(name)
            check.connect('toggled',changed); parent.pack_start(check,False,False,0)

    def toggle_card(self,key,enabled):
        self.transaction.checkpoint()
        visible=self.profile['visible']
        if enabled and key not in visible: visible.append(key)
        elif not enabled and key in visible: visible.remove(key)
        self.profile['layouts'].pop(self.display_key,None)
        self.build_cards()

    def profile_settings(self,parent):
        parent.pack_start(label('Profiles remember card visibility, refresh intervals, appearance and a separate layout for each monitor and resolution.',wrap=True),False,False,0)
        parent.pack_start(label('Current profile: '+self.data['active_profile'],'heading'),False,False,0)
        entry=Gtk.Entry(); entry.set_placeholder_text('New profile name')
        parent.pack_start(entry,False,False,0)
        parent.pack_start(button('Duplicate current profile',lambda:self.duplicate_profile(entry.get_text())),False,False,0)
        parent.pack_start(button('Rename current profile',lambda:self.rename_profile(entry.get_text())),False,False,0)
        parent.pack_start(button('Delete current profile',self.delete_profile),False,False,0)
        parent.pack_start(label('Daily balances the existing cards. Monitoring gives Performance more space. Minimal starts with five essential cards. Switch using the profile selector beside Packages.',wrap=True),False,False,0)
        parent.pack_start(label('Display: '+self.display_key,'muted',True),False,False,0)
        parent.pack_start(button('Reset current display layout',self.reset_profile_layout),False,False,0)

    def profile_name(self,name):
        name=name.strip()
        if not name or len(name)>40 or any(ord(c)<32 for c in name):
            self.message('Choose a profile name with 1–40 printable characters'); return None
        if name in self.data['profiles']:
            self.message('That profile name already exists'); return None
        return name

    def duplicate_profile(self,name):
        name=self.profile_name(name)
        if not name: return
        if len(self.data['profiles'])>=30: self.message('You can keep up to 30 profiles'); return
        self.transaction.checkpoint(); self.data['profiles'][name]=deepcopy(self.profile)
        self.data['active_profile']=name
        self.populate_profiles(); self.open_settings('Profiles')

    def rename_profile(self,name):
        name=self.profile_name(name)
        if not name: return
        self.transaction.checkpoint(); old=self.data['active_profile']
        self.data['profiles'][name]=self.data['profiles'].pop(old); self.data['active_profile']=name
        self.populate_profiles(); self.open_settings('Profiles')

    def delete_profile(self):
        if len(self.data['profiles'])==1: self.message('Keep at least one profile'); return
        self.transaction.checkpoint(); self.data['profiles'].pop(self.data['active_profile'])
        self.data['active_profile']=next(iter(self.data['profiles']))
        self.populate_profiles(); self.apply_appearance(); self.build_cards(); self.open_settings('Profiles')

    def reset_profile_layout(self):
        self.reset_layout(); self.open_settings('Profiles')

    def card_menu(self,card):
        content=self.drawer_page(CARDS[card.key][0]+' · actions',editable=False)
        for title,callback in [('Refresh now',lambda:self.refresh_card(card.key)),
                               ('Move / resize',self.edit_layout),('Refresh interval',lambda:self.open_settings('Refresh intervals')),
                               ('Card library',lambda:self.open_settings('Cards'))]:
            content.pack_start(button(title,callback),False,False,0)
        if card.key=='arch': content.pack_start(button('Open update list',lambda:self.run('launch.sh','updates')),False,False,0)
        reveal(self.drawer)

    def refresh_card(self,key):
        for source in SOURCES.get(key,()): self.engine.request(source)

    def run(self,script,*arguments):
        path=self.root/'scripts'/script
        argv=[str(path),*map(str,arguments)]
        if script.endswith('.py'): argv.insert(0,sys.executable)
        try:
            child=subprocess.Popen(argv,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
            # Launchers hand off to desktop apps. Do not kill them when the dashboard exits.
            if script in ('idle-control.py','power-control.py'):
                def completed():
                    code=child.wait()
                    GLib.idle_add(self.action_done,script,code)
                threading.Thread(target=completed,daemon=True).start()
        except OSError as exc: self.message('Could not open: '+str(exc))

    def action_done(self,script,code):
        if self.closing: return False
        if code: self.message('The action could not complete. Check the card’s status and try again.')
        if script=='idle-control.py': self.engine.request('session')
        elif 'power' in self.cards: self.cards['power'].render()
        return False

    def idle_action(self,*arguments): self.run('idle-control.py',*arguments)

    def seek(self,value):
        self.run('media-actions.py','seek',str(value))
        GLib.timeout_add(400,lambda:(self.engine.request('media'),False)[1])
        return False

    def open_url(self,url):
        from urllib.parse import urlparse
        if urlparse(url).scheme in ('http','https'):
            subprocess.Popen(['gio','open',url],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)

    def open_folder(self,path):
        target=Path(path)
        if target.is_absolute() and target.is_dir():
            subprocess.Popen(['gio','open',target.as_uri()],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        else: self.message('That mount folder is no longer available')

    def remember_shares(self,paths):
        if self.transaction:
            self.transaction.checkpoint(); self.data['expected_shares']=list(paths)
            self.message('Monitored paths updated in your draft. Save to keep them.')
        else:
            self.settings.data['expected_shares']=list(paths); self.settings.save()
            self.engine.configure(self.data)
            self.message('These mount paths will be checked for disconnections')
        self.update_health()

    def schedule_note(self,buffer):
        if self.note_timer: GLib.source_remove(self.note_timer)
        text=buffer.get_text(buffer.get_start_iter(),buffer.get_end_iter(),True)
        self.pending_note=text
        self.note_timer=GLib.timeout_add(600,self.save_note)

    def save_note(self):
        self.note_timer=None
        if len(self.pending_note)>100000:
            self.message('Keep notes under 100,000 characters to save them'); return False
        if self.transaction:
            self.data['notes']=self.pending_note
        else:
            self.settings.data['notes']=self.pending_note
            try: self.settings.save()
            except (ValueError,OSError) as exc: self.message('Could not save note: '+str(exc))
        return False

    def add_task(self,entry):
        text=entry.get_text().strip()
        if not text: return
        if len(text)>1000: self.message('Keep each task under 1000 characters'); return
        if len(self.data['tasks'])>=500: self.message('Keep up to 500 tasks; remove one before adding another'); return
        self.data['tasks'].append({'text':text,'done':False}); entry.set_text('')
        self.save_tasks()

    def toggle_task(self,index,done):
        if index<len(self.data['tasks']): self.data['tasks'][index]['done']=done; self.save_tasks()

    def delete_task(self,index):
        if index<len(self.data['tasks']): self.data['tasks'].pop(index); self.save_tasks()

    def save_tasks(self):
        if not self.transaction:
            try: self.settings.save()
            except (ValueError,OSError) as exc: self.message('Could not save tasks: '+str(exc))
        if 'tasks' in self.cards:
            clear(self.cards['tasks'].body); self.cards['tasks'].render()

    def process_details(self,process):
        parent=self.drawer_page('Process details',editable=False)
        row(parent,'Name',process.get('name','—')); row(parent,'PID',process.get('pid','—'))
        row(parent,'CPU',process.get('cpu','—')); row(parent,'Memory',process.get('memory','—'))
        pid=str(process.get('pid',''))
        if pid.isdigit():
            try:
                path=Path('/proc')/pid
                status=(path/'status').read_text()
                fields=dict(line.split(':',1) for line in status.splitlines() if ':' in line)
                for title,key in [('State','State'),('Threads','Threads'),('Resident memory','VmRSS'),('Virtual memory','VmSize')]: row(parent,title,fields.get(key,'—').strip())
                row(parent,'Executable',os.readlink(path/'exe'))
            except (OSError,ValueError): parent.pack_start(label('This process ended or its details are restricted.',wrap=True),False,False,0)
        parent.pack_start(button('Open btop for more details',lambda:self.run('launch.sh','system')),False,False,0)
        reveal(self.drawer)

    def power_profile(self):
        base=Path(os.environ.get('XDG_STATE_HOME',Path.home()/'.local/state'))/'poedash'
        # Existing power-policy service is retained; this surface only reads it.
        return read_json(base/'power-policy.json',{})

    def receive(self,payload):
        if self.closing: return False
        gate=payload.pop('_gate',None)
        if gate:
            self.paused=gate['on_battery'] and not gate['visible']
            self.visible=gate['visible'] or self.preview_window or self.smoke
            if (self.root/'disabled').exists(): self.quit(); return False
            if self.visible:
                if not self.window.get_visible(): self.window.show()
            else: self.window.hide()
        changed=set(payload)
        self.samples.update(payload)
        numeric={}
        for source in ('cpu','ram'):
            sample=payload.get(source,{})
            if not sample.get('error') and isinstance(sample.get('value'),(int,float)): numeric[source]=sample['value']
        temperature=payload.get('cpu_temperature',{}).get('value')
        if isinstance(temperature,str):
            try: numeric['temperature']=float(temperature.replace('°C',''))
            except ValueError: pass
        network=payload.get('network',{}).get('value') or {}
        if isinstance(network,dict):
            for key in ('rx_bps','tx_bps'):
                if isinstance(network.get(key),(int,float)): numeric[key]=network[key]
        power=payload.get('power',{}).get('value') or {}
        if isinstance(power,dict):
            try: numeric['watts']=float(str(power.get('watts','')).rstrip(' W'))
            except ValueError: pass
        if numeric: self.history.add(numeric)
        if 'media' in changed:
            media=payload['media'].get('value') or {}
            if isinstance(media,dict):
                playing=media.get('status')=='Playing'
                (self.root/'state/media-playing').write_text(str(playing).lower())
                atomic_json(self.root/'state/media-timeline.json',{'progress':media.get('progress',0),'position':media.get('position_seconds',0),
                    'length':media.get('length_seconds',0),'playing':playing,'sampled':media.get('sampled_at',time.monotonic())})
                uri=media.get('uri','')
                if playing and 'spotify' in media.get('player','').lower() and uri: atomic_json(self.root/'state/spotify-last.json',{'uri':uri})
        if 'shares' in changed and self.display_key not in self.profile['layouts']:
            self.reflow()
        for key,card in self.cards.items():
            if changed.intersection(SOURCES.get(key,())) or (key=='system' and 'health' in changed): card.render()
            card.update_freshness()
        self.update_health()
        self.diagnostic_payload=json.dumps({'profile':self.data['active_profile'],'visible':self.visible,'paused':self.paused,'canvas':self.canvas_size,'cards':list(self.cards),'zoom':self.profile['appearance'].get('scale',1),'samples':{key:{'updated':value.get('updated',0),'error':value.get('error','')} for key,value in self.samples.items()}})
        return False

    def update_health(self):
        values={key:sample.get('value') for key,sample in self.samples.items() if sample.get('value') is not None}
        self.issues=health_issues(values,self.data.get('expected_shares',[]),self.data.get('expected_vpns',[]))
        if not self.samples: return
        if self.issues:
            summary=self.issues[0]['text']
            if len(self.issues)>1: summary+=f' · {len(self.issues)-1} more'
            self.health_label.set_text('● '+summary)
            self.health_label.get_style_context().add_class('warning')
        else:
            self.health_label.set_text('● Health check unavailable' if self.samples.get('health',{}).get('error') else '● No health issues detected' if self.samples.get('health',{}).get('value') is not None else 'Checking system health…')
            self.health_label.get_style_context().remove_class('warning')
        self.health_button.set_label(f"Details ({len(self.issues)})" if self.issues else 'Health')

    def show_health(self):
        parent=self.drawer_page('System health',editable=False)
        issues=getattr(self,'issues',[])
        if not issues: parent.pack_start(label('No health issues detected.' if self.samples.get('health',{}).get('value') is not None else 'Health checks are still loading or unavailable.',wrap=True),False,False,0)
        for source,sample in self.samples.items():
            if sample.get('error'): parent.pack_start(label(SOURCE_TITLES.get(source,source.title())+': '+sample['error'],'warning',True),False,False,0)
        for issue in issues:
            parent.pack_start(button(issue['text'],lambda key=issue['card']:self.focus_card(key)),False,False,0)
        parent.pack_start(label('Checks cover disk space, failed system/user services, network connectivity, monitored shares and low battery.',wrap=True),False,False,0)
        parent.pack_start(button('Check again now',lambda:[self.engine.request(s) for s in ('health','network','shares','power')]),False,False,0)
        parent.pack_start(button('Configure monitored shares',lambda:self.open_settings('Cards')),False,False,0)
        reveal(self.drawer)

    def focus_card(self,key):
        self.drawer.hide()
        if key not in self.cards:
            self.message(CARDS[key][0]+' is hidden in this profile. Enable it from Edit → Cards.'); return
        card=self.cards[key]
        card.get_style_context().add_class('drawer')
        GLib.timeout_add_seconds(2,lambda:(card.get_style_context().remove_class('drawer'),False)[1])
        if key=='system': self.engine.request('health')

    def spawn_listener(self,name,arguments,callback):
        path=self.root/'scripts'/name
        if not path.exists(): return
        try:
            child=subprocess.Popen([sys.executable,str(path),*arguments],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,start_new_session=True)
            self.children.append(child)
            def read():
                try:
                    for line in child.stdout:
                        if self.closing: break
                        try: payload=json.loads(line)
                        except ValueError: continue
                        GLib.idle_add(callback,payload)
                except (OSError,ValueError): pass
            threading.Thread(target=read,daemon=True,name='poedash-'+name).start()
        except OSError: pass

    def receive_workspace(self,visible):
        if self.closing: return False
        if isinstance(visible,bool):
            self.engine.visibility_override=visible
            self.receive({'_gate':{'visible':visible,'on_battery':self.engine.on_battery}})
        return False

    def receive_apps(self,payload):
        if self.closing: return False
        self.app_lists=payload
        clear(self.rail_body)
        for category,title in [('pinned','PINNED'),('recent','RECENT')]:
            items=payload.get(category,[])
            if category=='pinned' and not items: continue
            heading=label(title,'freshness'); heading.set_margin_top(10)
            self.rail_body.pack_start(heading,False,False,0)
            if not items: self.rail_body.pack_start(label('Open an app\nto start','muted',True),False,False,0)
            for app in items:
                content=box(True,4)
                image=Gtk.Image.new_from_icon_name(app.get('icon','application-x-executable'),Gtk.IconSize.DND)
                image.set_pixel_size(round(40*self.profile['appearance'].get('scale',1)))
                content.pack_start(image,False,False,0)
                text=label(app.get('name','App')); text.set_max_width_chars(9); text.set_xalign(.5)
                content.pack_start(text,False,False,0)
                action=Gtk.Button(); action.add(content)
                action.set_tooltip_text(app.get('name','')+' · Right click to '+('unpin' if category=='pinned' else 'pin'))
                action.connect('clicked',lambda widget,ident=app['id']:self.run('desktop.py','launch',ident))
                action.connect('button-press-event',lambda widget,event,ident=app['id']:self.pin_app(event,ident))
                self.rail_body.pack_start(action,False,False,0)
        self.rail_body.set_border_width(8); self.rail_body.show_all()
        return False

    def pin_app(self,event,identifier):
        if event.button==3: self.run('desktop.py','pin',identifier); return True
        return False

    def receive_wave(self,payload):
        if self.closing: return False
        self.wave=payload
        if 'player' in self.cards: self.cards['player'].update_wave()
        return False

    def poll_profile(self):
        if self.closing: return False
        if 'power' in self.cards and not self.paused: self.cards['power'].render()
        return True

    def tick(self):
        if self.closing: return False
        now=datetime.datetime.now()
        if self.visible:
            self.clock.set_text(now.strftime('%H:%M\n%a %d %b'))
            for card in self.cards.values():
                card.update_freshness()
                for widget in card.body.get_children():
                    if isinstance(widget,Graph): widget.queue_draw()
            try:
                stamp=(self.root/'colors.scss').stat().st_mtime_ns
                if stamp!=self.theme_stamp: self.theme_stamp=stamp; self.apply_appearance()
            except OSError: pass
        self.children=[child for child in self.children if child.poll() is None]
        return True

    def start_ipc(self):
        self.ipc_path.parent.mkdir(parents=True,exist_ok=True)
        self.ipc_path.unlink(missing_ok=True)
        self.server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.server.bind(str(self.ipc_path)); self.ipc_path.chmod(0o600)
        self.server.listen(4); self.server.settimeout(.5)
        def serve():
            while not self.closing:
                try:
                    connection,_=self.server.accept()
                    with connection:
                        connection.settimeout(1)
                        command=connection.recv(100).decode(errors='replace').strip()
                        if command=='quit': GLib.idle_add(self.quit); connection.sendall(b'ok\n')
                        elif command=='status': connection.sendall(b'active\n')
                        elif command=='diagnostics': connection.sendall(self.diagnostic_payload.encode()+b'\n')
                        elif command=='reload': GLib.idle_add(self.reload); connection.sendall(b'ok\n')
                except (OSError,TimeoutError): continue
        threading.Thread(target=serve,daemon=True,name='poedash-control').start()

    def reload(self):
        if self.closing: return False
        if self.transaction:
            self.message('Finish your current edits before reloading settings'); return False
        self.settings=Settings(self.root); self.populate_profiles(); self.apply_appearance(); self.build_cards()
        self.engine.configure(self.data)
        return False

    def smoke_test(self):
        """Exercise the actual widgets on an offscreen GTK window."""
        try:
            if not self.cards: raise RuntimeError('No cards were created')
            if not getattr(self,'smoke_zoomed',False):
                self.change_zoom(.25)
                if self.profile['appearance']['scale']!=1.25: raise RuntimeError('Zoom in failed')
                self.change_zoom(reset=True)
                if self.profile['appearance']['scale']!=1: raise RuntimeError('Zoom reset failed')
                self.smoke_zoomed=True
                GLib.timeout_add(400,self.smoke_test)
                return False
            self.edit_layout()
            if not self.toolbar.get_visible(): raise RuntimeError('Editing toolbar is hidden')
            for control in self.toolbar.get_children():
                if not control.get_visible(): raise RuntimeError('Editing control is hidden')
            if not all(card.cover.get_visible() for card in self.cards.values()): raise RuntimeError('Drag overlay is hidden')
            from types import SimpleNamespace
            if 'arch' in self.cards and 'system' in self.cards:
                original=deepcopy(self.layout)
                card=self.cards['arch']; target=self.layout['system']
                origin=self.layout['arch']; width,height=self.canvas_size
                press=SimpleNamespace(button=1,x=card.get_allocated_width()/2,y=card.get_allocated_height()/2,x_root=100,y_root=100)
                card.press(card.cover,press)
                dx=((target[0]+target[2]/2)-(origin[0]+origin[2]/2))*width
                dy=((target[1]+target[3]/2)-(origin[1]+origin[3]/2))*height
                card.motion(card.cover,SimpleNamespace(x_root=100+dx,y_root=100+dy))
                card.release(card.cover,press)
                if self.layout['arch']!=original['system']: raise RuntimeError('Pointer-driven card swap failed')
                self.undo()
                if self.layout!=original: raise RuntimeError('Undo did not restore the layout')
                self.redo()
            for card in self.cards.values():
                for point in ((1,1),(card.get_allocated_width()-1,1),(1,card.get_allocated_height()-1)):
                    if not card.edge(*point): raise RuntimeError('Missing resize handle')
            self.reset_layout(); self.undo(); self.redo()
            for section in ('Refresh intervals','Appearance','Cards','Profiles'):
                self.open_settings(section)
                if not self.drawer.get_visible(): raise RuntimeError(section+' panel is hidden')
            self.duplicate_profile('Smoke profile')
            self.rename_profile('Smoke renamed')
            self.delete_profile()
            for key in ('notes','tasks','weather','feeds','containers','nas','remote'):
                self.toggle_card(key,True)
                self.cards[key].render()
            self.cancel()
            before=deepcopy(self.settings.data)
            self.open_settings('Refresh intervals')
            self.set_interval('cpu',17)
            self.save()
            if Settings(self.root).profile['refresh']['cpu']!=17: raise RuntimeError('Save did not persist interval')
            self.open_settings('Refresh intervals'); self.set_interval('cpu',19); self.cancel()
            if self.settings.profile['refresh']['cpu']!=17: raise RuntimeError('Cancel did not restore interval')
            self.settings.save(before); self.engine.configure(self.data)
            self.show_health()
            if not self.drawer.get_visible(): raise RuntimeError('Health panel is hidden')
            self.drawer.hide()
            validate(self.data)
            allocation=self.fixed.get_allocation()
            for card in self.cards.values():
                bounds=card.get_allocation()
                if bounds.width<1 or bounds.height<1: raise RuntimeError('A card has no size')
            atomic_json(self.root/'state/smoke-result.json',{'ok':True,'cards':list(self.cards),'canvas':[allocation.width,allocation.height]})
            GLib.timeout_add(500,self.capture_smoke)
        except Exception as exc:
            atomic_json(self.root/'state/smoke-result.json',{'ok':False,'error':str(exc)})
            self.quit()
        return False

    def capture_smoke(self):
        try:
            width,height=self.canvas_size
            for key,card in self.cards.items():
                allocation=card.get_allocation()
                if allocation.x<0 or allocation.y<0 or allocation.x+allocation.width>width+2 or allocation.y+allocation.height>height+2:
                    raise RuntimeError(f'{key} extends beyond the dashboard canvas: {allocation.x},{allocation.y} {allocation.width}x{allocation.height} in {width}x{height}')
        except Exception as exc:
            atomic_json(self.root/'state/smoke-result.json',{'ok':False,'error':str(exc)})
        if isinstance(self.window,Gtk.OffscreenWindow):
            pixbuf=self.window.get_pixbuf()
            if pixbuf: pixbuf.savev(str(self.root/'state/smoke.png'),'png',[],[])
        self.quit()
        return False

    def quit(self):
        if self.closing: return False
        self.closing=True
        if self.note_timer:
            GLib.source_remove(self.note_timer); self.save_note()
        self.window.hide()
        if hasattr(self,'engine'): self.engine.close()
        for child in self.children:
            try: os.killpg(child.pid,signal.SIGTERM)
            except ProcessLookupError: pass
        for child in self.children:
            try: child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try: os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError: pass
        if hasattr(self,'server'): self.server.close(); self.ipc_path.unlink(missing_ok=True)
        self.history.close()
        Gtk.main_quit()
        return False


def ipc(root,command):
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
            connection.settimeout(2); connection.connect(str(Path(root)/'state/native.sock'))
            connection.sendall(command.encode()); result=connection.recv(65536).decode().strip()
        if command=='quit':
            deadline=time.monotonic()+12
            while (Path(root)/'state/native.sock').exists() and time.monotonic()<deadline:
                time.sleep(.05)
        return result
    except OSError: return ''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--preview',action='store_true')
    parser.add_argument('--smoke',action='store_true')
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--size',default='1440x960',help='Preview/offscreen window size')
    parser.add_argument('--control',choices=['quit','status','reload','diagnostics'])
    args=parser.parse_args()
    if args.check:
        print('GTK 3 and GTK Layer Shell are available'); return 0
    if args.control:
        result=ipc(args.root,args.control)
        if result: print(result)
        return 0 if result else 1
    args.root.mkdir(parents=True,exist_ok=True)
    with (args.root/'.native.lock').open('w') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            ipc(args.root,'reload'); return 0
        try:
            size=tuple(int(value) for value in args.size.split('x'))
            if len(size)!=2 or min(size)<320: raise ValueError()
        except ValueError: parser.error('Use a preview size such as 1440x960, with both dimensions at least 320')
        app=Dashboard(args.root,args.preview,args.smoke,size)
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT,signal.SIGTERM,app.quit)
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT,signal.SIGINT,app.quit)
        Gtk.main()
        if args.smoke:
            return 0 if read_json(args.root/'state/smoke-result.json',{}).get('ok') else 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
