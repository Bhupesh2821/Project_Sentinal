"""Explicit one-time pinned model installation; normal inference is offline."""
import argparse
import hashlib
from pathlib import Path
import sys
import urllib.request
import urllib.error
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sentinal.config import ROOT
from sentinal.vision.model_registry import ASSETS

LICENSES={
 'weapons':('weapon_ginger-LICENSE.txt','https://raw.githubusercontent.com/GingerBrains/object-detection/ab6f53c8d18d77d799fa70a46adea646d7bb4499/LICENSE','3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986'),
 'fire_smoke':('fire_smoke-LICENSE.txt','https://raw.githubusercontent.com/luminous0219/fire-and-smoke-detection-yolov8/c30923f568d915a53fcf85989be9fe5d4e030518/LICENSE','8486a10c4393cee1c25392769ddd3b2d6c242d6ec7928e1414efff7dfb2f07ef'),
}

def digest(path):
    if not path.is_file():return None
    with path.open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()


def fetch(filename,url,sha256,verify_only=False):
    path=ROOT/'models/v02'/filename
    if digest(path)==sha256:
        print(filename+': checksum verified');return
    if verify_only:raise ValueError(filename+': absent or checksum mismatch')
    path.parent.mkdir(parents=True,exist_ok=True)
    partial=path.with_suffix(path.suffix+'.download-part')
    try:
        last_error=None
        for attempt in range(3):
            try:
                request=urllib.request.Request(url,headers={'User-Agent':'SENTINAL/0.2 explicit-model-installer'})
                total=0
                with urllib.request.urlopen(request,timeout=60) as response,partial.open('wb') as handle:
                    while chunk:=response.read(1024*1024):
                        total+=len(chunk)
                        if total>64*1024*1024:raise ValueError('Download exceeds64MB model bound')
                        handle.write(chunk)
                if digest(partial)!=sha256:raise ValueError(filename+': publisher bytes do not match pinned checksum')
                partial.replace(path)
                print(filename+': installed and checksum verified')
                return
            except Exception as exc:
                last_error=exc
                partial.unlink(missing_ok=True)
                if isinstance(exc,ValueError):raise
                if isinstance(exc,urllib.error.HTTPError) and exc.code not in {408,429,500,502,503,504}:raise
                if attempt<2:time.sleep(.5*(2**attempt))
        raise last_error
    finally:
        partial.unlink(missing_ok=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only',action='store_true',help='Never access the network; verify local selected weights and license files')
    args=parser.parse_args(argv)
    try:
        for key,asset in ASSETS.items():
            fetch(asset.filename,asset.source_url,asset.sha256,args.verify_only)
            fetch(*LICENSES[key],verify_only=args.verify_only)
        return 0
    except Exception as exc:
        print('V0.2 model installation failed: '+str(exc),file=sys.stderr)
        return 1

if __name__=='__main__':raise SystemExit(main())
