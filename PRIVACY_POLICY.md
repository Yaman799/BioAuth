# BioAuth Privacy Policy (Local-Only Beta)

**Last updated:** 2026-04-24  
**Privacy policy version:** 2026-04-24  
**Product:** BioAuth Desktop (Windows)

## Summary (plain language)

BioAuth is a local desktop security app that learns keyboard and mouse behavior patterns on your own device and uses them to estimate risk during a protected session. BioAuth can warn you and may lock the workstation when risk becomes high.

BioAuth is designed as **local-first** software. It does not upload biometric logs, model artifacts, screenshots, webcam images, or telemetry by default.

## Consent and versioning

BioAuth stores the privacy policy version and the local timestamp of consent in the app settings file after the user accepts the onboarding/privacy checklist.

Sensitive optional features, such as incident evidence capture, require separate explicit consent in Settings. Evidence consent is versioned against this privacy policy. If the policy version changes, evidence capture must be re-enabled by the user before any screenshot or webcam capture is allowed.

## What data is collected locally

BioAuth can collect the following data **on your device**:

- **Keyboard dynamics:** timing and key-event identifiers used to build behavioral features.
  - BioAuth stores hashed key identifiers, not raw typed characters, in encrypted logs.
- **Mouse dynamics:** pointer movement, click, scroll, and timestamp data used to build behavioral features.
- **Session metadata:** timestamps, counts, training status, runtime status, and decisions such as legit/suspicious/intruder.
- **Local account data:** username/display name, optional email binding for local recovery, password verifier, and local recovery metadata.
- **Local settings:** privacy consent version/timestamp, optional feature preferences, theme, startup, passcode, and runtime settings.

## Optional incident evidence capture

Incident evidence capture is **OFF by default**.

When you explicitly enable incident evidence capture in Settings, BioAuth records that explicit consent locally. Only then may the app attempt to save local evidence for confirmed high-risk events.

Depending on your chosen settings, incident evidence may include:

- one screenshot captured around the confirmed intruder event; and/or
- a short webcam image burst captured around the confirmed intruder event.

Evidence capture is local-only. It is not uploaded automatically and is not shared automatically. The app must not capture screenshot or webcam evidence when:

- incident evidence is disabled;
- evidence consent is missing;
- evidence consent is for an older policy version;
- both screenshot and webcam evidence channels are disabled.

## What is not collected or shared by default

- No cloud upload by default.
- No remote telemetry by default.
- No microphone capture.
- No clipboard collection.
- No raw typed text storage.
- No screenshot or webcam evidence unless the user explicitly enables incident evidence in Settings.

## Where data is stored

BioAuth stores per-user app data under:

- `%LOCALAPPDATA%\\BioAuth\\`

This includes:

- `data\\settings.json` for app settings and consent state;
- `data\\users.json` for local account records;
- `data\\sessions\\` for archived local sessions;
- `data\\live_session\\` for runtime session files;
- `data\\control\\` for local worker/control state;
- `data\\evidence\\` for optional local incident evidence;
- `models\\` for trained models, runtime bundles, metadata, and integrity files.

## Encryption and key protection

- Session CSV logs are encrypted at rest using Fernet.
- On Windows, the encryption key is protected with DPAPI and tied to your Windows user when available.
- Secrets must not be written to logs or support text.

## Decisions and workstation locking

When you start a protected session, BioAuth evaluates risk periodically. If risk is very high or repeatedly high according to the local lock policy, BioAuth may call the Windows lock operation.

This policy update does not change ML scoring, feature extraction, thresholds, warning behavior, or lock behavior.

## Data retention and deletion

Data remains on your device until you delete it from inside the app or manually remove `%LOCALAPPDATA%\\BioAuth\\`.

Inside the app:

- **Delete local evidence** removes saved incident evidence for the current account.
- **Delete my data** removes local sessions, trained models, and incident evidence for the current account while keeping the local login account.
- **Delete account** removes the local account and associated local data.

During uninstall, the installer may ask whether to remove the local BioAuth data directory.

## Contact / support

For support and updates, see the project repository:

- `https://github.com/alakhrs543-maker/BioAuth`
