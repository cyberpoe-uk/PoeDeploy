#!/usr/bin/env python3
"""Build the small GTK host adapter for Eww; no desktop state is changed."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import sysconfig
import tempfile

ROOT=Path(__file__).resolve().parent.parent

def prepare(root=ROOT):
    root=Path(root)
    for command in ('cc','pkg-config','eww'):
        if not shutil.which(command):raise RuntimeError('Eww shared hosting requires '+command+' (install gcc, pkgconf and Eww)')
    source=root/'scripts/eww-host-module.c'
    library=str(Path(sysconfig.get_config_var('LIBDIR'))/sysconfig.get_config_var('LDLIBRARY'))
    signature=sys.version+sysconfig.get_platform()+str(sysconfig.get_config_var('SOABI'))+library+str(Path(library).stat().st_mtime_ns)
    key=hashlib.sha256(source.read_bytes()+signature.encode()).hexdigest()[:20]
    directory=root/'state/eww-host';directory.mkdir(parents=True,exist_ok=True)
    output=directory/('host-'+key+'.so')
    if not output.exists():
        flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','gtk+-3.0','pygobject-3.0'],text=True))
        with tempfile.NamedTemporaryFile(prefix='host-build-',suffix='.so',dir=directory,delete=False) as stream:temporary=Path(stream.name)
        command=['cc','-shared','-fPIC','-O2',str(source),'-o',str(temporary),'-I'+sysconfig.get_path('include'),
                 '-DPOEDASH_PYTHON_LIBRARY='+json.dumps(library),library,'-ldl',*flags]
        try:
            subprocess.run(command,check=True,capture_output=True,text=True,timeout=60)
            temporary.chmod(0o700);os.replace(temporary,output)
        except subprocess.CalledProcessError as exc:
            temporary.unlink(missing_ok=True)
            raise RuntimeError('Eww host compilation failed: '+exc.stderr[-3000:]) from exc
        finally:temporary.unlink(missing_ok=True)
    return output

if __name__=='__main__':
    try:print(prepare())
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
        print(str(exc),file=sys.stderr);raise SystemExit(1)
