"""Build a real, project-linked macOS app without copying private runtime data."""
import argparse
import ast
from datetime import datetime,timezone
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import sysconfig

ROOT=Path(__file__).resolve().parents[1]


def app_info(version):
    return {'CFBundleName':'SENTINAL','CFBundleDisplayName':'SENTINAL',
        'CFBundleIdentifier':'org.projectsentinal.visioncore','CFBundleExecutable':'SENTINAL',
        'CFBundlePackageType':'APPL','CFBundleShortVersionString':version,'CFBundleVersion':version,
        'CFBundleIconFile':'SENTINAL.icns','NSHighResolutionCapable':True,
        'LSMinimumSystemVersion':'13.0','LSMultipleInstancesProhibited':True,
        'NSCameraUsageDescription':'SENTINAL uses the camera only when you explicitly select a source and start monitoring. Video is processed locally.',
        'NSLocalNetworkUsageDescription':'SENTINAL connects to authorized cameras and discovers compatible ONVIF services only when you request it.',
        'NSHumanReadableCopyright':'Project SENTINAL. AGPL-3.0 source; dependencies retain their licenses.'}


def version():
    for statement in ast.parse((ROOT/'sentinal/__init__.py').read_text()).body:
        if isinstance(statement,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='__version__' for target in statement.targets):
            return ast.literal_eval(statement.value)
    raise ValueError('Source version is unavailable')


def run(command,**kwargs):
    subprocess.run(command,check=True,**kwargs)


def build(target=None):
    if sys.platform!='darwin':raise ValueError('The native application can only be built on macOS')
    target=Path(target or ROOT/'dist/SENTINAL.app').resolve()
    if not target.is_relative_to(ROOT) or target.suffix!='.app':raise ValueError('Application output must be an .app inside the canonical project')
    scratch=ROOT/'work/mac-app-build';scratch.mkdir(parents=True,exist_ok=True)
    stage=scratch/'SENTINAL.app'
    if stage.exists():shutil.rmtree(stage)
    executable=stage/'Contents/MacOS/SENTINAL';resources=stage/'Contents/Resources'
    executable.parent.mkdir(parents=True);resources.mkdir(parents=True)
    with (stage/'Contents/Info.plist').open('wb') as stream:plistlib.dump(app_info(version()),stream)
    with (resources/'ProjectRoot.plist').open('wb') as stream:plistlib.dump({'ProjectRoot':str(ROOT),'Runtime':'project-linked .venv; not a standalone installation'},stream)
    shutil.copy2(ROOT/'tools/macos/bootstrap.py',resources/'bootstrap.py')
    include=sysconfig.get_config_var('INCLUDEPY');framework=sysconfig.get_config_var('PYTHONFRAMEWORKPREFIX')
    if not include or not framework:raise ValueError('A compatible framework Python with headers is required')
    command=['/usr/bin/clang','-fobjc-arc','-O2','-mmacosx-version-min=13.0',
        '-I'+include,'-framework','Cocoa',str(Path(sys.base_prefix)/'Python'),
        '-DSENTINAL_PYTHON_HOME='+json.dumps(sys.base_prefix),str(ROOT/'tools/macos/launcher.m'),'-o',str(executable)]
    run(command,cwd=ROOT)
    # Qt SVG is already part of the desktop dependencies; no image service/download.
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QGuiApplication,QImage,QPainter
    from PySide6.QtSvg import QSvgRenderer
    import os
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    app=QGuiApplication.instance() or QGuiApplication([])
    renderer=QSvgRenderer(str(ROOT/'web/icon.svg'))
    if not renderer.isValid():raise ValueError('The original SENTINAL vector icon is invalid')
    iconset=scratch/'SENTINAL.iconset';iconset.mkdir(exist_ok=True)
    for size in (16,32,128,256,512):
        for scale in (1,2):
            pixels=size*scale;image=QImage(pixels,pixels,QImage.Format.Format_ARGB32);image.fill(0)
            painter=QPainter(image);renderer.render(painter,QRectF(0,0,pixels,pixels));painter.end()
            suffix='@2x' if scale==2 else ''
            if not image.save(str(iconset/f'icon_{size}x{size}{suffix}.png')):raise ValueError('Icon raster could not be written')
    run(['/usr/bin/iconutil','-c','icns',str(iconset),'-o',str(resources/'SENTINAL.icns')],cwd=ROOT)
    run(['/usr/bin/codesign','--force','--sign','-',str(stage)],cwd=ROOT)
    run(['/usr/bin/codesign','--verify','--strict',str(stage)],cwd=ROOT)
    backup=None
    if target.exists():
        timestamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup=ROOT/'history/macos-app'/timestamp/target.name;backup.parent.mkdir(parents=True)
        shutil.move(str(target),str(backup))
    target.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(stage),str(target))
    report={'built':True,'version':version(),'app':str(target.relative_to(ROOT)),'binary_kind':'native Mach-O launcher embedding the existing project Python framework',
        'standalone':False,'python_environment':'.venv','camera_auto_started':False,
        'signing':'local ad-hoc signature; not Developer ID signed or notarized','prior_bundle_backup':str(backup.relative_to(ROOT)) if backup else None,
        'models_or_private_stores_copied':False}
    (ROOT/'work/mac-app-build/build-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output')
    print(json.dumps(build(parser.parse_args().output),indent=2))
