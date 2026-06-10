<div align="center">

<img src="assets/bioauth_social_preview_1280x640.png" alt="BioAuth Banner" width="100%">

<br>

# BioAuth

### Continuous Behavioral Authentication for Windows

A local-first desktop security system that verifies the active user after login using keyboard behavior, mouse behavior, runtime risk scoring, and face confirmation.

<br>

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge\&logo=python\&logoColor=white)
![Windows](https://img.shields.io/badge/Windows-Desktop-0078D6?style=for-the-badge\&logo=windows\&logoColor=white)
![PySide6](https://img.shields.io/badge/PySide6%20%2F%20QML-UI-41CD52?style=for-the-badge\&logo=qt\&logoColor=white)
![OpenCV](https://img.shields.io/badge/OpenCV-Face%20Verification-5C3EE8?style=for-the-badge\&logo=opencv\&logoColor=white)
![Privacy](https://img.shields.io/badge/Privacy-Local--First-00C853?style=for-the-badge)

</div>

---

## The Problem

Traditional authentication usually proves identity only once: at login.

After that, the computer may stay unlocked in a lab, office, library, or shared workspace. If another person starts using the active session, the original password check no longer protects the device.

**BioAuth** was built around this gap.

Instead of treating authentication as a single event, BioAuth continuously evaluates whether the current user's behavior still matches the legitimate owner's learned profile.

---

## What BioAuth Does

BioAuth monitors natural desktop interaction patterns during an active Windows session.

It focuses on behavioral signals such as:

* keyboard timing rhythm
* dwell time and flight time
* typing speed and variation
* mouse movement speed
* cursor movement style
* click timing and interaction rhythm
* optional face confirmation when behavior becomes suspicious

The goal is not to replace the password.
The goal is to add a second protection layer after login.

---

## Core Flow

```text
Login
  ↓
Train behavioral profile
  ↓
Start protection
  ↓
Monitor keyboard and mouse behavior
  ↓
Extract runtime feature windows
  ↓
Evaluate risk using local models
  ↓
Normal behavior → session continues
Suspicious behavior → face confirmation
Face not verified → Windows session lock
```

---

## Key Features

| Feature                    | Description                                                    |
| -------------------------- | -------------------------------------------------------------- |
| Continuous Authentication  | Verifies the active user during the session, not only at login |
| Keyboard Behavior Analysis | Learns typing rhythm using timing-based behavioral features    |
| Mouse Movement Analysis    | Evaluates cursor movement, speed, pauses, and click behavior   |
| Runtime Risk Scoring       | Converts live behavior into a risk decision                    |
| Face Confirmation          | Adds an identity check when behavior becomes suspicious        |
| Windows Lock Integration   | Protects the active session when identity cannot be confirmed  |
| Local-First Privacy        | Keeps behavioral and verification data on the user's device    |
| Encrypted Local Storage    | Protects local session data and user-related artifacts         |
| Desktop Packaging          | Supports Windows EXE and installer generation                  |

---

## Why It Matters

Passwords are still important, but they are not enough for active-session protection.

A user may sign in correctly, leave the device unlocked, and allow someone else to access private files, accounts, academic work, or internal resources.

BioAuth adds a quiet security layer that works in the background and reacts only when enough behavioral evidence becomes suspicious.

---

## System Architecture

BioAuth separates the system into clear layers:

```text
User Interaction
  ↓
Keyboard Listener + Mouse Tracker
  ↓
Encrypted Local Event Storage
  ↓
Feature Extraction
  ↓
Behavioral Model Inference
  ↓
Risk Decision Engine
  ↓
Face Confirmation / Session Protection
```

The user interface displays backend-owned security state.
The backend remains responsible for model readiness, protection status, runtime decisions, and lock behavior.

---

## Behavioral Biometrics

BioAuth uses behavioral biometrics instead of special biometric hardware.

### Keyboard Signals

The system analyzes timing patterns such as:

* key hold duration
* time between key events
* rhythm consistency
* typing speed
* timing variation

### Mouse Signals

The system also studies mouse behavior, including:

* cursor speed
* movement distance
* acceleration
* click intervals
* pauses
* movement style

Using keyboard and mouse evidence together gives the system stronger context than relying on only one signal.

---

## Face Confirmation

Face confirmation is used as a second verification step when behavior becomes suspicious.

It is designed as a privacy-conscious recovery layer:

```text
Suspicious behavior detected
  ↓
Face confirmation requested
  ↓
Owner verified → session continues
Owner not verified / timeout / unavailable camera → protective lock
```

The camera is not intended to run all the time.
It is only used for setup or confirmation when needed.

---

## Privacy-First Design

BioAuth is designed around local processing and data minimization.

The system is built to avoid unnecessary collection and to keep sensitive data under local user control.

Privacy principles include:

* local-first processing
* no cloud requirement for the core protection flow
* no storage of raw typed text as target data
* keyboard behavior treated as timing patterns
* mouse behavior treated as movement and interaction patterns
* face confirmation used only when needed
* encrypted local session storage
* user-facing privacy and deletion controls

---

## Technology Stack

| Area                          | Technology                     |
| ----------------------------- | ------------------------------ |
| Backend                       | Python 3.11                    |
| Desktop UI                    | PySide6 / QML                  |
| Keyboard & Mouse Capture      | pynput                         |
| Machine Learning              | Scikit-learn                   |
| Optional Deep Runtime Support | PyTorch                        |
| Face Verification             | OpenCV / ONNX                  |
| Local Storage                 | SQLite / encrypted local files |
| Packaging                     | PyInstaller                    |
| Installer                     | Inno Setup                     |
| Platform                      | Windows x64                    |

---

## Project Structure

```text
BioAuth/
├── desktop_app.py              # Main desktop application entrypoint
├── start_app.bat               # Windows launcher
├── logger.py                   # Behavioral event logger worker
├── monitor.py                  # Runtime monitor worker
├── auth.py                     # Local account authentication helpers
├── bioauth_runtime/            # Runtime supervision and worker control
├── bridge/                     # Python-to-QML backend bridge
├── feature_extractors/         # Keyboard and mouse feature extraction
├── model_runtime/              # Runtime model loading and decision support
├── training_core/              # Training pipeline and profile preparation
├── monitor_core/               # Runtime monitoring and escalation logic
├── models/face/                # ONNX face model files
├── qml/                        # PySide6/QML user interface
├── src/bioauth/                # Package-style application modules
├── build_exe.bat               # Windows EXE build script
├── build_installer.bat         # Windows installer build script
└── BioAuthInstaller.iss        # Inno Setup installer definition
```

---

## User Experience

BioAuth is designed around a simple end-user flow:

1. Create or sign in to a local account
2. Complete behavioral enrollment
3. Train the protection model
4. Start protected monitoring
5. Continue using the device normally
6. Respond to face confirmation only when needed
7. Let the system lock the session if identity cannot be confirmed

The application focuses on making security visible without exposing raw sensitive data.

---

## Build Requirements

Recommended environment:

* Windows x64
* Python 3.11 x64
* PySide6
* OpenCV contrib
* Scikit-learn
* PyInstaller
* Inno Setup

Install dependencies:

```powershell
pip install -r requirements.txt
pip install -r requirements-face.txt
pip install -r requirements-build.txt
```

---

## Running From Source

```powershell
python desktop_app.py
```

Or use the Windows launcher:

```powershell
.\start_app.bat
```

---

## Building the EXE

```powershell
.\build_exe.bat
```

Expected output:

```text
dist\BioAuth\BioAuth.exe
```

---

## Building the Installer

```powershell
.\build_installer.bat
```

Expected installer output:

```text
installer\BioAuthDesktopSetup_<version>.exe
```

---

## Security Philosophy

BioAuth follows a practical security model:

```text
Do not trust a session forever.
Do not collect more data than needed.
Do not make the UI responsible for security decisions.
Do not silently approve suspicious behavior.
Keep biometric-related processing local.
Fail safely when verification cannot be completed.
```

---

## Project Status

BioAuth is an active Windows desktop cybersecurity project focused on continuous behavioral authentication and local session protection.

The current version demonstrates:

* local account flow
* behavioral enrollment
* keyboard and mouse feature extraction
* runtime monitoring
* risk-based decision logic
* optional face confirmation
* local privacy controls
* Windows packaging and installer support

---

## Keywords

```text
Behavioral Biometrics
Continuous Authentication
Desktop Security
Machine Learning
Keystroke Dynamics
Mouse Dynamics
Face Verification
Windows Protection
Local-First Privacy
```

---

<div align="center">

### BioAuth

**A smarter way to protect an unlocked Windows session.**

</div>
