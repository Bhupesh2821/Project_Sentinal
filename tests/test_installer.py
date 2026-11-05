"""Installation-time failures do not leave partial model files or use runtime inference."""
import importlib.util
from pathlib import Path
import pytest


def load_downloader():
    path=Path(__file__).resolve().parents[1]/'tools/download_model.py'
    spec=importlib.util.spec_from_file_location('sentinal_test_downloader',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_download_failure_removes_partial_and_explains_retry(tmp_path,monkeypatch,capsys):
    module=load_downloader()
    monkeypatch.setattr(module,'ROOT',tmp_path)
    def unavailable(*args,**kwargs):
        raise OSError('offline test')
    monkeypatch.setattr(module,'urlopen',unavailable)
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code==1
    assert not (tmp_path/'models/yolo11n.part').exists()
    assert not (tmp_path/'models/yolo11n.pt').exists()
    assert 'retry install.command' in capsys.readouterr().err


def test_unexpected_model_bytes_fail_checksum_before_publish(tmp_path,monkeypatch):
    from io import BytesIO
    module=load_downloader()
    monkeypatch.setattr(module,'ROOT',tmp_path)
    (tmp_path/'models').mkdir()
    (tmp_path/'models/yolo11n.sha256').write_text('0'*64+'  yolo11n.pt\n')
    monkeypatch.setattr(module,'urlopen',lambda *args,**kwargs:BytesIO(b'not the official model'))
    with pytest.raises(SystemExit):
        module.main()
    assert not (tmp_path/'models/yolo11n.pt').exists()
    assert not (tmp_path/'models/yolo11n.part').exists()


def load_optional_downloader():
    path=Path(__file__).resolve().parents[1]/'tools/download_everyday_small.py'
    spec=importlib.util.spec_from_file_location('sentinal_test_optional_downloader',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def test_optional_model_valid_local_bytes_restore_pin_without_network(tmp_path,monkeypatch):
    import hashlib
    module=load_optional_downloader();monkeypatch.setattr(module,'ROOT',tmp_path)
    data=b'known pinned fixture, not model weights';expected=hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(module,'SHA256',expected)
    path=tmp_path/'models/yolo11s.pt';path.parent.mkdir();path.write_bytes(data)
    monkeypatch.setattr(module.requests,'get',lambda *a,**k:pytest.fail('Unexpected network access'))
    assert module.main()==0
    assert (path.parent/'yolo11s.sha256').read_text().split()[0]==expected


def test_optional_model_corrupt_response_preserves_previous_bytes(tmp_path,monkeypatch):
    import hashlib
    module=load_optional_downloader();monkeypatch.setattr(module,'ROOT',tmp_path)
    monkeypatch.setattr(module,'SHA256',hashlib.sha256(b'expected new bytes').hexdigest())
    target=tmp_path/'models/yolo11s.pt';target.parent.mkdir();target.write_bytes(b'previous installation')
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def raise_for_status(self):pass
        def iter_content(self,*args):yield b'corrupt response'
    monkeypatch.setattr(module.requests,'get',lambda *a,**k:Response())
    with pytest.raises(ValueError,match='checksum'):module.main()
    assert target.read_bytes()==b'previous installation'
    assert not target.with_suffix('.download-part').exists()


def test_optional_model_bounded_connection_retries_clean_partial(tmp_path,monkeypatch):
    module=load_optional_downloader();monkeypatch.setattr(module,'ROOT',tmp_path)
    attempts=[]
    def unavailable(*args,**kwargs):
        attempts.append(True);raise module.requests.ConnectionError('Offline test fixture')
    monkeypatch.setattr(module.requests,'get',unavailable);monkeypatch.setattr(module.time,'sleep',lambda _:None)
    with pytest.raises(module.requests.ConnectionError):module.main()
    assert len(attempts)==3
    assert not (tmp_path/'models/yolo11s.download-part').exists()
    assert not (tmp_path/'models/yolo11s.pt').exists()
