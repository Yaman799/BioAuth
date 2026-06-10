"""Compatibility facade for report-only Hybrid Direct candidate artifact builders."""

from __future__ import annotations

from training_core.candidates.common import importlib, _dependency_available
from training_core.candidates.constants import *
from training_core.candidates.artifacts import *
from training_core.candidates.classical import *
from training_core.candidates.supervised import *
from training_core.candidates.deep_oneclass import *
from training_core.candidates.keyboard_deep import *
from training_core.candidates.deep_sequence import *
from training_core.candidates.report_only import *
