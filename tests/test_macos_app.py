"""Build boundary checks; native launch/inference evidence is separate."""
import pytest
from tools import build_macos_app


def test_native_builder_rejects_output_outside_project_before_compiling(tmp_path,monkeypatch):
    invoked=[]
    monkeypatch.setattr(build_macos_app,'run',lambda *a,**k:invoked.append(a))
    monkeypatch.setattr(build_macos_app.sys,'platform','darwin')
    canonical=tmp_path/'project';canonical.mkdir()
    monkeypatch.setattr(build_macos_app,'ROOT',canonical)
    with pytest.raises(ValueError,match='inside the canonical project'):
        build_macos_app.build(tmp_path/'Unrelated.app')
    assert not invoked and not (tmp_path/'Unrelated.app').exists()


def test_native_builder_requires_application_bundle_output(monkeypatch):
    invoked=[]
    monkeypatch.setattr(build_macos_app,'run',lambda *a,**k:invoked.append(a))
    monkeypatch.setattr(build_macos_app.sys,'platform','darwin')
    with pytest.raises(ValueError,match='an .app'):
        build_macos_app.build(build_macos_app.ROOT/'work/not-an-app-folder')
    assert not invoked
