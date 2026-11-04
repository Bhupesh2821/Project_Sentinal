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


@pytest.fixture
def published(repository):
    root, main = repository
    tool = load_tool()
    command(root, 'remote', 'add', 'origin', tool.REPOSITORY)
    report = tool.prepare(root, 'feature/test-incremental', tool.REMOTE_MAIN, 'Published milestone')
    report = {**report, 'pushed': True, 'verified_remote_commit': report['commit']}
    return root, main, tool, report


def simulated_remote(tool, monkeypatch, main, branch, commit):
    remote = {'refs/heads/main': main, 'refs/heads/'+branch: commit}
    calls = []
    def authenticated(root, *args):
        calls.append(args)
        if args[0] == 'ls-remote':
            return ''.join(f'{sha}\t{ref}\n' for ref,sha in remote.items() if ref in args[3:]).encode()
        if args[0] == 'push':
            assert args == ('push', '--porcelain', 'origin', 'refs/heads/'+branch+':refs/heads/'+branch)
            remote['refs/heads/'+branch] = command(root, 'rev-parse', 'refs/heads/'+branch)
            return b'published test source'
        raise AssertionError('Unexpected authenticated operation')
    monkeypatch.setattr(tool, 'authenticated_git', authenticated)
    return remote, calls


def test_incremental_snapshot_preserves_index_head_files_and_correct_history(published, monkeypatch):
    root, main, tool, previous = published
    simulated_remote(tool, monkeypatch, main, previous['branch'], previous['commit'])
    old_report = json.dumps(previous, sort_keys=True)
    write(root, 'main.py', b'# revised actual source')
    command(root, 'add', 'main.py')
    write(root, 'web/new.js', b'export const updated = true;')
    index = (root/'.git/index').read_bytes()
    head = command(root, 'rev-parse', 'HEAD')
    private = (root/'work/cache/private.bin').read_bytes()
    result = tool.update(root, previous, 'fix: improve access and native application')
    assert result['mode'] == 'incremental_snapshot'
    assert result['parent'] == previous['commit'] and result['base_main'] == main
    assert result['previous_published_commit'] == previous['commit']
    assert command(root, 'show', '-s', '--format=%P', result['commit']) == previous['commit']
    assert command(root, 'show', '-s', '--format=%P', previous['commit']) == main
    assert command(root, 'rev-parse', 'HEAD') == head
    assert (root/'.git/index').read_bytes() == index
    assert (root/'work/cache/private.bin').read_bytes() == private
    assert (root/'main.py').read_bytes() == b'# revised actual source'
    assert json.dumps(previous, sort_keys=True) == old_report
    assert command(root, 'ls-tree', '-r', '--name-only', result['commit']).splitlines() == ['main.py','web/new.js']
    tool.verify_commit_snapshot(root, result['commit'], result['files'])


@pytest.mark.parametrize('changed',['feature','main'])
def test_incremental_preparation_rejects_changed_remote_without_moving_ref(published, monkeypatch, changed):
    root, main, tool, previous = published
    remote, calls = simulated_remote(tool, monkeypatch, main, previous['branch'], previous['commit'])
    remote['refs/heads/'+(previous['branch'] if changed == 'feature' else 'main')] = 'f'*40
    index = (root/'.git/index').read_bytes()
    with pytest.raises(ValueError, match='Remote .* changed'):
        tool.update(root, previous, 'Must compare changed work first')
    assert command(root, 'rev-parse', 'refs/heads/'+previous['branch']) == previous['commit']
    assert (root/'.git/index').read_bytes() == index
    assert all(call[0] == 'ls-remote' for call in calls)


def test_incremental_preparation_requires_previous_verified_publication(published, monkeypatch):
    root, main, tool, previous = published
    called=[];monkeypatch.setattr(tool,'authenticated_git',lambda *a:called.append(a))
    for invalid in ({**previous,'pushed':False},{**previous,'verified_remote_commit':'f'*40}):
        with pytest.raises(ValueError,match='previously published'):
            tool.update(root,invalid,'Cannot use an unverified predecessor')
    assert called == []


def test_incremental_preparation_ref_cas_preserves_concurrent_local_work(published, monkeypatch):
    root, main, tool, previous = published
    simulated_remote(tool, monkeypatch, main, previous['branch'], previous['commit'])
    ref='refs/heads/'+previous['branch']
    tree=command(root,'show','-s','--format=%T',previous['commit'])
    concurrent=command(root,'commit-tree',tree,'-p',previous['commit'],'-m','Concurrent local feature work')
    original=tool.git
    def racing_git(location,*args,**kwargs):
        if args[0]=='update-ref' and args[1]==ref:
            command(root,'update-ref',ref,concurrent,previous['commit'])
        return original(location,*args,**kwargs)
    monkeypatch.setattr(tool,'git',racing_git)
    head=command(root,'rev-parse','HEAD');index=(root/'.git/index').read_bytes()
    with pytest.raises(RuntimeError,match='update-ref failed'):
        tool.update(root,previous,'Do not overwrite concurrent work')
    assert command(root,'rev-parse',ref)==concurrent
    assert command(root,'rev-parse','HEAD')==head
    assert (root/'.git/index').read_bytes()==index


def test_incremental_preparation_refuses_checked_out_publication_branch(published, monkeypatch):
    root,main,tool,previous=published
    simulated_remote(tool,monkeypatch,main,previous['branch'],previous['commit'])
    command(root,'symbolic-ref','HEAD','refs/heads/'+previous['branch'])
    head=command(root,'rev-parse','HEAD');index=(root/'.git/index').read_bytes()
    with pytest.raises(ValueError,match='checked out'):
        tool.update(root,previous,'Cannot alter the active working branch')
    assert command(root,'rev-parse','HEAD')==head
    assert (root/'.git/index').read_bytes()==index


def test_incremental_push_is_fast_forward_read_back_and_idempotent(published, monkeypatch):
    root,main,tool,previous=published
    remote,calls=simulated_remote(tool,monkeypatch,main,previous['branch'],previous['commit'])
    write(root,'main.py',b'# second verified version')
    report=tool.update(root,previous,'Second source-only milestone')
    pushed=tool.push(root,report)
    assert pushed['pushed'] and pushed['verified_remote_commit']==report['commit']
    assert remote['refs/heads/'+previous['branch']]==report['commit']
    assert all(not any('force' in value for value in call) for call in calls)
    assert tool.push(root,report)['verified_remote_commit']==report['commit']


def test_incremental_push_rejects_changed_remote_before_upload(published, monkeypatch):
    root,main,tool,previous=published
    remote,calls=simulated_remote(tool,monkeypatch,main,previous['branch'],previous['commit'])
    write(root,'main.py',b'# new version')
    report=tool.update(root,previous,'Prepared incremental version')
    remote['refs/heads/'+previous['branch']]='f'*40
    with pytest.raises(ValueError,match='Remote feature branch changed'):
        tool.push(root,report)
    assert all(call[0]!='push' for call in calls)


def test_incremental_push_rejects_changed_source_before_network(published, monkeypatch):
    root,main,tool,previous=published
    remote,calls=simulated_remote(tool,monkeypatch,main,previous['branch'],previous['commit'])
    report=tool.update(root,previous,'Prepared source')
    write(root,'main.py',b'# source changed after preparation')
    calls.clear()
    with pytest.raises(ValueError,match='Source changed since'):
        tool.push(root,report)
    assert calls==[]


def test_incremental_cli_preserves_existing_report_before_any_git_operation(tmp_path,monkeypatch):
    import sys
    tool=load_tool();monkeypatch.setattr(tool,'ROOT',tmp_path)
    report=write(tmp_path,'docs/evidence/existing.json',b'{"preserve":"previous verified report"}')
    monkeypatch.setattr(sys,'argv',['release_git_v03.py','--update','--previous-report','previous.json','--report','docs/evidence/existing.json'])
    with pytest.raises(ValueError,match='report already exists'):
        tool.main()
    assert report.read_bytes()==b'{"preserve":"previous verified report"}'


def test_incremental_publication_against_real_isolated_bare_repository(published, tmp_path, monkeypatch):
    """Exercise actual Git FF transport/readback without contacting any network."""
    root, main, tool, previous = published
    bare = tmp_path/'isolated-remote.git'
    command(root,'init','--bare','-q',str(bare))
    # The authenticated-transport seam selects this real local remote; the
    # authorized origin validation and all other Git operations remain real.
    command(root,'push','-q',str(bare),tool.REMOTE_MAIN+':refs/heads/main')
    ref='refs/heads/'+previous['branch']
    command(root,'push','-q',str(bare),ref+':'+ref)
    monkeypatch.setattr(tool,'authenticated_git',lambda location,*args:tool.git(location,*(str(bare) if value=='origin' else value for value in args)))
    write(root,'main.py',b'# current code for actual local transport')
    head=command(root,'rev-parse','HEAD');index=(root/'.git/index').read_bytes()
    update=tool.update(root,previous,'Verified incremental snapshot through local bare Git')
    result=tool.push(root,update)
    assert result['verified_remote_commit']==update['commit']
    assert command(bare,'rev-parse',ref)==update['commit']
    assert command(bare,'show','-s','--format=%P',update['commit'])==previous['commit']
    assert command(bare,'rev-parse','refs/heads/main')==main
    assert command(root,'rev-parse','HEAD')==head
    assert (root/'.git/index').read_bytes()==index
    assert command(bare,'rev-list','--count',ref)== '3'
