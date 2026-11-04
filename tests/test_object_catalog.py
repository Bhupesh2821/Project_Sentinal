"""Model label policy and UI catalog tests, not detector accuracy evidence."""
from sentinal.vision.object_catalog import (MODEL_PROFILES, canonical_label, label_allowed, allowed_class_ids, catalog_rows, safety_tool_label)


def test_exact_bag_and_person_labels_canonicalize_between_models():
    assert [canonical_label(n) for n in ["Person", "Backpack", "Handbag", "Suitcase"]] == ["person", "backpack", "handbag", "suitcase"]
    assert canonical_label("Drill (Tool)") == "drill"
    assert canonical_label("Nail (Construction)") == "construction nail"


def test_sensitive_and_unrequested_weapon_categories_are_never_permitted():
    names = {0: "Person", 1: "Human face", 2: "Woman", 3: "Man", 4: "Girl", 5: "Boy", 6: "Helmet", 7: "Rifle"}
    assert allowed_class_ids(names) == [0, 6]
    assert not label_allowed("Human hair")
    assert not label_allowed("")


def test_safety_selection_uses_actual_model_names_and_native_ids():
    names = {13: "Hammer", 24: "Helmet", 82: "Person", 83: "Handbag", 143: "Drill (Tool)"}
    assert allowed_class_ids(names, "safety") == [13, 24, 143]
    assert allowed_class_ids(names, "focus") == [82, 83]
    assert safety_tool_label("drill")
    assert not safety_tool_label("high visibility vest")


def test_saved_catalog_counts_are_truthful_and_include_targets():
    everyday = catalog_rows(MODEL_PROFILES[0].model_path)
    expanded = catalog_rows(MODEL_PROFILES[1].model_path)
    assert len(everyday) == 80
    assert len(expanded) == 577
    assert catalog_rows(MODEL_PROFILES[2].model_path) == expanded
    assert {"person", "backpack", "handbag", "suitcase"} <= {r["label"] for r in expanded}
    assert {"helmet", "hammer", "wrench", "ladder", "drill", "glove", "goggles"} <= {r["label"] for r in expanded}
    assert all(label_allowed(r["model_label"]) for r in expanded)
    assert not catalog_rows("unknown-model.pt")


def test_unknown_category_filter_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        allowed_class_ids({0: "Person"}, "imaginary")


def test_extended_downloader_validates_checksum_and_cleans_failure(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    from io import BytesIO
    import pytest
    script = Path(__file__).resolve().parents[1] / "tools/download_extended_model.py"
    spec = importlib.util.spec_from_file_location("test_extended_downloader", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "urlopen", lambda *a, **k: BytesIO(b"corrupt test bytes"))
    with pytest.raises(RuntimeError, match="checksum"):
        module.main()
    assert not (tmp_path / "models/yolov8n-oiv7.pt").exists()
    assert not (tmp_path / "models/yolov8n-oiv7.part").exists()
