from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TESTS))
mod = importlib.import_module("test_history_archive_finalization_verification")
checks = [
    mod.test_runtime_view_keeps_finalizing_until_archived_path_is_indexed,
    mod.test_update_dashboard_rebuilds_runtime_view_after_missing_archive_timeout,
    mod.test_update_dashboard_rebuilds_runtime_view_after_late_archive_sync_without_duplicates,
    mod.test_history_page_displays_backend_owned_archive_status,
]
for check in checks:
    check()
    print("PASS: " + check.__name__)
print("ALL_HISTORY_ARCHIVE_FINALIZATION_CHECKS_PASSED=" + str(len(checks)))
