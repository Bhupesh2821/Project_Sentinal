"""Explicit one-time installation of the higher-capacity local object model."""
from hashlib import sha256
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
URL = "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8s-oiv7.pt"
EXPECTED = "4663086e1b8edbc4202a9ec589b03195ed149ef8aa8beeb4b503e0e35ff1731a"


def main():
    target = ROOT / "models/yolov8s-oiv7.pt"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and sha256(target.read_bytes()).hexdigest() == EXPECTED:
        print("Expanded model already installed and checksum verified.")
        return
    partial = target.with_suffix(".part")
    try:
        print("Downloading the official local expanded object model…", flush=True)
        with urlopen(URL, timeout=60) as response, partial.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        if sha256(partial.read_bytes()).hexdigest() != EXPECTED:
            raise RuntimeError("The downloaded model checksum did not match; it was rejected.")
        partial.replace(target)
        print("Expanded safety / tool model installed locally.")
    finally:
        partial.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
