"""Release privacy/integrity contracts using synthetic byte fixtures, not AI proof."""
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest


def load_tool(name):
    path=Path(__file__).resolve().parents[1]/'tools'/name
    spec=importlib.util.spec_from_file_location('sentinal_test_'+path.stem,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def sha(data):return hashlib.sha256(data).hexdigest()


def write(root,name,data=b'fixture'):
    path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);return path


@pytest.fixture
def package_tree(tmp_path):
    root=tmp_path/'release';root.mkdir()
    for directory in ('sentinal','tests','tools','docs','models','config'):(root/directory).mkdir()
    write(root,'main.py',b'# source')
    write(root,'sentinal/vision.py',b'# source')
    write(root,'tests/test_contract.py',b'# source')
    model=write(root,'models/v02/model.pt',b'synthetic pinned model bytes')
    license=write(root,'models/v02/LICENSE.txt',b'synthetic license text')
    manifest={'selected_assets':[{'filename':'model.pt','sha256':sha(model.read_bytes()),'license_file':'LICENSE.txt','license_sha256':sha(license.read_bytes())}],'included_files':['model.pt','LICENSE.txt']}
    write(root,'models/v02/MODEL_MANIFEST.json',json.dumps(manifest).encode())
    image=write(root,'data/v02-evaluation/public.jpg',b'synthetic image bytes')
    fixtures={'files':[{'path':str(image.relative_to(root)),'sha256':sha(image.read_bytes()),'license':'Public domain','source_url':'https://example.test/public-source'}]}
    write(root,'data/v02-demo/DISTRIBUTION_MANIFEST.json',json.dumps(fixtures).encode())
    return root


def test_release_excludes_private_runtime_and_unselected_assets(package_tree):
    tool=load_tool('package_project.py');root=package_tree
    forbidden=['sentinal/.DS_Store','tests/.DS_Store','docs/.DS_Store','config/settings.json','config/v02.json','config/cameras/registry.sqlite3','recordings/incidents/evidence/a.jpg','logs/private.log','history/conversation.json','work/v02-network-tools/ffmpeg','models/v02/exploratory.pt','data/v02-demo/mixkit-raw.mp4','docs/runtime/secret.json','tests/__pycache__/x.pyc','docs/evidence/legacy-camera.json']
    for name in forbidden:write(root,name,b'private sentinel')
    approved=write(root,'docs/evidence/v02-test/hash-only-camera.json',b'{"camera_id_sha256":"test"}')
    files=set(tool.collect_release_files(root))
    assert all(root/name not in files for name in forbidden)
    assert approved in files
    assert root/'sentinal/vision.py' in files
    assert root/'data/v02-evaluation/public.jpg' in files
    assert root/'models/v02/model.pt' in files


@pytest.mark.parametrize('target',['models/v02/model.pt','models/v02/LICENSE.txt','data/v02-evaluation/public.jpg'])
def test_release_rejects_modified_pinned_bytes(package_tree,target):
    tool=load_tool('package_project.py');write(package_tree,target,b'altered')
    with pytest.raises(ValueError,match='checksum'):tool.collect_release_files(package_tree)


def test_release_rejects_fixture_traversal(package_tree):
    tool=load_tool('package_project.py');path=package_tree/'data/v02-demo/DISTRIBUTION_MANIFEST.json'
    values=json.loads(path.read_text());values['files'][0]['path']='../private.jpg';path.write_text(json.dumps(values))
    with pytest.raises(ValueError,match='escaped'):tool.collect_release_files(package_tree)


def test_release_rejects_raw_stock_media_even_if_mistakenly_listed(package_tree):
    tool=load_tool('package_project.py');path=package_tree/'data/v02-demo/DISTRIBUTION_MANIFEST.json'
    values=json.loads(path.read_text());values['files'][0]['license']='Mixkit Free License';path.write_text(json.dumps(values))
    with pytest.raises(ValueError,match='license'):tool.collect_release_files(package_tree)


def test_release_rejects_unselected_checkpoint_in_manifest(package_tree):
    tool=load_tool('package_project.py');write(package_tree,'models/v02/unknown.pt',b'unreviewed')
    path=package_tree/'models/v02/MODEL_MANIFEST.json';values=json.loads(path.read_text());values['included_files'].append('unknown.pt');path.write_text(json.dumps(values))
    with pytest.raises(ValueError,match='Unselected'):tool.collect_release_files(package_tree)


def test_release_rejects_symlinked_fixture(package_tree,tmp_path):
    tool=load_tool('package_project.py');fixture=package_tree/'data/v02-evaluation/public.jpg'
    other=tmp_path/'outside.jpg';other.write_bytes(fixture.read_bytes());fixture.unlink();fixture.symlink_to(other)
    with pytest.raises(ValueError,match='symlink'):tool.collect_release_files(package_tree)


def test_v02_verify_only_never_downloads(tmp_path,monkeypatch):
    module=load_tool('download_v02_models.py');monkeypatch.setattr(module,'ROOT',tmp_path)
    monkeypatch.setattr(module.urllib.request,'urlopen',lambda *a,**k:pytest.fail('network accessed'))
    with pytest.raises(ValueError,match='absent'):module.fetch('model.pt','https://example.test/model.pt','0'*64,verify_only=True)
    assert not (tmp_path/'models').exists()


def test_v02_valid_local_bytes_do_not_access_network(tmp_path,monkeypatch):
    module=load_tool('download_v02_models.py');monkeypatch.setattr(module,'ROOT',tmp_path)
    data=b'known local bytes';path=write(tmp_path,'models/v02/model.pt',data)
    monkeypatch.setattr(module.urllib.request,'urlopen',lambda *a,**k:pytest.fail('network accessed'))
    module.fetch('model.pt','https://example.test/model.pt',sha(data))
    assert path.read_bytes()==data


def test_v02_download_retry_succeeds_then_atomically_replaces(tmp_path,monkeypatch):
    from io import BytesIO
    module=load_tool('download_v02_models.py');monkeypatch.setattr(module,'ROOT',tmp_path);monkeypatch.setattr(module.time,'sleep',lambda _:None)
    path=write(tmp_path,'models/v02/model.pt',b'previous valid revision');attempts=[];fresh=b'new pinned revision'
    def download(*args,**kwargs):
        attempts.append(True)
        if len(attempts)<3:raise OSError('temporary network interruption')
        return BytesIO(fresh)
    monkeypatch.setattr(module.urllib.request,'urlopen',download)
    module.fetch('model.pt','https://example.test/model.pt',sha(fresh))
    assert len(attempts)==3 and path.read_bytes()==fresh
    assert not path.with_suffix('.pt.download-part').exists()


def test_v02_bad_download_preserves_previous_file(tmp_path,monkeypatch):
    from io import BytesIO
    module=load_tool('download_v02_models.py');monkeypatch.setattr(module,'ROOT',tmp_path)
    old=b'previous valid revision';path=write(tmp_path,'models/v02/model.pt',old)
    monkeypatch.setattr(module.urllib.request,'urlopen',lambda *a,**k:BytesIO(b'corrupted publisher response'))
    with pytest.raises(ValueError,match='checksum'):module.fetch('model.pt','https://example.test/model.pt',sha(b'expected new revision'))
    assert path.read_bytes()==old
    assert not path.with_suffix('.pt.download-part').exists()


def prepare_installer_contract(tmp_path,version_status):
    import os
    source=Path(__file__).resolve().parents[1]/'install.command'
    root=tmp_path/'project with spaces';root.mkdir()
    write(root,'install.command',source.read_bytes())
    write(root,'runtime-env.sh',b'# synthetic installer contract fixture; no dependencies or network\n')
    shell='''#!/bin/zsh
if [[ "$1" == "-c" ]]; then exit STATUS; fi
print -r -- "$*" >> calls.txt
exit 0
'''.replace('STATUS',str(version_status))
    executable=write(root,'.venv/bin/python',shell.encode());executable.chmod(0o755)
    return root


def test_installer_preserves_incompatible_environment_before_any_install(tmp_path):
    import subprocess
    root=prepare_installer_contract(tmp_path,1)
    result=subprocess.run(['/bin/zsh','install.command'],cwd=root,input='\n',text=True,capture_output=True,timeout=5)
    assert result.returncode==1
    assert 'requires Python 3.12' in result.stdout and 'preserved' in result.stdout
    assert (root/'.venv/bin/python').exists()
    assert not (root/'calls.txt').exists(),'Incompatible environment must not run pip or download tools'


def test_installer_in_space_path_runs_all_selected_model_installers(tmp_path):
    import subprocess
    root=prepare_installer_contract(tmp_path,0)
    result=subprocess.run(['/bin/zsh','install.command'],cwd=root,input='\n',text=True,capture_output=True,timeout=5)
    assert result.returncode==0,result.stderr
    calls=(root/'calls.txt').read_text().splitlines()
    assert calls[0].startswith('-m pip install ')
    assert 'tools/download_model.py' in calls
    assert 'tools/download_everyday_small.py' in calls
    assert 'tools/download_extended_model.py' in calls
    assert 'tools/download_small_extended_model.py' in calls
    assert 'tools/download_v02_models.py' in calls
    assert calls[-1]=='-m pip check'


def test_v021_package_includes_hashed_public_reported_items_and_current_evidence(package_tree):
    tool=load_tool('package_project.py');root=package_tree
    photo=write(root,'data/v021-items/scissors.jpg',b'public licensed test fixture')
    manifest={'files':[{'path':str(photo.relative_to(root)),'sha256':sha(photo.read_bytes()),'license':'CC BY 4.0','source_url':'https://example.test/source','author':'Fixture author'}]}
    write(root,'data/v021-items/DISTRIBUTION_MANIFEST.json',json.dumps(manifest).encode())
    evidence=write(root,'docs/evidence/v021-test/hash-only.json',b'{}')
    files=set(tool.collect_release_files(root))
    assert photo in files and evidence in files
    photo.write_bytes(b'changed')
    with pytest.raises(ValueError,match='checksum'):tool.collect_release_files(root)


def test_v021_package_rejects_private_or_unlicensed_item_fixture(package_tree):
    tool=load_tool('package_project.py');root=package_tree
    photo=write(root,'data/v021-items/unreviewed.jpg',b'unreviewed')
    manifest={'files':[{'path':str(photo.relative_to(root)),'sha256':sha(photo.read_bytes()),'license':'Unknown','source_url':'https://example.test/source','author':'Unknown'}]}
    write(root,'data/v021-items/DISTRIBUTION_MANIFEST.json',json.dumps(manifest).encode())
    with pytest.raises(ValueError,match='license'):tool.collect_release_files(root)


def test_v021_package_rejects_modified_optional_model(package_tree):
    tool=load_tool('package_project.py');root=package_tree
    write(root,'models/yolo11s.pt',b'wrong bytes')
    write(root,'models/yolo11s.source.json',b'{"sha256":"wrong"}')
    write(root,'models/yolo11s.sha256',b'wrong yolo11s.pt')
    with pytest.raises(ValueError,match='checksum'):tool.collect_release_files(root)
