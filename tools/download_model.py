"""Explicit installation-time download only. Never called by monitoring."""
from hashlib import sha256
from pathlib import Path
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt'


def main():
    target = ROOT / 'models/yolo11n.pt'
    target.parent.mkdir(exist_ok=True)
    checksum_file = ROOT / 'models/yolo11n.sha256'
    expected = checksum_file.read_text().split()[0] if checksum_file.exists() else None
    def valid(path):
        return path.is_file() and (expected is None or sha256(path.read_bytes()).hexdigest() == expected)
    if valid(target):
        print('Local model already present and checksum valid.')
        return
    temporary = target.with_suffix('.part')
    print('Downloading official YOLO11n weights for local inference...')
    try:
        with urlopen(URL, timeout=60) as response, temporary.open('wb') as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        if not valid(temporary):
            raise RuntimeError('Model checksum mismatch; incomplete/unexpected weights rejected.')
        temporary.replace(target)
        print('Model ready:', target)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        print(f'Model installation failed: {exc}. Check internet access and retry install.command.', file=sys.stderr)
        raise SystemExit(1)

if __name__ == '__main__':
    main()
