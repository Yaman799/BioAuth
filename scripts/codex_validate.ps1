# BioAuth Codex helper: validation
$ErrorActionPreference = 'Stop'
if (Test-Path .\.venv\Scripts\python.exe) {
  .\.venv\Scripts\python.exe -m compileall -q .
} else {
  python -m compileall -q .
}
if (Test-Path .\.venv\Scripts\pytest.exe) {
  .\.venv\Scripts\pytest.exe -q tests\test_commercial_core_22*.py
} else {
  pytest -q tests\test_commercial_core_22*.py
}
