from __future__ import annotations

import os

from test_license_production_policy_closure import run_all

if __name__ == "__main__":
    run_all()
    print("ALL_LICENSE_PRODUCTION_POLICY_CLOSURE_CHECKS_PASSED=8", flush=True)
    os._exit(0)
