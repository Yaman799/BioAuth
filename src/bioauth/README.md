# BioAuth Commercial Package Skeleton

`src/bioauth` is the commercial package namespace for the gradual BioAuth Desktop cleanup.

## Compatibility rule

Root modules remain the supported compatibility surface during the split phases. The following files must keep working from the repository root until a later phase explicitly moves implementation and adds tested wrappers:

- `desktop_app.py`
- `start_app.pyw`
- `start_app.bat`
- `logger.py`
- `monitor.py`
- `model_training.py`
- `model_inference.py`
- `paths.py`
- `security.py`
- `app_settings.py`

## Migration rule

Implementation modules will move gradually into this package only in later phases. Each move must preserve the old import path with a compatibility wrapper and must pass the relevant import, startup, runtime, training, face confirmation, lock, and packaging tests.

## No direct deletion rule

No existing runtime, training, QML, identity, security, or release module should be deleted or moved directly. A module can be removed only after reference scans and tests prove it is unused, and even then deletion must happen in an explicit cleanup phase.

## No behavior-change rule

This skeleton phase is structural only. It must not change runtime behavior, model logic, risk policy, face policy, lock policy, QML loading, Start/Stop Monitor, training, inference, post-lock resume, or PyInstaller entrypoints.

## Intended namespace layout

- `bioauth.app` — future application bootstrap and UI-facing orchestration
- `bioauth.runtime` — future runtime monitor/session orchestration
- `bioauth.input` — future keyboard/mouse collection adapters
- `bioauth.features` — future feature extraction package surface
- `bioauth.ml` — future training/inference/model runtime surfaces
- `bioauth.identity` — future face/identity confirmation surfaces
- `bioauth.security` — future encryption, storage, licensing, and policy surfaces
- `bioauth.release` — future packaging/update/release surfaces
- `bioauth.hybrid` — future hybrid/direct test surfaces, kept separate from commercial runtime policy
- `bioauth.utils` — future shared utility surface
