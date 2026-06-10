# BioAuth Codex helper: low-token project map
$ErrorActionPreference = 'SilentlyContinue'
Write-Host "== Largest files excluding generated dirs =="
Get-ChildItem -Recurse -File | Where-Object { $_.FullName -notmatch '\\.venv|__pycache__|\.pytest_cache|build|dist|archive|node_modules|reports' } | Sort-Object Length -Descending | Select-Object -First 50 FullName,Length

Write-Host "`n== Key symbols =="
rg "startProtected|stopProductionMonitor|logger_ready|monitor_ready|session_state|worker_heartbeat|runtime_summary" bridge src monitor_core qml

Write-Host "`n== Internal/dev terms =="
rg "shadow|hybrid|debug|developer|promotion|production_approval" bridge src qml
