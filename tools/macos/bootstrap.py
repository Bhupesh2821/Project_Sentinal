"""Project-linked native bundle entry; no camera or network starts here."""
import os
from pathlib import Path
import site
import sys

root=Path(os.environ['SENTINAL_PROJECT_ROOT']).resolve()
venv=root/'.venv'
sys.prefix=str(venv)
sys.exec_prefix=str(venv)
sys.executable=str(venv/'bin/python')
site.addsitedir(str(venv/f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages'))
sys.path.insert(0,str(root))
os.chdir(root)

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--sentinal-verify':
        from tools.verify_macos_app import run_inside_bundle
        status=run_inside_bundle(sys.argv[2])
    else:
        from sentinal.application import main
        status=main([arg for arg in sys.argv[1:] if not arg.startswith('-psn_')])
    # Preserve the native host until Qt/resource cleanup has completed.
    if status:
        raise RuntimeError(f'SENTINAL application returned status {status}; see local diagnostics')
