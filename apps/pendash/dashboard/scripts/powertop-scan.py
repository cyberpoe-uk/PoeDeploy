#!/usr/bin/env python3
"""Explicit, finite PowerTOP measurement; never a recurring root service."""
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import fcntl


class Tables(HTMLParser):
    def __init__(self):
        super().__init__(); self.tables=[]; self.table=[]; self.row=[]; self.cell=None
    def handle_starttag(self, tag, attrs):
        if tag == 'table': self.table=[]
        elif tag == 'tr': self.row=[]
        elif tag in ('td','th'): self.cell=[]
    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self, tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(''.join(self.cell).strip()); self.cell=None
        elif tag == 'tr': self.table.append(self.row)
        elif tag == 'table': self.tables.append(self.table)


def parse(text):
    parser=Tables(); parser.feed(text)
    groups={}
    for table in parser.tables:
        if not table or 'Wakeups/s' not in table[0] or 'Description' not in table[0]: continue
        header=table[0]; wi=header.index('Wakeups/s'); di=header.index('Description'); ci=header.index('Category')
        for row in table[1:]:
            if len(row) <= max(wi,di,ci) or row[ci] != 'Process': continue
            match=re.match(r'\[PID \d+\]\s+(\S+)',row[di])
            if not match: continue
            if match.group(1).startswith('['): continue  # Kernel threads are not apps.
            name=Path(match.group(1)).name
            if name.startswith('[') or name in ('powertop','pkexec'): continue
            try: value=float(row[wi])
            except ValueError: continue
            groups[name]=groups.get(name,0)+value
    return [{'name':n,'wakeups':v} for n,v in sorted(groups.items(),key=lambda x:x[1],reverse=True)[:3]]


def main():
    cache=Path.home()/'.cache/eww'; cache.mkdir(parents=True,exist_ok=True)
    with (cache/'powertop.lock').open('w') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: return
        subprocess.run(['notify-send','PoeDash','PowerTOP will measure wakeups for 15 seconds. Authentication may be required.'])
        with tempfile.TemporaryDirectory(prefix='poedash-powertop-') as tmp:
            report=Path(tmp)/'report.html'
            p=subprocess.run(['pkexec','/usr/bin/powertop','--time=15',f'--html={report}'],capture_output=True,text=True)
            if p.returncode or not report.exists():
                subprocess.run(['notify-send','PoeDash','PowerTOP scan cancelled or failed.'])
                return
            text=report.read_text()
            (cache/'powertop.html').write_text(text)
            (cache/'powertop.json').write_text(json.dumps({'timestamp':time.time(),'apps':parse(text)}))
        subprocess.run(['notify-send','PoeDash','PowerTOP result is available on the laptop card. Rankings are wakeups, not watts.'])


if __name__=='__main__': main()
