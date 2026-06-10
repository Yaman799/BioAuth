from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QML_ROOT = ROOT / "qml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _qml_brace_balance(text: str) -> tuple[int, str]:
    """Return structural brace balance while ignoring common string/comment spans."""
    balance = 0
    state = "code"
    escape = False
    index = 0
    while index < len(text):
        char = text[index]
        nxt = text[index + 1] if index + 1 < len(text) else ""
        if state == "code":
            if char == "/" and nxt == "/":
                state = "line_comment"
                index += 1
            elif char == "/" and nxt == "*":
                state = "block_comment"
                index += 1
            elif char in {"\"", "'", "`"}:
                state = char
                escape = False
            elif char == "{":
                balance += 1
            elif char == "}":
                balance -= 1
        elif state == "line_comment":
            if char == "\n":
                state = "code"
        elif state == "block_comment":
            if char == "*" and nxt == "/":
                state = "code"
                index += 1
        else:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == state:
                state = "code"
        index += 1
    return balance, state


def test_qml_files_have_balanced_structural_braces() -> None:
    """A missing final brace prevents QQmlApplicationEngine from creating Main.qml."""
    offenders: list[str] = []
    for path in sorted(QML_ROOT.rglob("*.qml")):
        balance, state = _qml_brace_balance(_read(path))
        if balance != 0 or state != "code":
            offenders.append(f"{path.relative_to(ROOT)}: balance={balance}, parser_state={state}")
    assert not offenders, "Unbalanced QML file(s): " + " | ".join(offenders)


def test_qml_files_do_not_define_duplicate_ids() -> None:
    """Duplicate ids in one QML component can make QQmlApplicationEngine.rootObjects() empty."""
    offenders: list[str] = []
    pattern = re.compile(r"\bid\s*:\s*([A-Za-z_][A-Za-z0-9_]*)")
    for path in sorted(QML_ROOT.rglob("*.qml")):
        ids = pattern.findall(_read(path))
        duplicates = sorted(name for name, count in Counter(ids).items() if count > 1)
        if duplicates:
            offenders.append(f"{path.relative_to(ROOT)}: {', '.join(duplicates)}")
    assert not offenders, "Duplicate QML ids found: " + " | ".join(offenders)


def test_profile_page_has_single_automated_setup_card() -> None:
    qml = _read(QML_ROOT / "pages" / "ProfilePage.qml")
    assert qml.count("id: setupJourneyColumn") == 1
    assert qml.count("id: setupJourneyHero") == 1
    assert qml.count("Automated protection setup") == 1
    assert "backend.autoEnrollmentState" in qml
    assert "backend.productionApprovalState" in qml
    assert "backend.modelReadinessState" in qml


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("3 focused startup qml integrity phase9 fix tests passed", flush=True)
    os._exit(0)
