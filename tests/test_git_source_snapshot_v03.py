"""Source publication boundaries. Tests never publish or contact GitHub."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import pytest


def load_tool():
    path = Path(__file__).resolve().parents[1] / 'tools/release_git_v03.py'
    spec = importlib.util.spec_from_file_location('sentinal_git_export_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(root, name, data=b'public source'):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def command(root, *args):
    return subprocess.check_output(['git', *args], cwd=root).decode().strip()


def test_allowlist_excludes_private_runtime_credentials_and_model_binaries(tmp_path):
    tool = load_tool()
    approved = [write(tmp_path, 'main.py'), write(tmp_path, 'sentinal/engine.py'),
                write(tmp_path, 'web/app.js'), write(tmp_path, 'models/model.source.json'),
                write(tmp_path, 'models/LICENSE.txt'),
                write(tmp_path, 'models/v02/weapon_ginger-LICENSE.txt')]
    blocked = ['config/connected/device.json', 'work/cache/private.py', 'history/chat.md',
               'recordings/private.jpg', 'archives/release.zip', 'models/model.pt',
               'frontend/command-center/.app.jsonc', 'web/.env.local', 'web/node_modules/private.js', 'web/dist/private.js',
               'sentinal/__pycache__/module.pyc', 'docs/evidence/v03/private.json']
    for name in blocked:
        write(tmp_path, name)
    assert tool.collect_files(tmp_path) == sorted(approved)


def test_external_source_symlink_is_rejected(tmp_path):
    tool = load_tool()
    root = tmp_path / 'project'; root.mkdir()
    external = write(tmp_path, 'outside.txt')
    (root / 'sentinal').mkdir(); (root / 'sentinal/link.py').symlink_to(external)
    with pytest.raises(ValueError, match='symlinked'):
        tool.collect_files(root)


def test_tampered_fixture_and_path_escape_are_rejected(tmp_path):
    tool = load_tool()
    media = write(tmp_path, 'data/v021-items/public.jpg', b'approved picture')
    record = {'path': 'data/v021-items/public.jpg', 'license':'CC BY 4.0', 'source_url':'https://example.invalid/public-credit', 'sha256': hashlib.sha256(media.read_bytes()).hexdigest()}
    manifest = write(tmp_path, 'data/v021-items/DISTRIBUTION_MANIFEST.json', json.dumps({'files':[record]}).encode())
    assert media in tool.collect_files(tmp_path)
    media.write_bytes(b'altered')
    with pytest.raises(ValueError, match='hash changed'):
        tool.collect_files(tmp_path)
    record['path'] = '../../outside.jpg'
    manifest.write_text(json.dumps({'files':[record]}))
    with pytest.raises(ValueError, match='reviewed public fixture'):
        tool.collect_files(tmp_path)


def test_high_confidence_secret_rejected_without_disclosing_it(tmp_path):
    tool = load_tool()
    token = 'ghp_' + 'x' * 40
    write(tmp_path, 'web/app.js', ('token='+token).encode())
    with pytest.raises(ValueError, match='Possible credential') as error:
        tool.collect_files(tmp_path)
    assert token not in str(error.value)


def test_ghs_category_names_do_not_look_like_github_tokens(tmp_path):
    tool = load_tool()
    public = write(tmp_path, 'tests/test_names.py', b'def test_missing_optional_ghs_is_disabled_in_settings(): pass')
    assert tool.collect_files(tmp_path) == [public]


def test_oversized_source_file_is_rejected(tmp_path, monkeypatch):
    tool = load_tool(); monkeypatch.setattr(tool, 'MAX_FILE_BYTES', 10)
    write(tmp_path, 'web/app.js', b'x'*11)
    with pytest.raises(ValueError, match='exceeds 10 MiB'):
        tool.collect_files(tmp_path)


@pytest.fixture
def repository(tmp_path):
    command(tmp_path, 'init', '-q')
    command(tmp_path, 'config', 'user.name', 'Local test author')
    command(tmp_path, 'config', 'user.email', 'test@example.invalid')
    write(tmp_path, 'main.py', b'# initial public source')
    write(tmp_path, 'work/cache/private.bin', b'private cache retained locally')
    command(tmp_path, 'add', '.')
    command(tmp_path, 'commit', '-qm', 'Local oversized-history stand-in')
    empty_tree = command(tmp_path, 'mktree')
    remote = subprocess.check_output(['git', 'commit-tree', empty_tree, '-m', 'Remote baseline'], cwd=tmp_path).decode().strip()
    command(tmp_path, 'update-ref', 'refs/remotes/origin/main', remote)
    return tmp_path, remote


def test_preparation_uses_remote_parent_and_keeps_local_head_index_and_files(repository):
    root, remote = repository; tool = load_tool()
    write(root, 'main.py', b'# current source update')
    write(root, 'web/app.js', b'export const version = "test";')
    command(root, 'add', 'main.py')  # Deliberate staged user changes must survive.
    local_head = command(root, 'rev-parse', 'HEAD')
    index = (root/'.git/index').read_bytes()
    cache = (root/'work/cache/private.bin').read_bytes()
    report = tool.prepare(root, 'feature/test-publication', tool.REMOTE_MAIN, 'Test source snapshot')
    assert command(root, 'rev-parse', 'HEAD') == local_head
    assert (root/'.git/index').read_bytes() == index
    assert (root/'work/cache/private.bin').read_bytes() == cache
    assert command(root, 'show', '-s', '--format=%P', report['commit']) == remote
    names = command(root, 'ls-tree', '-r', '--name-only', report['commit']).splitlines()
    assert names == ['main.py', 'web/app.js']
    assert report['pushed'] is False and report['index_unchanged']
    assert command(root, 'show', '-s', '--format=%ae', report['commit']) == tool.AUTHOR_EMAIL
    assert command(root, 'config', 'user.name') == 'Local test author'
    with pytest.raises(ValueError, match='already exists'):
        tool.prepare(root, 'feature/test-publication', tool.REMOTE_MAIN, 'Do not overwrite')


def test_preparation_rejects_local_oversized_history_as_parent(repository):
    root, _ = repository; tool = load_tool()
    with pytest.raises(ValueError, match='origin/main'):
        tool.prepare(root, 'feature/wrong-parent', 'HEAD', 'Wrong parent')


def test_changed_source_blocks_publication_before_network(repository, monkeypatch):
    root, _ = repository; tool = load_tool()
    command(root, 'remote', 'add', 'origin', tool.REPOSITORY)
    report = tool.prepare(root, 'feature/test-no-network', tool.REMOTE_MAIN, 'Test')
    write(root, 'main.py', b'# changed after preparation')
    called=[]; monkeypatch.setattr(tool, 'authenticated_git', lambda *a: called.append(a))
    with pytest.raises(ValueError, match='Source changed since'):
        tool.push(root, report)
    assert called == []


def test_other_remote_is_rejected_before_network(repository, monkeypatch):
    root, _ = repository; tool = load_tool()
    command(root, 'remote', 'add', 'origin', 'https://example.invalid/another/repo.git')
    report = tool.prepare(root, 'feature/test-wrong-remote', tool.REMOTE_MAIN, 'Test')
    called=[]; monkeypatch.setattr(tool, 'authenticated_git', lambda *a: called.append(a))
    with pytest.raises(ValueError, match='authorized project'):
        tool.push(root, report)
    assert called == []


def test_manifest_with_unattributed_media_is_rejected(tmp_path):
    tool=load_tool()
    media=write(tmp_path,'data/v021-items/public.jpg',b'picture')
    manifest={'files':[{'path':'data/v021-items/public.jpg','sha256':hashlib.sha256(media.read_bytes()).hexdigest()}]}
    write(tmp_path,'data/v021-items/DISTRIBUTION_MANIFEST.json',json.dumps(manifest).encode())
    with pytest.raises(ValueError,match='attribution and license'):
        tool.collect_files(tmp_path)


def test_committed_tree_is_verified_against_manifest(repository):
    root,_=repository;tool=load_tool()
    report=tool.prepare(root,'feature/test-tree-integrity',tool.REMOTE_MAIN,'Test')
    tool.verify_commit_snapshot(root,report['commit'],report['files'])
    wrong=[{**entry,'sha256':'0'*64} for entry in report['files']]
    with pytest.raises(ValueError,match='Committed tree'):
        tool.verify_commit_snapshot(root,report['commit'],wrong)
