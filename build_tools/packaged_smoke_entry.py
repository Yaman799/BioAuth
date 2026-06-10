from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault('PYNPUT_BACKEND', 'dummy')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from build_tools import packaged_runtime_support as support

if __name__ == '__main__':
    if '--self-check-packaging' in sys.argv:
        raise SystemExit(support.run_packaging_selfcheck())
    if '--self-check-runtime-smoke' in sys.argv:
        raise SystemExit(support.run_runtime_smoke_selfcheck())
    if '--self-check-performance' in sys.argv:
        raise SystemExit(support.run_packaging_performance_check())
    if '--self-check-release-readiness' in sys.argv:
        raise SystemExit(support.run_release_readiness_selfcheck())
    print('Usage: packaged_smoke_entry.py [--self-check-packaging|--self-check-runtime-smoke|--self-check-performance|--self-check-release-readiness]')
    raise SystemExit(2)
