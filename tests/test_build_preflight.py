from __future__ import annotations


def test_validate_required_project_files_requires_privacy_policy(tmp_path):
    import build_tools.preflight as preflight

    root = tmp_path
    (root / "desktop_app.py").write_text("print(1)\n", encoding="utf-8")
    (root / "qml").mkdir(parents=True, exist_ok=True)
    (root / "qml" / "Main.qml").write_text("Item {}\n", encoding="utf-8")
    (root / "bioauth.ico").write_text("icon\n", encoding="utf-8")

    assert preflight.validate_required_project_files(root) == "PRIVACY_POLICY.md is missing."


def test_validate_required_project_files_rejects_empty_privacy_policy(tmp_path):
    import build_tools.preflight as preflight

    root = tmp_path
    (root / "desktop_app.py").write_text("print(1)\n", encoding="utf-8")
    (root / "qml").mkdir(parents=True, exist_ok=True)
    (root / "qml" / "Main.qml").write_text("Item {}\n", encoding="utf-8")
    (root / "bioauth.ico").write_text("icon\n", encoding="utf-8")
    (root / "PRIVACY_POLICY.md").write_text("   \n", encoding="utf-8")

    assert preflight.validate_required_project_files(root) == "PRIVACY_POLICY.md is empty."


def test_validate_required_modules_reports_missing_lightgbm(monkeypatch):
    import build_tools.preflight as preflight

    def fake_import(name: str):
        if name == "lightgbm":
            raise ImportError("missing lightgbm")
        return object()

    monkeypatch.setattr(preflight.importlib, "import_module", fake_import)
    missing = preflight.validate_required_modules(preflight.REQUIRED_MODULES)
    assert any(item.startswith("lightgbm") for item in missing)


def test_validate_required_modules_accepts_lightgbm_when_available(monkeypatch):
    import build_tools.preflight as preflight

    monkeypatch.setattr(preflight.importlib, "import_module", lambda name: object())
    missing = preflight.validate_required_modules(preflight.REQUIRED_MODULES)
    assert missing == []


def test_release_hygiene_rejects_dev_cache_files(tmp_path):
    from build_tools.release_hygiene import scan_tree

    root = tmp_path / "dist" / "BioAuth"
    cache = root / ".pytest_cache"
    cache.mkdir(parents=True)
    (cache / "README.md").write_text("cache", encoding="utf-8")

    problems = scan_tree(root)

    assert any(".pytest_cache" in item for item in problems)


def test_release_hygiene_accepts_clean_dist(tmp_path):
    from build_tools.release_hygiene import scan_tree

    root = tmp_path / "dist" / "BioAuth"
    root.mkdir(parents=True)
    (root / "BioAuth.exe").write_text("exe", encoding="utf-8")
    (root / "PRIVACY_POLICY.md").write_text("policy", encoding="utf-8")

    assert scan_tree(root) == []



def test_release_hygiene_rejects_generated_evidence_and_model_artifacts(tmp_path):
    from build_tools.release_hygiene import scan_tree

    root = tmp_path / "source"
    (root / "validation_artifacts" / "phase" ).mkdir(parents=True)
    (root / "validation_artifacts" / "phase" / "manifest.json").write_text("{}", encoding="utf-8")
    (root / "validation" / "logs").mkdir(parents=True)
    (root / "validation" / "logs" / "run.exitcode").write_text("0", encoding="utf-8")
    (root / "docs" / "validation").mkdir(parents=True)
    (root / "docs" / "validation" / "compile.log.md").write_text("log", encoding="utf-8")
    (root / "reports" / "phase").mkdir(parents=True)
    (root / "reports" / "phase" / "model.pkl").write_text("artifact", encoding="utf-8")
    (root / "reports" / "phase" / "events.jsonl").write_text("{}\n", encoding="utf-8")

    problems = scan_tree(root, release_mode=False)

    assert any(item.startswith("validation_artifacts/") for item in problems)
    assert any(item.startswith("validation/") for item in problems)
    assert any(item.startswith("docs/validation/") for item in problems)
    assert any(item.startswith("reports/phase/") for item in problems)
    assert any(item.endswith("model.pkl") for item in problems)
    assert any(item.endswith("events.jsonl") for item in problems)


def test_release_hygiene_allows_packaged_safety_reports_only(tmp_path):
    from build_tools.release_hygiene import scan_tree

    root = tmp_path / "source"
    (root / "reports" / "safety").mkdir(parents=True)
    (root / "reports" / "safety" / "policy.md").write_text("safe policy", encoding="utf-8")

    assert scan_tree(root, release_mode=False) == []
