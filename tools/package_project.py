"""Package source and explicitly licensed assets; exclude private runtime state."""
from dataclasses import asdict
from pathlib import Path
import argparse
import hashlib
import json
import os
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sentinal import __version__

TOP_FILES=('main.py','README.md','VERIFICATION_REPORT.md','RELEASE_NOTES.md',
    'HACKATHON_DEMO.md','DEVELOPMENT_CHECKPOINT.md','LOCATION.md','AGENTS.md',
    'LICENSE','LICENSE_NOTES.md','requirements.txt','requirements-lock.txt',
    'install.command','launch.command','demo.command','web.command','runtime-env.sh','test.command',
    'pytest.ini','.gitignore')
BASE_MODELS=('yolo11n.pt','yolo11n.sha256','yolov8n-oiv7.pt','yolov8n-oiv7.sha256',
    'yolov8s-oiv7.pt','yolov8s-oiv7.sha256','yolo11s.pt','yolo11s.sha256','yolo11s.source.json')
BANNED_PARTS={'__pycache__','runtime','.pytest_cache','quarantine','.venv','venv','history','recordings','logs',
    '.git','.base44','.codex','.agents','node_modules','dist','build','coverage','.next','.npm','work'}
BANNED_SUFFIXES={'.pyc','.pyo','.sqlite3','.db','.part','.download-part','.zip','.sha256.zip','.pem','.key','.p12','.pfx'}
PRIVATE_FILENAMES={'.app.jsonc','accounts.json','credentials.json','edge-credentials.json','base44-edge-credentials.json',
    'auth.json','tokens.json','secrets.json','device-secret.txt'}
SOURCE_DIRS=('sentinal','tests','tools','docs','web','frontend/command-center')
MEDIA_SUFFIXES={'.jpg','.jpeg','.png','.mp4','.avi','.webm','.mov'}


def digest(path):
    with path.open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()


def inside(root,relative,base=None):
    if not isinstance(relative,str):raise ValueError('Manifest paths must be relative strings')
    fragment=Path(relative)
    if fragment.is_absolute() or '..' in fragment.parts:raise ValueError('Manifest path escaped its asset directory')
    path=(base or root)/fragment
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('Manifest asset is missing, external or a symlink')
    return path


def selected_model_files(root):
    base=root/'models/v02';manifest_path=base/'MODEL_MANIFEST.json'
    manifest=json.loads(manifest_path.read_text())
    selected=manifest['selected_assets'];included=manifest['included_files']
    if not isinstance(selected,list) or not selected or not isinstance(included,list):raise ValueError('Invalid selected model manifest')
    expected={entry['filename'] for entry in selected}
    files={manifest_path}
    for name in included:
        path=inside(root,name,base)
        if path.suffix=='.pt' and name not in expected:raise ValueError('Unselected checkpoint cannot enter the release')
        files.add(path)
    for entry in selected:
        for name,checksum in [(entry['filename'],entry['sha256']),(entry['license_file'],entry['license_sha256'])]:
            path=inside(root,name,base)
            if path not in files or digest(path)!=checksum:raise ValueError('Selected model or license checksum mismatch')
    return files


def public_fixture_files(root):
    manifest_path=root/'data/v02-demo/DISTRIBUTION_MANIFEST.json'
    manifest=json.loads(manifest_path.read_text())
    entries=manifest['files'];files={manifest_path}
    if not isinstance(entries,list) or not entries:raise ValueError('Public fixture distribution manifest is empty')
    for entry in entries:
        path=inside(root,entry['path'])
        relative=path.relative_to(root)
        if relative.parts[:2] not in {('data','v02-demo'),('data','v02-evaluation')}:
            raise ValueError('Only approved public V0.2 fixture folders may be packaged')
        if digest(path)!=entry['sha256']:raise ValueError('Public fixture checksum mismatch')
        if path.suffix.lower() in MEDIA_SUFFIXES:
            license=str(entry.get('license','')).lower()
            if not license or not any(term in license for term in ('public domain','cc by','cc-by')) or not entry.get('source_url'):
                raise ValueError('Public media requires reviewed source attribution and license')
        files.add(path)
    if 'included_files' in manifest and set(manifest['included_files'])!={str(path.relative_to(root)) for path in files if path!=manifest_path}:
        raise ValueError('Public fixture whitelist does not match hashed entries')
    return files



def reported_item_fixture_files(root):
    """Only reviewed public V0.2.1 photos and their hashed attribution enter ZIP."""
    manifest_path=root/'data/v021-items/DISTRIBUTION_MANIFEST.json'
    if not manifest_path.is_file():return set()
    entries=json.loads(manifest_path.read_text()).get('files')
    if not isinstance(entries,list) or not entries:raise ValueError('Reported-item fixture whitelist is empty')
    files={manifest_path}
    for entry in entries:
        path=inside(root,entry['path'])
        if path.relative_to(root).parts[:2]!=('data','v021-items'):
            raise ValueError('Reported-item fixture escaped its public directory')
        if digest(path)!=entry['sha256']:raise ValueError('Reported-item fixture checksum mismatch')
        if path.suffix.lower() in MEDIA_SUFFIXES:
            license=str(entry.get('license','')).lower()
            if not any(term in license for term in ('cc by','cc-by','public domain')) or not entry.get('source_url') or not entry.get('author'):
                raise ValueError('Reported-item media requires reviewed license, author and source')
        files.add(path)
    return files


def verify_optional_everyday_model(root):
    target=root/'models/yolo11s.pt'
    if not target.is_file():return
    from tools.download_everyday_small import SHA256
    provenance=root/'models/yolo11s.source.json';checksum=root/'models/yolo11s.sha256'
    if not provenance.is_file() or not checksum.is_file():raise ValueError('Optional YOLO11s provenance is missing')
    if digest(target)!=SHA256 or json.loads(provenance.read_text()).get('sha256')!=SHA256 or checksum.read_text().split()[0]!=SHA256:
        raise ValueError('Optional YOLO11s checksum mismatch')

def eligible_source(path,root):
    relative=path.relative_to(root)
    if path.name=='.DS_Store' or path.name.casefold().startswith('.env') or path.name.casefold() in PRIVATE_FILENAMES:return False
    if not path.is_file() or path.is_symlink() or any(part.casefold() in BANNED_PARTS for part in relative.parts):return False
    if path.suffix.casefold() in BANNED_SUFFIXES or path.name.endswith(('-wal','-shm')):return False
    if path.name in {'archive-check.json','release-archive-check.json','delivery-manifest.json'}:return False
    # Historical camera reports can contain personal names and raw device IDs.
    # Preserve them locally; ship only current technical/hash-only V0.2 evidence.
    if relative.parts[:2]==('docs','evidence'):
        return len(relative.parts)>2 and relative.parts[2].startswith(('v02-','v021-','v03-'))
    if len(relative.parts)>1 and relative.parts[0]=='docs' and relative.parts[1].startswith('verification'):
        return path.suffix=='.md'
    return True


def source_files(directory,root):
    """Prune installed dependencies/builds before walking source subdirectories."""
    for current,directories,names in os.walk(directory,followlinks=False):
        directories[:]=[name for name in directories if name.casefold() not in BANNED_PARTS and not (Path(current)/name).is_symlink()]
        for name in names:
            path=Path(current)/name
            if eligible_source(path,root):yield path


def collect_release_files(root=ROOT):
    root=Path(root);files={root/name for name in TOP_FILES if (root/name).is_file()}
    for directory in SOURCE_DIRS:
        files.update(source_files(root/directory,root))
    files.update(root/'models'/name for name in BASE_MODELS if (root/'models'/name).is_file())
    verify_optional_everyday_model(root)
    files.update(selected_model_files(root));files.update(public_fixture_files(root));files.update(reported_item_fixture_files(root))
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):raise ValueError('Release entry escaped project root')
    return sorted(files)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',default='docs/evidence/release-archive-check.json')
    args=parser.parse_args(argv)
    report_path=(ROOT/args.report).resolve()
    if not report_path.is_relative_to(ROOT):raise ValueError('Archive evidence must remain inside project')
    output=ROOT/'archives'/f'SENTINAL-V{__version__}-macOS.zip'
    output.parent.mkdir(parents=True,exist_ok=True)
    files=[path for path in collect_release_files() if path!=report_path]
    from sentinal.config import AppConfig
    from sentinal.vision.model_registry import ASSETS
    required=['main.py','launch.command','install.command','demo.command','web.command','HACKATHON_DEMO.md',
        'web/index.html','web/app.html','web/app.js','web/sw.js','web/manifest.webmanifest',
        'tools/start_command_center.py','sentinal/connected/server.py','sentinal/connected/edge.py',
        'sentinal/interface/connected_dialog.py','docs/CONNECTED_V03.md',
        'frontend/command-center/package.json','frontend/command-center/package-lock.json',
        'frontend/command-center/base44/entities/CommandState.jsonc',
        'frontend/command-center/base44/functions/command/entry.ts',
        'frontend/command-center/base44/functions/ingest/entry.ts',
        'sentinal/storage/video_library.py','sentinal/vision/live_capture.py','sentinal/interface/video_import_worker.py',
        'sentinal/vision/qt_camera.py','sentinal/vision/object_catalog.py','sentinal/vision/onvif_client.py',
        'sentinal/vision/network_discovery.py','sentinal/interface/network_camera_dialog.py','sentinal/interface/catalog_dialog.py',
        'sentinal/storage/camera_registry.py','sentinal/core/credentials.py','sentinal/core/incidents.py',
        'sentinal/core/incident_worker.py','sentinal/storage/incident_database.py','sentinal/storage/evidence_store.py',
        'sentinal/vision/specialized.py','sentinal/vision/safe_weights.py','sentinal/interface/control_center.py',
        'sentinal/interface/local_alerts.py','sentinal/interface/assets/alert.wav','tools/download_v02_models.py',
        'models/yolov8n-oiv7.pt','models/yolov8s-oiv7.pt','models/v02/MODEL_MANIFEST.json',
        'docs/MODEL_MANIFEST_V02.md','docs/FIXTURES_V02.md',
        'data/v02-demo/DISTRIBUTION_MANIFEST.json','data/v02-demo/weapon_range_motion.mp4',
        'data/v02-demo/handgun_repeated_still.mp4','data/v02-demo/fire_repeated_still.mp4',
        'data/v02-demo/smoke_repeated_still.mp4']+[f'models/v02/{asset.filename}' for asset in ASSETS.values()]
    partial=output.with_suffix('.zip.part')
    try:
        with zipfile.ZipFile(partial,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for path in files:archive.write(path,Path('SENTINAL')/path.relative_to(ROOT))
            archive.writestr('SENTINAL/config/settings.json',json.dumps(asdict(AppConfig()),indent=2)+'\n')
            for directory in ['logs','recordings','data/videos','work/tmp']:archive.writestr(f'SENTINAL/{directory}/',b'')
        with zipfile.ZipFile(partial) as archive:
            if archive.testzip() is not None:raise RuntimeError('ZIP integrity failure')
            names=archive.namelist()
            if len(names)!=len(set(names)):raise RuntimeError('Duplicate ZIP entries')
            for name in names:
                relative=Path(name).parts[1:]
                if (not name.endswith('/') and any(part.casefold() in BANNED_PARTS for part in relative)) or name.endswith(('.sqlite3','.db','-wal','-shm')):
                    raise RuntimeError('Private/runtime file unexpectedly included')
                if '/config/' in name and name!='SENTINAL/config/settings.json':raise RuntimeError('User configuration unexpectedly included')
            for name in ('launch.command','install.command','demo.command','web.command','test.command'):
                if not (archive.getinfo('SENTINAL/'+name).external_attr>>16)&0o111:raise RuntimeError('Executable script permission lost')
            for name in required:
                if 'SENTINAL/'+name not in names:raise RuntimeError('Required release source or asset missing: '+name)
            for asset in ASSETS.values():
                if hashlib.sha256(archive.read('SENTINAL/models/v02/'+asset.filename)).hexdigest()!=asset.sha256:raise RuntimeError('Packaged selected model checksum mismatch')
        partial.replace(output)
    finally:partial.unlink(missing_ok=True)
    checksum=digest(output);output.with_suffix('.zip.sha256').write_text(f'{checksum}  {output.name}\n')
    report={'passed':True,'version':__version__,'archive':str(output.relative_to(ROOT)),'bytes':output.stat().st_size,
        'members':len(names),'sha256':checksum,'zip_crc_verified':True,'executable_scripts_verified':True,
        'selected_models_verified':True,'public_fixture_manifest_verified':True,
        'includes':'desktop and connected source, Base44 frontend/functions/schema and pinned package lock, pinned Python dependencies, selected licensed weights, approved public fixtures, current technical evidence, default configuration',
        'excludes':'installed environment, all user settings/cameras/credentials, user media/databases/evidence, runtime caches/logs, exploratory checkpoints, local test executables and conversation/history files'}
    report_path.parent.mkdir(parents=True,exist_ok=True);report_path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
