"""Explicit install of official YOLO11s; pinned GitHub asset SHA256, no runtime fetch."""
from pathlib import Path
import hashlib,json,sys,time
import requests
ROOT=Path(__file__).resolve().parents[1]
URL='https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo11s.pt'
SHA256='85a76fe86dd8afe384648546b56a7a78580c7cb7b404fc595f97969322d502d5'

def digest(path):
    if not path.is_file():return None
    with path.open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()

def main():
    target=ROOT/'models/yolo11s.pt';temporary=target.with_suffix('.download-part')
    if digest(target)==SHA256:
        (ROOT/'models/yolo11s.sha256').write_text(SHA256+'  yolo11s.pt\n')
        print('YOLO11s local checksum verified');return 0
    target.parent.mkdir(parents=True,exist_ok=True)
    try:
        for attempt in range(3):
            try:
                with requests.get(URL,stream=True,timeout=60) as response,temporary.open('wb') as output:
                    response.raise_for_status();total=0
                    for chunk in response.iter_content(1024*1024):
                        total+=len(chunk)
                        if total>32*1024**2:raise ValueError('Official model exceeds expected size bound')
                        output.write(chunk)
                if digest(temporary)!=SHA256:raise ValueError('Official model checksum mismatch')
                temporary.replace(target)
                (ROOT/'models/yolo11s.sha256').write_text(SHA256+'  yolo11s.pt\n')
                print('Installed official YOLO11s; checksum verified');return 0
            except requests.RequestException:
                if attempt==2:raise
                time.sleep(.5*(attempt+1))
    finally:temporary.unlink(missing_ok=True)
if __name__=='__main__':raise SystemExit(main())
