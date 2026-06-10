"""Compatibility wrapper for :mod:`bioauth.ml.policy`.

Commercial-CLEAN-08 moved the implementation into ``src/bioauth/ml/policy.py``.
Keep importing ``model_policy`` from the repository root until a later phase
explicitly removes this compatibility surface after reference scans and tests.
"""
from __future__ import annotations

import importlib as _importlib
import sys as _sys
from pathlib import Path as _Path

_wrapper_name = __name__
_src_dir = _Path(__file__).resolve().parent / "src"
if _src_dir.exists() and str(_src_dir) not in _sys.path:
    _sys.path.insert(0, str(_src_dir))

_module = _importlib.import_module("bioauth.ml.policy")
_sys.modules[_wrapper_name] = _module
globals().update(_module.__dict__)
