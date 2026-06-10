from __future__ import annotations

import os

# Embedded demo-classic protected build hook.
# This is intentionally forced for the dedicated demo EXE so the packaged app
# behaves exactly like launching source with:
#   $env:BIOAUTH_DEMO_CLASSIC_PROTECTED="1"
# The normal product build never includes this hook.
os.environ["BIOAUTH_DEMO_CLASSIC_PROTECTED"] = "1"
os.environ["BIOAUTH_DEMO_CLASSIC_PROTECTED_EMBEDDED"] = "1"
os.environ.setdefault("BIOAUTH_BUILD_FLAVOR", "demo-classic-protected")

# Make the local face confirmation feature available in the dedicated
# presentation build. This does not enroll a face, does not create consent,
# and does not force face confirmation on by itself; it only allows an already
# enrolled/consented local profile to use the backend-owned pre-lock face path.
os.environ.setdefault("BIOAUTH_ENABLE_FACE_CONFIRMATION_DEV", "1")
os.environ.setdefault("BIOAUTH_ENABLE_FACE_ENROLLMENT_DEV", "1")
