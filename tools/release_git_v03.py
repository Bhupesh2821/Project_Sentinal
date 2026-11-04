"""Create a source-only feature commit without changing the working tree/index.

The existing local initial commit contains model/cache/archive assets that must
not be pushed. A separate index creates a reviewed tree whose parent is fetched
remote main. Existing refs/files/index remain intact. Publication is explicit.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import shutil
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'https://github.com/Bhupesh2821/Project_Sentinal.git'
REMOTE_MAIN = 'refs/remotes/origin/main'
DEFAULT_BRANCH = 'feature/v03-connected-command-center'
AUTHOR_NAME = 'P. Bhupesh'
AUTHOR_EMAIL = '304970598+Bhupesh2821@users.noreply.github.com'
TOP_FILES = {
    '.gitignore', '.env.example', 'AGENTS.md', 'README.md', 'LICENSE',
    'LICENSE_NOTES.md', 'LOCATION.md', 'DEVELOPMENT_CHECKPOINT.md',
    'VERIFICATION_REPORT.md', 'RELEASE_NOTES.md', 'HACKATHON_DEMO.md',
    'requirements.txt', 'requirements-lock.txt', 'pytest.ini', 'main.py',
    'runtime-env.sh', 'install.command', 'launch.command', 'demo.command',
    'test.command', 'web.command', 'connected.command', 'package.json', 'package-lock.json',
    'SENTINAL_P_Bhupesh_SOLVIX26.pdf',
}
SOURCE_DIRS = ('sentinal', 'tests', 'tools', 'docs', 'web', 'frontend', 'base44', 'deployment')
BANNED_PARTS = {
    '.git', '.base44', '.codex', '.agents', '.venv', 'venv', 'node_modules', '__pycache__', '.pytest_cache',
    '.mypy_cache', '.ruff_cache', '.next', 'dist', 'build', 'coverage',
    'work', 'history', 'archives', 'recordings', 'logs', 'runtime',
}
BANNED_SUFFIXES = {'.pt', '.pth', '.onnx', '.safetensors', '.mlmodel', '.pyc', '.pyo',
                   '.zip', '.gz', '.tar', '.tgz', '.part', '.sqlite3', '.db', '.pem', '.key', '.p12', '.pfx'}
SECRET_PATTERNS = (
    re.compile(rb'(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9]{36,255}(?![A-Za-z0-9_])'),
    re.compile(rb'github_pat_[A-Za-z0-9_]{30,}'),
    re.compile(rb'AKIA[0-9A-Z]{16}'),
    re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    re.compile(rb'sk_live_[A-Za-z0-9]{16,}'),
)
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 75 * 1024 * 1024


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(root: Path, *args: str, data: bytes | None = None, env=None) -> bytes:
    result = subprocess.run(['git', *args], cwd=root, input=data, capture_output=True, env=env)
    if result.returncode:
        # Remote output is not included: it may contain endpoint credentials or
        # attacker-controlled text. Callers can inspect their local Git log.
        raise RuntimeError(f'Git {args[0]} failed with status {result.returncode}')
    return result.stdout


def authenticated_git(root: Path, *args: str) -> bytes:
    executable = shutil.which('gh')
    if not executable:
        raise ValueError('Authenticated GitHub CLI is required to publish')
    env = dict(os.environ)
    # The project redirects generic XDG caches/config. Read the already existing
    # shared GitHub account connection without changing that config or HOME.
    shared = Path.home() / '.config/gh'
    if not env.get('GH_CONFIG_DIR') and shared.is_dir():
        env['GH_CONFIG_DIR'] = str(shared)
    identity = subprocess.run([executable, 'api', 'user', '--jq', '.login'],
                              cwd=root, env=env, capture_output=True, text=True)
    if identity.returncode or identity.stdout.strip() != 'Bhupesh2821':
        raise ValueError('Reconnect the authorized Bhupesh2821 GitHub account before publishing')
    return git(root, '-c', 'credential.helper=', '-c',
               'credential.helper=!' + shlex.quote(executable) + ' auth git-credential',
               *args, env=env)


def checked_file(root: Path, relative: str) -> Path:
    fragment = Path(relative)
    if fragment.is_absolute() or '..' in fragment.parts or any(ord(c) < 32 for c in relative):
        raise ValueError('A source path is not a safe relative filename')
    path = root / fragment
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'Missing, external or symlinked source asset: {relative}')
    for parent in path.parents:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError('Source directories cannot be symlink aliases')
    return path


def permitted(relative: Path) -> bool:
    if any(part in BANNED_PARTS for part in relative.parts):
        return False
    if relative.name in {'.DS_Store','.app.jsonc'} or (relative.name.startswith('.env') and relative.name != '.env.example'):
        return False
    if relative.suffix.lower() in BANNED_SUFFIXES or relative.name.endswith(('-wal', '-shm', '.download-part')):
        return False
    # Raw integration evidence is retained locally/Drive rather than published
    # automatically. Root verification reports describe executed scope.
    if relative.parts[:2] == ('docs', 'evidence'):
        return False
    return True


def public_fixture_files(root: Path) -> set[Path]:
    files = set()
    for name in ('data/v02-demo/DISTRIBUTION_MANIFEST.json', 'data/v021-items/DISTRIBUTION_MANIFEST.json'):
        manifest = root / name
        if not manifest.exists():
            continue
        manifest = checked_file(root, name)
        records = json.loads(manifest.read_text()).get('files')
        if not isinstance(records, list) or not records:
            raise ValueError('Public fixture manifest is invalid')
        files.add(manifest)
        for record in records:
            relative = record['path']
            if Path(relative).parts[:2] not in {('data', 'v02-demo'), ('data', 'v02-evaluation'), ('data', 'v021-items')}:
                raise ValueError('Only reviewed public fixture folders may enter Git')
            path = checked_file(root, relative)
            if path.suffix.lower() in {'.jpg', '.jpeg', '.png', '.mp4', '.avi', '.webm', '.mov', '.wav'}:
                license_text = str(record.get('license', '')).lower()
                if not record.get('source_url') or not any(term in license_text for term in ('public domain', 'cc by', 'cc-by')):
                    raise ValueError('Public media needs reviewed source attribution and license')
            if digest(path.read_bytes()) != record['sha256']:
                raise ValueError('Public fixture hash changed; review before publication')
            files.add(path)
    return files


def collect_files(root: Path) -> list[Path]:
    root = root.resolve()
    files = {checked_file(root, name) for name in TOP_FILES if (root / name).exists()}
    for directory in SOURCE_DIRS:
        for path in (root / directory).rglob('*'):
            relative = path.relative_to(root)
            if path.is_file() and permitted(relative):
                files.add(checked_file(root, str(relative)))
    # Model source/class/license descriptors are small and reproducible. Model
    # binaries stay in approved asset storage and are installed by pinned tools.
    for path in (root / 'models').rglob('*'):
        if path.is_file() and (path.suffix in {'.json', '.sha256'} or (path.name.startswith('LICENSE') or path.name.endswith('-LICENSE.txt'))):
            if permitted(path.relative_to(root)):
                files.add(checked_file(root, str(path.relative_to(root))))
    files.update(public_fixture_files(root))
    total = 0
    for path in files:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ValueError(f'Source asset exceeds 10 MiB: {path.relative_to(root)}')
        total += size
        data = path.read_bytes()
        if any(pattern.search(data) for pattern in SECRET_PATTERNS):
            raise ValueError(f'Possible credential in source asset: {path.relative_to(root)}')
    if total > MAX_TOTAL_BYTES:
        raise ValueError('Source export exceeds its bounded reviewed size')
    return sorted(files)


def snapshot_entries(root: Path, files: list[Path]) -> list[dict]:
    return [{'path': str(path.relative_to(root)), 'bytes': path.stat().st_size,
             'sha256': digest(path.read_bytes()), 'mode': '100755' if path.stat().st_mode & stat.S_IXUSR else '100644'}
            for path in files]


def prepare(root: Path, branch: str, parent: str, message: str) -> dict:
    root = root.resolve()
    git(root, 'check-ref-format', '--branch', branch)
    if branch in {'main', 'master'}:
        raise ValueError('Prepare a dedicated feature branch')
    ref = 'refs/heads/' + branch
    current_refs = git(root, 'for-each-ref', '--format=%(refname)').decode().splitlines()
    if ref in current_refs:
        raise ValueError('Feature branch already exists; choose a new branch name')
    if parent != REMOTE_MAIN:
        raise ValueError('Use fetched origin/main as the only snapshot parent')
    parent_sha = git(root, 'rev-parse', '--verify', parent + '^{commit}').decode().strip()
    original_head = git(root, 'rev-parse', 'HEAD').decode().strip()
    index = root / '.git/index'
    before_index = digest(index.read_bytes()) if index.exists() else None
    files = collect_files(root)
    entries = snapshot_entries(root, files)
    scratch = root / 'work/git-v03'
    if not scratch.resolve().is_relative_to(root):
        raise ValueError('Git temporary files must remain inside the project')
    scratch.mkdir(parents=True, exist_ok=True)
    handle, index_name = tempfile.mkstemp(prefix='source-index-', dir=scratch)
    os.close(handle)
    temporary_index = Path(index_name)
    temporary_index.unlink()  # read-tree creates a new valid index.
    env = {**os.environ, 'GIT_INDEX_FILE': str(temporary_index)}
    try:
        git(root, 'read-tree', '--empty', env=env)
        records = []
        for entry in entries:
            path = checked_file(root, entry['path'])
            data = path.read_bytes()
            if digest(data) != entry['sha256']:
                raise ValueError('Source changed while preparing; retry after development stops')
            blob = git(root, 'hash-object', '-w', '--stdin', data=data).decode().strip()
            records.append(f"{entry['mode']} {blob}\t{entry['path']}\0".encode())
        git(root, 'update-index', '-z', '--index-info', data=b''.join(records), env=env)
        tree = git(root, 'write-tree', env=env).decode().strip()
        commit_env = {**os.environ, 'GIT_AUTHOR_NAME': AUTHOR_NAME, 'GIT_AUTHOR_EMAIL': AUTHOR_EMAIL,
                      'GIT_COMMITTER_NAME': AUTHOR_NAME, 'GIT_COMMITTER_EMAIL': AUTHOR_EMAIL}
        commit = git(root, 'commit-tree', tree, '-p', parent_sha, data=(message.rstrip() + '\n').encode(), env=commit_env).decode().strip()
        git(root, 'update-ref', ref, commit, '')
    finally:
        temporary_index.unlink(missing_ok=True)
        temporary_index.with_suffix(temporary_index.suffix + '.lock').unlink(missing_ok=True)
    if git(root, 'rev-parse', 'HEAD').decode().strip() != original_head:
        raise RuntimeError('Current working branch unexpectedly changed')
    if (digest(index.read_bytes()) if index.exists() else None) != before_index:
        raise RuntimeError('Current working index unexpectedly changed')
    return {'prepared_utc': datetime.now(timezone.utc).isoformat(), 'repository': REPOSITORY,
            'branch': branch, 'commit': commit, 'parent': parent_sha, 'tree': tree,
            'local_working_head_preserved': original_head, 'index_unchanged': True,
            'files': entries, 'bytes': sum(entry['bytes'] for entry in entries), 'pushed': False}


def verify_commit_snapshot(root: Path, commit: str, entries: list[dict]):
    actual = {}
    for raw in git(root, 'ls-tree', '-rz', '--full-tree', commit).split(b'\0'):
        if not raw:
            continue
        metadata, path = raw.split(b'\t', 1)
        mode, kind, blob = metadata.decode().split()
        if kind != 'blob':
            raise ValueError('Source snapshots cannot contain submodule entries')
        size = int(git(root, 'cat-file', '-s', blob))
        if size > MAX_FILE_BYTES:
            raise ValueError('Committed source asset exceeds the publication limit')
        actual[path.decode()] = {'mode': mode, 'bytes': size,
                                 'sha256': digest(git(root, 'cat-file', 'blob', blob))}
    expected = {entry['path']: {key: entry[key] for key in ('mode', 'bytes', 'sha256')} for entry in entries}
    if actual != expected:
        raise ValueError('Committed tree does not match the reviewed source manifest')


def push(root: Path, report: dict) -> dict:
    if report.get('repository') != REPOSITORY or not report.get('index_unchanged'):
        raise ValueError('Use the verified source snapshot report')
    remote_url = git(root, 'remote', 'get-url', 'origin').decode().strip()
    if remote_url not in {REPOSITORY, REPOSITORY.removesuffix('.git'), 'git@github.com:Bhupesh2821/Project_Sentinal.git'}:
        raise ValueError('Origin is not the authorized project repository')
    branch = report['branch']
    git(root, 'check-ref-format', '--branch', branch)
    ref = 'refs/heads/' + branch
    commit = git(root, 'rev-parse', '--verify', ref).decode().strip()
    if commit != report['commit']:
        raise ValueError('Feature branch no longer matches its prepared report')
    parents = git(root, 'rev-list', '--parents', '-n', '1', commit).decode().split()
    if parents != [commit, report['parent']]:
        raise ValueError('Prepared commit does not preserve the audited remote parent')
    current = snapshot_entries(root, collect_files(root))
    if current != report['files']:
        raise ValueError('Source changed since snapshot; prepare a new reviewed branch')
    verify_commit_snapshot(root, commit, current)
    remote = authenticated_git(root, 'ls-remote', '--heads', 'origin', 'refs/heads/main', ref).decode().splitlines()
    remote_refs = dict(line.split('\t')[::-1] for line in remote if '\t' in line)
    if remote_refs.get('refs/heads/main') != report['parent']:
        raise ValueError('Remote main changed; compare it before preparing a new snapshot')
    if ref in remote_refs and remote_refs[ref] != commit:
        raise ValueError('Remote feature branch exists with other work; no overwrite allowed')
    authenticated_git(root, 'push', '--porcelain', 'origin', ref + ':' + ref)
    verified = authenticated_git(root, 'ls-remote', '--heads', 'origin', ref).decode().split()
    if not verified or verified[0] != commit:
        raise RuntimeError('Remote branch readback did not match')
    return {**report, 'pushed': True, 'verified_remote_commit': commit,
            'verified_utc': datetime.now(timezone.utc).isoformat()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare', action='store_true', help='Create a new source-only feature commit, without publishing')
    mode.add_argument('--push', action='store_true', help='Explicitly publish the already prepared source snapshot')
    parser.add_argument('--branch', default=DEFAULT_BRANCH)
    parser.add_argument('--parent', default=REMOTE_MAIN)
    parser.add_argument('--message', default='feat(v0.3): connect local AI events to an authenticated command center')
    parser.add_argument('--report', default='docs/evidence/v03-2026-11-03/github-source-snapshot.json')
    args = parser.parse_args()
    report_path = (ROOT / args.report).resolve()
    if not report_path.is_relative_to(ROOT):
        raise ValueError('Snapshot reports must remain inside the project')
    if args.push:
        report = push(ROOT, json.loads(report_path.read_text()))
    elif args.prepare:
        report = prepare(ROOT, args.branch, args.parent, args.message)
    else:
        entries = snapshot_entries(ROOT, collect_files(ROOT))
        print(json.dumps({'dry_run': True, 'files': len(entries), 'bytes': sum(row['bytes'] for row in entries), 'publication': False}, indent=2))
        return 0
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'files'}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
