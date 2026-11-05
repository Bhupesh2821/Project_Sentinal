"""V0.3 release boundaries: source is distributable; local account state is not."""
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest


def tool():
    path=Path(__file__).resolve().parents[1]/'tools/package_project.py'
    spec=importlib.util.spec_from_file_location('package_v03_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def write(root,name,data=b'public source'):
    path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);return path


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def root(tmp_path):
    model=write(tmp_path,'models/v02/model.pt',b'synthetic selected checkpoint')
    license=write(tmp_path,'models/v02/LICENSE.txt',b'public license')
    write(tmp_path,'models/v02/MODEL_MANIFEST.json',json.dumps({'selected_assets':[{'filename':'model.pt','sha256':sha(model),'license_file':'LICENSE.txt','license_sha256':sha(license)}],'included_files':['model.pt','LICENSE.txt']}).encode())
    photo=write(tmp_path,'data/v02-evaluation/public.jpg',b'synthetic public fixture')
    write(tmp_path,'data/v02-demo/DISTRIBUTION_MANIFEST.json',json.dumps({'files':[{'path':'data/v02-evaluation/public.jpg','sha256':sha(photo),'license':'Public domain','source_url':'https://example.invalid/credit'}]}).encode())
    return tmp_path


def test_v03_release_includes_launchable_local_and_hosted_source(root):
    approved=['web.command','web/index.html','web/app.html','web/app.js','web/sw.js','web/manifest.webmanifest',
              'sentinal/connected/server.py','sentinal/connected/edge.py','tools/start_command_center.py',
              'frontend/command-center/package.json','frontend/command-center/package-lock.json',
              'frontend/command-center/cloud.js','frontend/command-center/sync-assets.mjs',
              'frontend/command-center/base44/config.jsonc','frontend/command-center/base44/entities/CommandState.jsonc',
              'frontend/command-center/base44/functions/command/entry.ts','frontend/command-center/base44/functions/ingest/entry.ts',
              'frontend/command-center/base44/shared/core.js','docs/CONNECTED_V03.md',
              'docs/evidence/v03-test/hash-only-report.json']
    for name in approved:write(root,name)
    included=set(tool().collect_release_files(root))
    assert all(root/name in included for name in approved)


@pytest.mark.parametrize('private',[
    'frontend/command-center/node_modules/dependency/private.js',
    'frontend/command-center/dist/assets/bundle.js','frontend/command-center/build/output.js',
    'frontend/command-center/.git/config','frontend/command-center/.base44/auth.json',
    'frontend/command-center/.env','frontend/command-center/.env.production',
    'frontend/command-center/credentials.json','frontend/command-center/secrets.json',
    'frontend/command-center/private.key','frontend/command-center/config/accounts.json',
    'docs/evidence/v03-test/accounts.json','web/.env.local','web/tokens.json',
    'config/connected/edge-credentials.json','recordings/connected/server.sqlite3',
    'work/v03-browser/accounts.json'])
def test_v03_release_excludes_installed_builds_credentials_and_operational_data(root,private):
    private_path=write(root,private,b'private account state sentinel')
    assert private_path not in tool().collect_release_files(root)


def test_v03_frontend_external_symlink_cannot_enter_archive(root,tmp_path):
    external=write(tmp_path,'external-private.json',b'private external')
    frontend=root/'frontend/command-center';frontend.mkdir(parents=True)
    (frontend/'linked.json').symlink_to(external)
    (frontend/'linked-directory').symlink_to(tmp_path,target_is_directory=True)
    included=tool().collect_release_files(root)
    assert not any(path.is_symlink() or 'linked-directory' in path.parts for path in included)



def native_fixture(root):
    import plistlib
    module=tool();bundle=root/'dist/SENTINAL.app'
    for name in module.NATIVE_APP_FILES:write(root,'dist/SENTINAL.app/'+name,b'policy test data, not an executable or signature')
    write(root,'tools/macos/bootstrap.py',b'# reviewed bootstrap')
    (bundle/'Contents/Resources/bootstrap.py').write_bytes(b'# reviewed bootstrap')
    (bundle/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'SENTINAL','CFBundleShortVersionString':module.__version__,'NSCameraUsageDescription':'Only on explicit Start'}))
    return module,bundle


def test_native_package_maps_only_reviewed_bundle_without_dist_runtime(root):
    module,bundle=native_fixture(root)
    entries=module.native_app_entries(root)
    assert len(entries)==len(module.NATIVE_APP_FILES)
    assert all(str(target).startswith('SENTINAL/SENTINAL.app/Contents/') for _,target in entries)
    assert all('dist' not in target.parts for _,target in entries)


def test_native_package_rejects_unreviewed_private_file(root):
    module,bundle=native_fixture(root)
    (bundle/'Contents/Resources/credentials.json').write_text('private sentinel')
    with pytest.raises(ValueError,match='Unreviewed'):module.native_app_entries(root)


def test_native_package_rejects_stale_bootstrap_and_external_link(root):
    module,bundle=native_fixture(root)
    script=bundle/'Contents/Resources/bootstrap.py';script.write_text('# old startup')
    with pytest.raises(ValueError,match='differs'):module.native_app_entries(root)
    script.unlink();script.symlink_to(root/'tools/macos/bootstrap.py')
    with pytest.raises(ValueError,match='symlink'):module.native_app_entries(root)
