#!/usr/bin/env python3
"""PoeDash's editable GTK/Wayland desktop surface."""
import argparse
import calendar
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import datetime
import fcntl
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

from dashboard_model import (CARDS, REFRESH, SOURCES, SOURCE_TITLES,
    DEFAULT_APPEARANCE, Settings, Transaction, History, atomic_json, read_json,
    default_layout, valid_move, resolve_layout, insert_card, fit_layout_height, spaced, central_drop_target, measure_gaps, transform, validate)
from dashboard_collect import Engine, health_issues, search_weather_locations
from service_health import failed_units, service_details
from weather_visual import condition as weather_condition, icon_svg as weather_icon_svg

ROOT = Path(__file__).resolve().parent.parent
GRAPH_COLORS = ((.80,.69,.98),(.45,.82,.74),(.95,.69,.45))
METRIC_COLORS = dict(zip(('cpu','ram','temperature'),GRAPH_COLORS))
METRIC_COLORS.update(rx_bps=GRAPH_COLORS[0],tx_bps=GRAPH_COLORS[1],watts=GRAPH_COLORS[0])


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


def row(parent, name, value, style=''):
    line = box(False, 12)
    key, val = label(name, style or 'muted'), label(value, style)
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


def weather_icon(code,is_day=True,size=80):
    loader=GdkPixbuf.PixbufLoader.new_with_type('svg')
    loader.set_size(size,round(size*.75))
    loader.write(weather_icon_svg(code,is_day).encode()); loader.close()
    image=Gtk.Image.new_from_pixbuf(loader.get_pixbuf())
    image.get_accessible().set_name(weather_condition(code,is_day)[1])
    return image


class Artwork(Gtk.DrawingArea):
    def __init__(self, path, scale=1):
        super().__init__()
        self.pixbuf=GdkPixbuf.Pixbuf.new_from_file(path)
        self.set_hexpand(True); self.set_vexpand(True)
        self.set_size_request(-1,round(80*scale))
        self.get_accessible().set_name('Album artwork')
        self.connect('draw',self.draw_artwork)

    def draw_artwork(self, widget, cr):
        width,height=self.get_allocated_width(),self.get_allocated_height()
        art_width,art_height=self.pixbuf.get_width(),self.pixbuf.get_height()
        scale=min(width/art_width,height/art_height)
        cr.save()
        cr.translate((width-art_width*scale)/2,(height-art_height*scale)/2)
        cr.scale(scale,scale)
        Gdk.cairo_set_source_pixbuf(cr,self.pixbuf,0,0)
        cr.paint(); cr.restore()
        return False


class Waveform(Gtk.DrawingArea):
    """Draw audio levels directly; avoid per-frame SVG decoding and image layout."""
    def __init__(self):
        super().__init__()
        self.payload = {}
        self.set_size_request(-1, 36)
        self.connect('draw', self.draw_wave)
        self.get_accessible().set_name('Audio waveform')

    def set_frame(self, payload):
        self.payload = payload
        self.queue_draw()

    def draw_wave(self, widget, cr):
        values = self.payload.get('values', [])
        if not values: return False
        width, height = self.get_allocated_width(), self.get_allocated_height()
        cr.save()
        cr.scale(width / 320, height / 32)
        cr.set_source_rgba(.65, .62, .72, .18)
        cr.move_to(0, 30); cr.line_to(320, 30); cr.stroke()
        played = min(320, max(0, self.payload.get('progress', 100) * 3.2))
        cr.rectangle(0, 0, played, 32); cr.clip()
        import cairo
        palette = ((.984,.573,.235),(.937,.267,.267),(.659,.333,.969),(.231,.510,.965))
        for layer, (offset, gain, opacity) in enumerate(((0,.28,.65),(7,.22,.7),(15,.15,.85))):
            gradient = cairo.LinearGradient(0, 0, max(1, played), 0)
            for i, color in enumerate(palette): gradient.add_color_stop_rgba(i/3, *color, opacity)
            points = [(0,30)] + [(i*320/max(1,len(values)-1),30-max(0,min(100,values[(i+offset)%len(values)]))*gain) for i in range(len(values))] + [(320,30)]
            cr.move_to(*points[0])
            # Convert the SVG quadratic ridges to Cairo cubic curves.
            start = points[0]
            for i in range(1,len(points)-1):
                control = points[i]; after = points[i+1]
                end = ((control[0]+after[0])/2,(control[1]+after[1])/2)
                cr.curve_to(start[0]+2/3*(control[0]-start[0]),start[1]+2/3*(control[1]-start[1]),end[0]+2/3*(control[0]-end[0]),end[1]+2/3*(control[1]-end[1]),*end)
                start = end
            cr.line_to(320,30); cr.line_to(0,30); cr.close_path()
            cr.set_source(gradient); cr.fill()
        cr.restore()
        return False


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
        for index, (metric, _) in enumerate(self.metrics):
            points = self.app.history.series(metric, minutes, now)
            if not points: continue
            maximum = self.maximum or max(1, max(v for _,v in points)*1.15)
            cr.set_source_rgba(*METRIC_COLORS.get(metric,GRAPH_COLORS[index % len(GRAPH_COLORS)]), .95)
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
        if key=='player':
            self.player_controls=box(True,round(7*app.profile['appearance'].get('scale',1)))
            self.content.pack_end(self.player_controls,False,False,0)
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
        self.app.status.set_text('Drop inside a card’s highlighted centre to swap · keep the measured gaps')
        self.app.preview_layout=None
        self.drag_offset=(event.x,event.y)
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
            gap=appearance['spacing']*appearance.get('scale',1)
            rect, guides = transform(original, event.x_root-x, event.y_root-y, edge, width, height,
                                     appearance['grid_size'] if appearance['snap'] else 0, others,gap)
            self.drag_proposed=rect
            offset=getattr(self,'drag_offset',(original[2]*width/2,original[3]*height/2))
            self.app.drop_point=(original[0]+(offset[0]+event.x_root-x)/width,original[1]+(offset[1]+event.y_root-y)/height)
            plan=resolve_layout(self.key,rect,self.app.layout,edge,width,height,gap,allow_swap=False)
            hint=central_drop_target(self.key,rect,self.app.layout,self.app.drop_point) if not edge and plan is None else None
            self.app.swap_hint=hint
            self.app.preview_layout=plan
            self.app.preview=(self.key,plan[self.key] if plan else rect,plan is not None or hint is not None)
            self.app.guides=guides
            self.app.gap_guides=measure_gaps(self.key,plan[self.key] if plan else rect,plan or self.app.layout,width,height,max(120,gap*4))
            for key,position in (plan or self.app.layout).items(): self.app.place_card(key,position)
            if plan is None:
                self.app.place_card(self.key,rect)
                self.app.status.set_text('Release inside the highlighted centre to swap' if hint else 'Keep the configured gap · release here to restore the card')
            else:
                count=sum(plan[key]!=self.app.layout[key] for key in plan if key!=self.key)
                self.app.status.set_text(('Release to adjust '+str(count)+' neighbouring card(s)') if count else 'Release to place card')
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
        plan=getattr(self.app,'preview_layout',None)
        if not self.drag[3] and hasattr(self,'drag_proposed'):
            appearance=self.app.profile['appearance']
            if event is not None and hasattr(event,'x_root'):
                x,y,original,_=self.drag;width,height=self.app.canvas_size
                offset=getattr(self,'drag_offset',(original[2]*width/2,original[3]*height/2))
                self.app.drop_point=(original[0]+(offset[0]+event.x_root-x)/width,original[1]+(offset[1]+event.y_root-y)/height)
            plan=resolve_layout(self.key,self.drag_proposed,self.app.layout,'',*self.app.canvas_size,
                                appearance['spacing']*appearance.get('scale',1),allow_swap=True,drop_point=getattr(self.app,'drop_point',None))
        if plan is not None:
            self.app.transaction.checkpoint()
            self.app.layout=deepcopy(plan)
            self.app.store_layout()
            self.app.status.set_text('Layout changed · Save to keep it, or Cancel to restore')
        else:
            self.app.status.set_text('Position restored · cards keep their usable minimum size')
        for key,rect in self.app.layout.items(): self.app.place_card(key,rect)
        self.app.preview_layout=None
        self.app.swap_hint=None;self.app.gap_guides=[]
        if hasattr(self,'drag_proposed'): del self.drag_proposed
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
            legend=box(False,round(8*self.app.profile['appearance'].get('scale',1)))
            for metric,name in metrics:
                item=label(name,'freshness'); item.get_style_context().add_class('metric-'+metric)
                legend.pack_start(item,True,True,0)
            legend.pack_end(label(f"{self.app.profile['appearance']['history_minutes']} min",'freshness'),False,False,0)
            self.body.pack_start(legend,False,False,0)

    def render(self):
        # Keep the pressed widget alive until GTK delivers the release. A
        # collector can finish between mouse-down and mouse-up (or mid-seek).
        if self.get_realized():
            seat = self.get_display().get_default_seat()
            pointer = seat.get_pointer() if seat else None
            focus = self.app.window.get_focus()
            pressed = pointer and self.get_window().get_device_position(pointer).mask & Gdk.ModifierType.BUTTON1_MASK
            active = focus and focus.is_ancestor(self) and focus.get_state_flags() & Gtk.StateFlags.ACTIVE
            if pressed or active:
                if not getattr(self, 'render_pending', None):
                    self.render_pending = GLib.timeout_add(100, self.retry_render)
                return
        if getattr(self, 'render_pending', None):
            GLib.source_remove(self.render_pending)
            self.render_pending = None
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
                                ('Packages',self.value('packages','—'))]: row(self.body,name,value)
            updates=self.value('updates','—')
            update_value=row(self.body,'Updates',updates)
            try: count=int(str(updates).strip())
            except ValueError: count=-1
            error=self.app.samples.get('updates',{}).get('error')
            if error: count=-1
            state='unknown' if count<0 else 'current' if count==0 else 'critical' if count>50 else 'pending'
            update_value.get_style_context().add_class('updates-'+state)
            update_value.set_tooltip_text(error or ('Update count unavailable' if count<0 else 'Up to date' if count==0 else f"{count} update{'s' if count!=1 else ''} available"))
        elif key == 'system':
            data = self.value('system_info',{})
            for name, field in [('OS','os'),('CPU','cpu'),('GPU','gpu'),('Memory','memory'),('Home disk','disk')]:
                line=box(False,10)
                key_label=label(name.upper(),'freshness'); key_label.set_size_request(76,-1)
                line.pack_start(key_label,False,False,0)
                value=label(data.get(field,'—'),wrap=True); value.set_selectable(True)
                line.pack_start(value,True,True,0); self.body.pack_start(line,False,False,0)
            detail = self.details('Storage and service health')
            contents = box()
            for disk in self.value('health',{}).get('disks',[]): row(contents,disk['path'],f"{disk['free_gib']} GiB free · {disk['percent']}% used")
            for unit in failed_units(self.value('health',{}).get('failed',[])):
                contents.pack_start(button(f"Failed {unit['scope']} unit: {unit['unit']}",
                    lambda unit=unit:self.app.show_service_details(unit['unit'],unit['scope']),
                    'Show this unit’s status and recent logs'),False,False,0)
            contents.pack_start(button('Open system monitor',lambda: self.app.run('launch.sh','system')),False,False,0)
            detail.add(contents); self.body.pack_start(detail,False,False,0)
        elif key == 'performance':
            gpu = self.value('gpu',{})
            for name,value,display,metric in [('CPU',self.value('cpu',0),str(self.value('cpu','—'))+'%','cpu'),
                                       ('GPU',gpu.get('usage',0),gpu.get('label','—'),None),
                                       ('RAM',self.value('ram',0),str(self.value('ram','—'))+'%','ram')]:
                style='metric-'+metric if metric else ''
                line = box(False,8); line.pack_start(label(name,style),False,False,0)
                meter = Gtk.ProgressBar(); meter.set_fraction(max(0,min(1,float(value or 0)/100)))
                if style: meter.get_style_context().add_class(style)
                line.pack_start(meter,True,True,0); line.pack_end(label(display,style),False,False,0)
                self.body.pack_start(line,False,False,0)
            temperature = self.value('cpu_temperature','--')
            row(self.body,'CPU temperature', temperature if temperature != '--' else 'Sensor unavailable','metric-temperature')
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
                               ('Tailscale',vpn.get('tailscale_state','—')),('Proton VPN',vpn.get('proton_state','—'))]: row(self.body,name,value)
            row(self.body,'Download',rate(network.get('rx_bps')),'metric-rx_bps')
            row(self.body,'Upload',rate(network.get('tx_bps')),'metric-tx_bps')
            self.chart([('rx_bps','Download'),('tx_bps','Upload')])
            details=self.details('Interface, Tailscale IP and routes')
            details.set_label_widget(label('Interface, Tailscale IP and routes'))
            details.set_tooltip_text('Interface, Tailscale IP and routes')
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
                choices = Gtk.FlowBox()
                choices.set_selection_mode(Gtk.SelectionMode.NONE)
                choices.set_homogeneous(True)
                choices.set_min_children_per_line(1); choices.set_max_children_per_line(3)
                choices.set_column_spacing(4); choices.set_row_spacing(4)
                for name in profile.get('available',[]):
                    if isinstance(name,str): choices.add(button(name,lambda n=name: self.app.run('power-control.py','set',n)))
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
            today=datetime.date.today()
            self.calendar_date=today
            selected=self.app.calendar_selection or today
            month_title=label(today.strftime('%B %Y'),'heading')
            month_title.set_xalign(.5)
            self.body.pack_start(month_title,False,False,0)
            month=Gtk.Grid()
            month.set_column_homogeneous(True); month.set_row_homogeneous(True)
            month.set_hexpand(True)
            month.set_column_spacing(round(4*self.app.profile['appearance'].get('scale',1)))
            month.set_row_spacing(round(4*self.app.profile['appearance'].get('scale',1)))
            for column,name in enumerate(calendar.day_abbr):
                weekday=label(name,'muted'); weekday.set_xalign(.5)
                weekday.set_hexpand(True)
                month.attach(weekday,column,0,1,1)
            for week,days in enumerate(calendar.Calendar(firstweekday=calendar.MONDAY).monthdayscalendar(today.year,today.month),1):
                for column,day in enumerate(days):
                    date=today.replace(day=day) if day else None
                    cell=button(str(day),lambda date=date:self.app.select_calendar_date(date)) if day else label('')
                    cell.get_style_context().add_class('calendar-day')
                    cell.set_hexpand(True)
                    if date:
                        description=date.strftime('%A %d %B %Y')
                        if date==today:
                            cell.get_style_context().add_class('calendar-today')
                            description='Today · '+description
                        if date==selected: cell.get_style_context().add_class('calendar-selected')
                        cell.set_tooltip_text(description)
                        cell.get_accessible().set_name(description)
                    month.attach(cell,column,week,1,1)
            self.body.pack_start(month,False,False,0)
            data=self.app.calendar_day_data if self.app.calendar_selection else self.value('calendar',{})
            self.text(selected.strftime('%a %d %b %Y') if self.app.calendar_selection else 'UPCOMING · NEXT 14 DAYS','freshness',False)
            self.text(data.get('status','Reading Thunderbird calendars'),'muted')
            for event in data.get('events',[]):
                self.text(event.get('when',''),'freshness',False)
                self.text(event.get('title','Untitled event'))
            self.body.pack_start(button('Open Thunderbird Calendar',lambda: self.app.run('desktop.py','calendar')),False,False,0)
        elif key == 'player':
            clear(self.player_controls)
            data=self.value('media',{})
            art=data.get('art','')
            if art and Path(art).is_file():
                try:
                    image=Artwork(art,self.app.profile['appearance'].get('scale',1))
                    self.body.pack_start(image,True,True,0)
                except GLib.Error: pass
            self.text(data.get('title','Nothing playing'),'media-title')
            self.text(data.get('artist') or data.get('player',''),'muted')
            self.wave_image=Waveform(); self.player_controls.pack_start(self.wave_image,False,False,0)
            self.update_wave()
            seek=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0,100,1)
            seek.set_draw_value(False); seek.set_value(float(data.get('progress',0)))
            seek.set_sensitive(bool(data.get('available') and data.get('length','0:00') != '0:00'))
            seek.connect('button-release-event',lambda widget,event: self.app.seek(widget.get_value()))
            self.player_controls.pack_start(seek,False,False,0)
            self.player_controls.pack_start(label(f"{data.get('position','0:00')} / {data.get('length','0:00')}",'freshness'),False,False,0)
            controls=box(False,7)
            for text,action in [('⏮','previous'),('⏸' if data.get('status')=='Playing' else '▶','play-pause'),('⏭','next'),('Open','open')]:
                controls.pack_start(button(text,lambda a=action: self.app.run('media-control.sh',a)),True,True,0)
            self.player_controls.pack_start(controls,False,False,0)
            self.player_controls.show_all()
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
                location=self.app.data['integrations']['weather'].get('location','')
                if location: self.text(location,'muted')
                current=data.get('current',{})
                code=current.get('weather_code');day=bool(current.get('is_day',1))
                kind,description,_=weather_condition(code,day)
                zoom=self.app.profile['appearance'].get('scale',1)
                hero=box(False,8);hero.get_style_context().add_class('weather-hero')
                hero.get_style_context().add_class('weather-'+kind)
                if not day: hero.get_style_context().add_class('weather-night')
                hero.pack_start(weather_icon(code,day,round(100*zoom)),False,False,0)
                summary=box(True,2)
                temperature=label(str(current.get('temperature_2m','—'))+'°','weather-temperature')
                summary.pack_start(temperature,False,False,0)
                summary.pack_start(label(description,'muted',True),False,False,0)
                summary.pack_start(label('Feels like '+str(current.get('apparent_temperature','—'))+' °C','freshness'),False,False,0)
                hero.pack_start(summary,True,True,0);self.body.pack_start(hero,False,False,0)
                for name,field,unit in [('Humidity','relative_humidity_2m','%'),('Wind','wind_speed_10m','km/h')]: row(self.body,name,str(current.get(field,'—'))+' '+unit)
                daily=data.get('daily',{})
                forecast=box(False,6);forecast.set_homogeneous(True)
                def value(field,index):
                    values=daily.get(field,[])
                    return values[index] if index<len(values) and values[index] is not None else '—'
                for i,date in enumerate(daily.get('time',[])[:3]):
                    tile=box(True,3);tile.get_style_context().add_class('weather-forecast')
                    try:
                        parsed=datetime.date.fromisoformat(date)
                        title='Today' if parsed==datetime.date.today() else parsed.strftime('%a')
                    except (TypeError,ValueError):title=str(date)
                    title_label=label(title,'freshness');title_label.set_xalign(.5);tile.pack_start(title_label,False,False,0)
                    tile.pack_start(weather_icon(value('weather_code',i),True,round(42*zoom)),False,False,0)
                    for text,style in [(str(value('temperature_2m_max',i))+'°','weather-high'),(str(value('temperature_2m_min',i))+'°','freshness'),(str(value('precipitation_probability_max',i))+'% precip.','freshness')]:
                        item=label(text,style);item.set_xalign(.5);tile.pack_start(item,False,False,0)
                    forecast.pack_start(tile,True,True,0)
                self.body.pack_start(forecast,False,False,0)
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

    def retry_render(self):
        self.render_pending = None
        if not self.app.closing and self.app.cards.get(self.key) is self:
            self.render()
        return False

    def details(self, title):
        # Refresh the readings without collapsing the section under the user.
        if not hasattr(self, 'expanded_details'): self.expanded_details = {}
        widget = Gtk.Expander(label=title)
        widget.set_expanded(self.expanded_details.get(title, False))
        widget.connect('notify::expanded', lambda item, *_: self.expanded_details.update({title: item.get_expanded()}))
        return widget

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
        self.wave_image.set_frame(self.app.wave)

    def update_freshness(self):
        sources=SOURCES.get(self.key,())
        samples=[(source,self.app.samples.get(source,{})) for source in sources]
        icon='↻'; warning=False
        self.refresh_button.set_sensitive(bool(sources))
        if not sources:
            message='Saved locally'
        elif self.app.paused:
            message='Paused on battery · dashboard hidden'; icon='⏸'
        else:
            errors=[sample.get('error') for _,sample in samples if sample.get('error')]
            updated=[sample.get('updated',0) for _,sample in samples]
            if errors: message=errors[0]; warning=True
            elif not updated or not min(updated): message='Collecting…'
            else:
                stamp=datetime.datetime.fromtimestamp(max(updated))
                message=stamp.strftime('Last updated: %a %d %b %H:%M:%S')
                stale=any(time.time()-sample.get('updated',0)>max(15,3*self.app.profile['refresh'].get(source,REFRESH[source])) for source,sample in samples)
                if stale: message+=' · some readings are stale'; warning=True
        self.refresh_button.set_label('⚠' if warning else icon)
        style=self.refresh_button.get_style_context()
        if warning: style.add_class('warning')
        else: style.remove_class('warning')
        self.refresh_button.set_tooltip_text(message+('\nRefresh this card now' if sources else ''))


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
        self.calendar_selection=None
        self.calendar_day_data={}
        self.calendar_generation=0
        self.calendar_future=None
        self.calendar_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='poedash-calendar')
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
        if visual:self.window.set_visual(visual)
        self.window.connect('destroy',lambda *_:self.quit())
        self.window.connect('key-press-event',self.key_press)
        self.choose_monitor()
        if not preview and GtkLayerShell.is_supported():
            GtkLayerShell.init_for_window(self.window)
            GtkLayerShell.set_namespace(self.window,'poedash')
            GtkLayerShell.set_layer(self.window,GtkLayerShell.Layer.BOTTOM)
            GtkLayerShell.set_keyboard_mode(self.window,GtkLayerShell.KeyboardMode.ON_DEMAND)
            GtkLayerShell.set_monitor(self.window,self.monitor)
            # Respect panel reservations so the header sits below the status
            # bar's input region and its controls receive pointer events.
            GtkLayerShell.set_exclusive_zone(self.window,0)
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
        self.header.get_style_context().add_class('dashboard-header')
        titlebox=box(True,2)
        self.hostname=label(socket.gethostname(),'hostname'); titlebox.pack_start(self.hostname,False,False,0)
        titlebox.pack_start(label(read_json(self.root/'settings.json',{}).get('name','PoeDash'),'muted'),False,False,0)
        self.header.pack_start(titlebox,True,True,0)
        self.header_controls=box(False,8)
        self.header_controls.set_valign(Gtk.Align.CENTER)
        self.header_controls.get_style_context().add_class('header-controls')
        self.header.pack_start(self.header_controls,False,False,0)
        self.profile_combo=Gtk.ComboBoxText(); self.profile_combo.connect('changed',self.profile_changed)
        self.header_controls.pack_start(self.profile_combo,False,False,0)
        zoom_controls=box(False,3)
        zoom_controls.pack_start(button('−',lambda:self.change_zoom(-.05),'Zoom out'),False,False,0)
        self.zoom_label=label('100%'); zoom_controls.pack_start(self.zoom_label,False,False,0)
        zoom_controls.pack_start(button('+',lambda:self.change_zoom(.05),'Zoom in'),False,False,0)
        zoom_controls.pack_start(button('↶',lambda:self.change_zoom(reset=True),'Reset dashboard zoom to 100%'),False,False,0)
        self.header_controls.pack_start(zoom_controls,False,False,0)
        self.header_controls.pack_start(button('Packages',lambda: self.run('packages.py','launch')),False,False,0)
        self.edit_button=button('Edit',self.edit_menu)
        self.header_controls.pack_start(self.edit_button,False,False,0)
        self.clock=label(datetime.datetime.now().strftime('%H:%M\n%a %d %b'),'clock'); self.header.pack_end(self.clock,False,False,0)
        self.surface.pack_start(self.header,False,False,0)
        self.healthbar=box(False,6)
        self.health_label=label('Checking system health…','muted')
        self.health_summary=Gtk.Button()
        self.health_summary.set_relief(Gtk.ReliefStyle.NONE)
        self.health_summary.set_tooltip_text('Open the reported health issue')
        self.health_summary.add(self.health_label)
        self.health_summary.connect('clicked',lambda *_:self.open_health_summary())
        self.healthbar.pack_start(self.health_summary,True,True,0)
        self.health_button=button('Details',self.show_health)
        self.healthbar.pack_end(self.health_button,False,False,0)
        # Editing replaces the health strip instead of adding a row. Both
        # pages remain measured so switching modes cannot resize the canvas.
        self.control_stack=Gtk.Stack()
        self.control_stack.set_hhomogeneous(False)
        self.control_stack.set_vhomogeneous(True)
        self.control_stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.control_stack.add_named(self.healthbar,'health')
        self.surface.pack_start(self.control_stack,False,False,0)
        self.toolbar=box(False,6)
        for text,callback in [('Save',self.save),('Cancel',self.cancel),('Undo',self.undo),('Redo',self.redo),('Reset layout',self.reset_layout)]:
            control=button(text,callback); self.toolbar.pack_start(control,False,False,0)
            if text=='Undo': self.undo_button=control
            if text=='Redo': self.redo_button=control
        self.snap_check=Gtk.CheckButton.new_with_label('Snap & guides')
        self.snap_check.connect('toggled',self.snap_changed)
        self.toolbar.pack_end(self.snap_check,False,False,0)
        self.control_stack.add_named(self.toolbar,'editing')
        self.control_stack.set_visible_child(self.healthbar)
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
        self.board_view.get_child().connect('size-allocate',self.schedule_allocate)
        self.main.pack_start(self.board_view,True,True,0)
        self.surface.pack_start(self.main,True,True,0)
        # An empty status line reserves the same height as a populated one.
        self.status=label('','freshness')
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
        self.control_stack.set_visible_child(self.healthbar); self.drawer.hide()
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
        viewport=self.board_view.get_child()
        self.allocate(viewport,viewport.get_allocation())
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
        recent_text=appearance['recent_text_size']
        recent_icon=appearance['recent_icon_size']
        text=''
        try: text=(self.root/'colors.scss').read_text()
        except OSError: pass
        colors={name:value for name,value in re.findall(r'\$(\w+):\s*(#[0-9a-fA-F]{6})',text)}
        colors={**{'accent':'#d3bbfc','background':'#0f0d13','card':'#1d1b20','foreground':'#e7e0e8','muted':'#948f99','border':'#49454e'},**colors}
        metric_css='\n'.join(
            f".metric-{metric} {{ color: rgb({','.join(str(round(c*255)) for c in color)}); }}\n"
            f"progressbar.metric-{metric} progress {{ background: rgb({','.join(str(round(c*255)) for c in color)}); }}"
            for metric,color in METRIC_COLORS.items())
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
        .dashboard-header * {{ font-size: {appearance['font_size']}px; }}
        .hostname, .clock {{ font-size: {appearance['font_size']+12}px; font-weight: bold; }}
        .media-title {{ font-size: {round((appearance['font_size']+5)*zoom)}px; font-weight: bold; }}
        .muted, .freshness {{ color: {colors['muted']}; }}
        .freshness {{ font-size: {max(8,round((appearance['font_size']-3)*zoom))}px; }}
        .rail .app-name {{ font-size: {round(recent_text*zoom)}px; }}
        .rail .freshness {{ font-size: {max(8,round((recent_text-3)*zoom))}px; }}
        .calendar-day {{ min-height: {round(24*zoom)}px; padding: {max(1,round(2*zoom))}px 0; }}
        button.calendar-day {{ background: transparent; border-color: transparent; box-shadow: none; text-shadow: none; }}
        button.calendar-day:hover {{ background: {rgba('accent',.10)}; border-color: transparent; }}
        button.calendar-day.calendar-selected {{ box-shadow: inset 0 0 0 2px {colors['accent']}; border-radius: {round(6*zoom)}px; }}
        button.calendar-day.calendar-today {{ color: {colors['background']}; background: {colors['accent']}; border-radius: {round(6*zoom)}px; font-weight: bold; }}
        .weather-hero {{ border-radius: 10px; padding: {round(10*zoom)}px; background: linear-gradient(135deg,rgba(96,165,250,.16),rgba(96,165,250,.03)); }}
        .weather-clear, .weather-partly {{ background: linear-gradient(135deg,rgba(251,191,36,.20),rgba(249,115,22,.04)); }}
        .weather-night {{ background: linear-gradient(135deg,rgba(129,140,248,.22),rgba(30,41,59,.10)); }}
        .weather-storm {{ background: linear-gradient(135deg,rgba(192,132,252,.22),rgba(96,165,250,.04)); }}
        .weather-snow {{ background: linear-gradient(135deg,rgba(165,227,243,.20),rgba(96,165,250,.03)); }}
        .weather-temperature {{ font-size: {round(34*zoom)}px; font-weight: bold; }}
        .weather-high {{ color: #fbbf24; font-weight: bold; }}
        .weather-forecast {{ border-radius: 8px; padding: {round(7*zoom)}px {round(3*zoom)}px; background: rgba(148,163,184,.07); }}
        .warning {{ color: #f3a580; }}
        .updates-current {{ color: #8dd5a0; font-weight: bold; }}
        .updates-pending {{ color: #e6a85c; font-weight: bold; }}
        .updates-critical {{ color: #ff5c68; font-weight: bold; }}
        .updates-unknown {{ color: {colors['muted']}; }}
        button, combobox, entry, spinbutton {{ color: {colors['foreground']}; background: {rgba('card',.95)}; border: 1px solid {colors['border']}; border-radius: 6px; padding: {max(2,round(4*zoom))}px {max(3,round(7*zoom))}px; }}
        .header-controls button {{ min-height: 20px; min-width: 16px; padding: 2px 6px; }}
        .header-controls combobox {{ min-height: 0; padding: 0; border: 0; background: transparent; box-shadow: none; }}
        button:hover {{ border-color: {colors['accent']}; }}
        button:disabled {{ opacity: .45; }}
        textview, textview text {{ color: {colors['foreground']}; background: transparent; }}
        progressbar trough {{ min-height: 6px; background: {colors['border']}; }}
        progressbar progress {{ min-height: 6px; background: {colors['accent']}; }}
        {metric_css}
        .drawer {{ background: {colors['background']}; border: 1px solid {colors['accent']}; border-radius: 10px; }}
        popover, menu {{ background: {colors['background']}; color: {colors['foreground']}; }}
        scrollbar slider {{ min-width: 5px; min-height: 20px; background: {colors['border']}; border-radius: 3px; }}
        '''
        self.provider.load_from_data(css.encode())
        self.surface.set_spacing(round(appearance['spacing']*zoom))
        self.main.set_spacing(round(appearance['spacing']*zoom)) if hasattr(self,'main') else None
        if hasattr(self,'rail'):
            self.rail.set_size_request(round(max(94,recent_icon+36,recent_text*4.4+28)*zoom),-1)
        if hasattr(self,'zoom_label'): self.zoom_label.set_text(f'{round(zoom*100)}%')
        self.theme=colors
        if getattr(self,'app_lists',None): self.receive_apps(self.app_lists)
        if hasattr(self,'cards'):
            for card in self.cards.values(): card.queue_draw()

    def build_cards(self):
        saved=self.profile['layouts'].get(self.display_key)
        if saved is not None and any(key not in saved for key in self.profile['visible']):
            width,height=self.profile.get('layout_sizes',{}).get(self.display_key,self.canvas_size)
            original_height=height
            plan={key:deepcopy(saved[key]) for key in self.profile['visible'] if key in saved}
            for key in self.profile['visible']:
                if key not in plan:
                    candidate,_=insert_card(key,plan,width,height,self.profile['appearance']['spacing']*self.profile['appearance'].get('scale',1))
                    if candidate is None:
                        plan=default_layout(self.profile['visible'],width,height,self.profile['appearance']['spacing'],self.data['active_profile']);break
                    plan=candidate
            if height!=original_height:
                for rect in saved.values():rect[1]*=original_height/height;rect[3]*=original_height/height
            saved.update(plan)
            self.profile.setdefault('layout_sizes',{})[self.display_key]=[width,height]
        for child in self.fixed.get_children(): self.fixed.remove(child)
        self.cards={}
        self.layout={}
        for key in self.profile['visible']:
            card=Card(self,key)
            self.cards[key]=card
            self.fixed.put(card,0,0)
            card.show_all(); card.set_editing(self.editing)
        self.reflow()

    def layout_for_size(self,width,height):
        zoom=self.profile['appearance'].get('scale',1)
        logical_width,logical_height=width/zoom,height/zoom
        saved=self.profile['layouts'].get(self.display_key,{})
        # Existing user geometry always wins; add/hide does not reset other cards.
        if set(self.cards).issubset(saved): layout={key:deepcopy(saved[key]) for key in self.cards}
        else:
            layout=default_layout(list(self.cards),logical_width,logical_height,self.profile['appearance']['spacing'],self.data['active_profile'])
            if logical_width>=850 and all(key in layout for key in ('performance','processes','shares')):
                # Shares take space from the scrolling process list as mount text grows.
                shares=self.samples.get('shares',{}).get('value') or []
                share_rect=layout['shares']; process_rect=layout['processes']
                if abs(share_rect[0]-process_rect[0])<.001:
                    appearance=self.profile['appearance']; font=appearance['font_size']*zoom
                    chars=max(12,int((share_rect[2]*width-32)/(font*.65)))
                    lines=sum(3+math.ceil((len(s.get('source',''))+len(s.get('target','')))/chars) for s in shares if isinstance(s,dict))
                    desired=max(share_rect[3]*height,85*zoom+lines*(font*1.5+5*zoom))
                    extra=min(max(0,desired-share_rect[3]*height),max(0,process_rect[3]*height-140*zoom))
                    process_rect[3]-=extra/height
                    share_rect[1]-=extra/height; share_rect[3]+=extra/height
        minima={key:card.content.get_preferred_height()[0]+2 for key,card in self.cards.items()}
        reference_height=self.profile.get('layout_sizes',{}).get(self.display_key,[width,height])[1] if set(self.cards).issubset(saved) else height
        fitted,_=fit_layout_height(layout,width,reference_height,height,self.profile['appearance']['spacing']*zoom,minima)
        if fitted is not None:layout=fitted
        return layout

    def reflow(self):
        width,height=self.canvas_size
        if width<2 or height<2: return
        self.layout=self.layout_for_size(width,height)
        for key,rect in self.layout.items(): self.place_card(key,rect)
        self.guide_layer.queue_draw()

    def schedule_allocate(self,*_):
        # Resize children after GTK finishes allocating the viewport; changing
        # their requests inside that allocation can leave stale card bounds.
        if not getattr(self,'allocate_idle',None):
            self.allocate_idle=GLib.idle_add(self.allocate_viewport)

    def allocate_viewport(self):
        self.allocate_idle=None
        if self.closing: return False
        viewport=self.board_view.get_child()
        self.allocate(viewport,viewport.get_allocation())
        return False

    def allocate(self,widget,allocation):
        if allocation.width<2 or allocation.height<2:return
        width=max(1,allocation.width-8)
        # Use the actual visible viewport, including at non-default zoom levels.
        height=max(1,self.board_view.get_allocated_height()-4)
        size=(width,height)
        plan=self.layout_for_size(width,height)
        if size!=self.canvas_size or plan!=self.layout:
            self.canvas_size=size
            self.board.set_size_request(width,height);self.fixed.set_size_request(width,height)
            self.layout=plan
            for key,rect in plan.items():self.place_card(key,rect)
            self.guide_layer.queue_draw()

    def place_card(self,key,rect):
        if key not in self.cards: return
        width,height=self.canvas_size
        x,y,w,h=rect
        card=self.cards[key]
        card.set_size_request(max(1,round(w*width)),max(1,round(h*height)))
        self.fixed.move(card,round(x*width),round(y*height))

    def store_layout(self):
        saved=self.profile['layouts'].setdefault(self.display_key,{})
        saved.update(deepcopy(self.layout))
        self.profile.setdefault('layout_sizes',{})[self.display_key]=list(self.canvas_size)

    def draw_guides(self,widget,cr):
        if not self.editing: return False
        width,height=self.canvas_size
        cr.set_source_rgba(.45,.9,.75,.9); cr.set_line_width(1)
        for axis,pos in self.guides:
            cr.move_to(pos,0) if axis=='x' else cr.move_to(0,pos)
            cr.line_to(pos,height) if axis=='x' else cr.line_to(width,pos)
        cr.stroke()
        zoom=self.profile['appearance'].get('scale',1)
        gap=self.profile['appearance']['spacing']
        cr.set_font_size(11)
        for x1,y1,x2,y2,distance in getattr(self,'gap_guides',[]):
            matched=abs(distance/zoom-gap)<=1
            cr.set_source_rgba(*((.45,.9,.75,.95) if matched else (1,.75,.35,.95)))
            cr.move_to(x1,y1);cr.line_to(x2,y2)
            if abs(y1-y2)<1:
                for x in (x1,x2):cr.move_to(x,y1-4);cr.line_to(x,y1+4)
            else:
                for y in (y1,y2):cr.move_to(x1-4,y);cr.line_to(x1+4,y)
            cr.stroke()
            cr.move_to((x1+x2)/2+5,(y1+y2)/2-5);cr.show_text(f'{distance/zoom:.0f} px')
        hint=getattr(self,'swap_hint',None)
        if hint in self.layout:
            x,y,w,h=self.layout[hint];x=(x+.175*w)*width;y=(y+.175*h)*height;w*=.65*width;h*=.65*height
            cr.set_source_rgba(1,.75,.35,.13);cr.rectangle(x,y,w,h);cr.fill_preserve()
            cr.set_source_rgba(1,.75,.35,.9);cr.stroke()
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
        for text,callback in [('Move & resize cards',self.edit_layout),('Fit cards to screen',self.fit_cards_to_screen),('Refresh intervals',lambda:self.open_settings('Refresh intervals')),
                              ('Appearance',lambda:self.open_settings('Appearance')),('Add / hide cards',lambda:self.open_settings('Cards')),
                              ('Profiles',lambda:self.open_settings('Profiles'))]:
            control=button(text,callback)
            self.edit_actions[text]=control
            content.pack_start(control,False,False,0)
        reveal(self.drawer)

    def edit_layout(self):
        self.begin(); self.drawer.hide()
        self.editing=True
        self.control_stack.set_visible_child(self.toolbar); self.status.show()
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
            viewport=self.board_view.get_child()
            self.allocate(viewport,viewport.get_allocation())
            self.update_edit_buttons()
            self.snap_check.set_active(self.profile['appearance']['snap'])

    def redo(self):
        if self.transaction and self.transaction.redo():
            self.apply_appearance(); self.build_cards()
            viewport=self.board_view.get_child()
            self.allocate(viewport,viewport.get_allocation())
            self.update_edit_buttons()
            self.snap_check.set_active(self.profile['appearance']['snap'])

    def reset_layout(self):
        if not self.transaction: return
        self.transaction.checkpoint()
        self.profile['layouts'].pop(self.display_key,None)
        self.profile.get('layout_sizes',{}).pop(self.display_key,None)
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
        self.swap_hint=None;self.gap_guides=[]
        self.control_stack.set_visible_child(self.healthbar); self.drawer.hide()
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
        self.drawer_generation=getattr(self,'drawer_generation',0)+1
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
        self.editing=False; self.control_stack.set_visible_child(self.healthbar)
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
                                       ('Recent Apps text size','recent_text_size',9,24,1),
                                       ('Recent Apps icon size','recent_icon_size',16,80,1),
                                       ('Card spacing','spacing',4,24,1),('Snap sensitivity','grid_size',4,40,1)]:
            line=box(False,8); line.pack_start(label(title),True,True,0)
            spin=Gtk.SpinButton.new_with_range(low,high,step); spin.set_digits(2 if key=='opacity' else 0); spin.set_value(appearance[key])
            spin.get_accessible().set_name(title)
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

    def weather_location_settings(self,parent,cfg):
        parent.pack_start(label('WEATHER LOCATION','heading'),False,False,0)
        selected=label(cfg.get('location') or ('Existing saved location' if cfg.get('latitude','')!='' else 'No location selected'),'muted',True)
        parent.pack_start(selected,False,False,0)
        line=box(False,6)
        entry=Gtk.Entry(); entry.set_placeholder_text('Town or city, e.g. Cambridge, United Kingdom')
        line.pack_start(entry,True,True,0)
        results=box(True,4)
        status=label('Search, then choose a matching place. Save to keep your choice.','muted',True)
        transaction=self.transaction; generation=self.drawer_generation
        request_version=[0]
        def choose(location):
            cfg.update(location); selected.set_text(location['location'])
            clear(results); status.set_text('Location selected. Save to apply.')
        def search():
            query=entry.get_text().strip()
            if len(query)<2:
                status.set_text('Enter at least two characters.'); return
            request_version[0]+=1; request=request_version[0]
            search_button.set_sensitive(False); clear(results); status.set_text('Searching…')
            def lookup():
                try: return search_weather_locations(query),''
                except Exception: return [],'Search unavailable. Check your connection and try again.'
            def deliver(value):
                if self.closing or self.transaction is not transaction or self.drawer_generation!=generation or request_version[0]!=request: return False
                search_button.set_sensitive(True)
                if entry.get_text().strip()!=query:
                    status.set_text('Search again for the edited name.'); return False
                locations,error=value
                status.set_text(error or ('Choose a place:' if locations else 'No matching places. Try a nearby city or add the country.'))
                for location in locations:
                    results.pack_start(button(location['location'],lambda location=location:choose(location)),False,False,0)
                results.show_all(); return False
            future=self.calendar_pool.submit(lookup)
            future.add_done_callback(lambda result: None if result.cancelled() else GLib.idle_add(deliver,result.result()))
        search_button=button('Search',search)
        line.pack_end(search_button,False,False,0)
        entry.connect('activate',lambda *_: search_button.clicked() if search_button.get_sensitive() else None)
        parent.pack_start(line,False,False,0)
        parent.pack_start(status,False,False,0)
        parent.pack_start(results,False,False,0)
        def remove():
            request_version[0]+=1; search_button.set_sensitive(True)
            cfg.update(location='',latitude='',longitude=''); selected.set_text('No location selected'); clear(results)
            status.set_text('Location cleared. Save to apply.')
        parent.pack_start(button('Clear weather location',remove),False,False,0)

    def card_settings(self,parent):
        parent.pack_start(label('Choose cards for this profile. New cards use free space first. If the dashboard is full, the cards in a column share the space. Hidden cards remember their slot.',wrap=True),False,False,0)
        for key,(title,description) in CARDS.items():
            check=Gtk.CheckButton.new_with_label(title); check.set_active(key in self.profile['visible'])
            check.set_tooltip_text(description)
            def toggle(widget,k=key):
                if self.toggle_card(k,widget.get_active()) is False:widget.set_active(k in self.profile['visible'])
            check.connect('toggled',toggle)
            parent.pack_start(check,False,False,0)
        parent.pack_start(Gtk.Separator(),False,False,4)
        parent.pack_start(label('INTEGRATIONS','heading'),False,False,0)
        parent.pack_start(label('Optional cards make requests only when enabled and configured. Notes and tasks stay local.',wrap=True),False,False,0)
        integrations=self.data['integrations']
        self.weather_location_settings(parent,integrations['weather'])
        fields=[('RSS / Atom URLs (one per line)','feeds','urls',False),
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

    def fit_cards_to_screen(self):
        self.begin()
        width,oldheight=self.canvas_size
        height=max(1,self.board_view.get_allocated_height()-4)
        gap=self.profile['appearance']['spacing']*self.profile['appearance'].get('scale',1)
        minima={key:card.content.get_preferred_height()[0]+2 for key,card in self.cards.items()}
        plan,height=fit_layout_height(self.layout,width,oldheight,height,gap,minima)
        if plan is None:
            self.message('The cards cannot fit at their minimum sizes. Hide a card or reduce the spacing.');return
        self.transaction.checkpoint()
        self.canvas_size=(width,height);self.layout=plan;self.store_layout()
        self.board.set_size_request(width,round(height));self.fixed.set_size_request(width,round(height))
        self.reflow();self.edit_layout()
        self.message('Cards fitted to the visible dashboard · Save to keep this layout')

    def toggle_card(self,key,enabled):
        visible=self.profile['visible']
        if enabled==(key in visible):return True
        self.transaction.checkpoint()
        self.store_layout()
        saved=self.profile['layouts'][self.display_key]
        if enabled:
            width,height=self.canvas_size
            viewport=max(1,self.board_view.get_allocated_height()-4)
            plan=deepcopy(self.layout)
            minima={name:card.content.get_preferred_height()[0]+2 for name,card in self.cards.items()}
            probe=Card(self,key);minima[key]=probe.content.get_preferred_height()[0]+2;probe.destroy()
            previous=saved.get(key)
            gap=self.profile['appearance']['spacing']*self.profile['appearance'].get('scale',1)
            if height>viewport+4:
                plan,height=fit_layout_height(plan,width,height,viewport,gap,minima)
            if plan is None:
                self.message('Not enough room at the cards’ minimum sizes. Hide a card or reduce the spacing.');return False
            if previous and previous[3]*height>=max(100,minima[key]) and valid_move(key,previous,plan) and all(spaced(previous,r,width,height,gap) for r in plan.values()):plan[key]=deepcopy(previous)
            else:plan,height=insert_card(key,plan,width,height,gap,minimums=minima)
            if plan is None:
                self.message('Not enough room at the cards’ minimum sizes. Hide a card or reduce the spacing.');return False
            self.canvas_size=(width,height)
            self.board.set_size_request(width,round(height));self.fixed.set_size_request(width,round(height))
            saved.update(plan)
            self.profile.setdefault('layout_sizes',{})[self.display_key]=[width,height]
            visible.append(key)
        else:visible.remove(key)
        self.build_cards()
        return True

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

    def card_interval_controls(self,parent,source,title):
        line=box(False,6);line.pack_start(label(title),True,True,0)
        controls=box(False,4)
        entry=Gtk.Entry();entry.set_width_chars(5);entry.set_max_width_chars(6)
        entry.set_alignment(.5);entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
        entry.set_text(str(self.profile['refresh'].get(source,REFRESH[source])))
        entry.get_accessible().set_name(title+' refresh interval in seconds')
        def change(delta):
            value=self.profile['refresh'].get(source,REFRESH[source])
            entry.set_text(str(max(1,min(86400,value+delta))))
        minus=button('−',lambda:change(-1),'Refresh more often')
        plus=button('+',lambda:change(1),'Refresh less often')
        minus.get_accessible().set_name('Decrease '+title+' refresh interval')
        plus.get_accessible().set_name('Increase '+title+' refresh interval')
        def edited(widget):
            text=widget.get_text().strip()
            value=int(text) if text.isdecimal() and len(text)<=5 else 0
            valid=1<=value<=86400
            style=widget.get_style_context()
            if valid:
                self.set_interval(source,value);style.remove_class('warning')
            else:style.add_class('warning')
            current=self.profile['refresh'].get(source,REFRESH[source])
            minus.set_sensitive(current>1);plus.set_sensitive(current<86400)
        entry.connect('changed',edited)
        entry.connect('focus-out-event',lambda widget,event:(widget.set_text(str(self.profile['refresh'].get(source,REFRESH[source]))),False)[1])
        entry.set_tooltip_text('Seconds between updates · enter a value from 1 to 86400')
        edited(entry)
        for control in (minus,entry,plus,label('sec','muted')):controls.pack_start(control,False,False,0)
        line.pack_end(controls,False,False,0);parent.pack_start(line,False,False,0)

    def card_menu(self,card):
        self.begin()
        self.editing=False;self.control_stack.set_visible_child(self.healthbar)
        for item in self.cards.values():item.set_editing(False)
        content=self.drawer_page(CARDS[card.key][0]+' · edit')
        sources=SOURCES.get(card.key,())
        if sources:
            content.pack_start(label('REFRESH INTERVALS','heading'),False,False,0)
            for source in sources:
                self.card_interval_controls(content,source,SOURCE_TITLES.get(source,CARDS[card.key][0]))
            content.pack_start(label('− refreshes more often; + refreshes less often. You can also type the number of seconds.',style='muted',wrap=True),False,False,0)
            content.pack_start(button('Refresh now',lambda:self.refresh_card(card.key)),False,False,0)
        else:content.pack_start(label('This card updates when you edit it; no refresh interval is needed.',style='muted',wrap=True),False,False,0)
        for title,callback in [('Move / resize',self.edit_layout),('Card library',lambda:self.open_settings('Cards'))]:
            content.pack_start(button(title,callback),False,False,0)
        if card.key=='arch':content.pack_start(button('Open update list',lambda:self.run('launch.sh','updates')),False,False,0)
        reveal(self.drawer)
        self.status.show();self.status.set_text('Changes remain a preview until you Save · Cancel restores previous settings')

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
            if gate['visible'] and not self.visible and self.calendar_selection is not None:
                self.select_calendar_date(datetime.date.today())
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
        if 'calendar' in changed and self.calendar_selection is not None:
            self.select_calendar_date(self.calendar_selection)
        for key,card in self.cards.items():
            if changed.intersection(SOURCES.get(key,())) or (key=='system' and 'health' in changed): card.render()
            card.update_freshness()
        self.update_health()
        self.diagnostic_payload=json.dumps({'backend':'gtk','profile':self.data['active_profile'],'visible':self.visible,'paused':self.paused,'canvas':self.canvas_size,'cards':list(self.cards),'zoom':self.profile['appearance'].get('scale',1),'samples':{key:{'updated':value.get('updated',0),'error':value.get('error','')} for key,value in self.samples.items()}})
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
            parent.pack_start(button(issue['text'],lambda issue=issue:self.open_health_issue(issue)),False,False,0)
        parent.pack_start(label('Checks cover disk space, failed system/user services, network connectivity, monitored shares and low battery.',wrap=True),False,False,0)
        parent.pack_start(button('Check again now',lambda:[self.engine.request(s) for s in ('health','network','shares','power')]),False,False,0)
        parent.pack_start(button('Configure monitored shares',lambda:self.open_settings('Cards')),False,False,0)
        reveal(self.drawer)

    def open_health_summary(self):
        issues=getattr(self,'issues',[])
        if len(issues)==1 and 'unit' in issues[0]: self.open_health_issue(issues[0])
        else: self.show_health()

    def open_health_issue(self,issue):
        if 'unit' in issue:
            self.show_service_details(issue['unit'],issue['scope'])
        else:
            self.focus_card(issue['card'])

    def show_service_details(self,unit,scope):
        parent=self.drawer_page('Unit diagnostics',editable=False)
        generation=self.drawer_generation
        row(parent,'Unit',unit)
        row(parent,'Manager','Your user session' if scope=='user' else 'System')
        parent.pack_start(label('Current status and the last 50 accessible log entries from this boot.',wrap=True),False,False,0)
        buffers={}
        for key,title in [('status','Current status'),('journal','Recent logs')]:
            parent.pack_start(label(title,'heading'),False,False,0)
            view=Gtk.TextView(editable=False,cursor_visible=False,monospace=True)
            view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            buffers[key]=view.get_buffer(); buffers[key].set_text('Loading…')
            pane=scroll(view); pane.set_size_request(-1,180 if key=='status' else 240)
            parent.pack_start(pane,False,False,0)
        refresh=button('Refresh details',lambda:self.show_service_details(unit,scope))
        refresh.set_sensitive(False)
        parent.pack_start(refresh,False,False,0)
        parent.pack_start(button('Back to system health',self.show_health),False,False,0)
        reveal(self.drawer)
        def receive_details(result):
            if self.closing or self.drawer_generation!=generation or not self.drawer.get_visible():
                return False
            for key,buffer in buffers.items(): buffer.set_text(result[key])
            refresh.set_sensitive(True)
            self.engine.request('health')
            return False
        def read_details():
            try: result=service_details(unit,scope)
            except (OSError,ValueError) as exc: result={'status':str(exc),'journal':'Details unavailable.'}
            GLib.idle_add(receive_details,result)
        threading.Thread(target=read_details,daemon=True,name='poedash-service-details').start()

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

    def select_calendar_date(self,day):
        if self.closing: return
        self.calendar_generation+=1
        generation=self.calendar_generation
        if self.calendar_future: self.calendar_future.cancel()
        self.calendar_selection=None if day==datetime.date.today() else day
        self.calendar_day_data={'status':'Reading Thunderbird calendars','events':[]}
        if 'calendar' in self.cards: self.cards['calendar'].render()
        if self.calendar_selection is None: return
        def read_day():
            try:
                result=subprocess.run([sys.executable,str(self.root/'scripts/thunderbird-calendar.py'),'--date',day.isoformat()],
                                      capture_output=True,text=True,timeout=5,check=True)
                return json.loads(result.stdout)
            except (OSError,ValueError,subprocess.SubprocessError):
                return {'status':'Thunderbird calendar unavailable','events':[]}
        def ready(future):
            if not future.cancelled(): GLib.idle_add(self.receive_calendar_day,generation,future.result())
        self.calendar_future=self.calendar_pool.submit(read_day)
        self.calendar_future.add_done_callback(ready)

    def receive_calendar_day(self,generation,payload):
        if self.closing or generation!=self.calendar_generation: return False
        self.calendar_day_data=payload
        if 'calendar' in self.cards: self.cards['calendar'].render()
        return False

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
                image.set_pixel_size(round(self.profile['appearance']['recent_icon_size']*self.profile['appearance'].get('scale',1)))
                content.pack_start(image,False,False,0)
                text=label(app.get('name','App'),'app-name'); text.set_max_width_chars(9); text.set_xalign(.5)
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
        if self.visible and 'player' in self.cards: self.cards['player'].update_wave()
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
                if card.key=='calendar' and card.calendar_date!=now.date(): self.select_calendar_date(now.date())
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
            if not self.toolbar.get_mapped(): raise RuntimeError('Editing toolbar is hidden')
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
                card.release(card.cover,SimpleNamespace(x_root=100+dx,y_root=100+dy))
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
                if self.toggle_card(key,True):self.cards[key].render()
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
        self.calendar_pool.shutdown(wait=False,cancel_futures=True)
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
        Gtk.StyleContext.remove_provider_for_screen(self.window.get_screen(),self.provider)
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
        import cairo
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
