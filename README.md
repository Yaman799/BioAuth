# BioAuth

BioAuth is a Windows desktop application for continuous behavioral authentication.

The system verifies the active user after login by analyzing keyboard rhythm, mouse movement behavior, and face verification. It is designed to improve local desktop security by detecting suspicious user behavior during an active session.

## Key Features

- Continuous behavioral authentication
- Keyboard behavior analysis
- Mouse movement behavior analysis
- Face verification support
- Runtime risk scoring
- Suspicious activity detection
- Windows session lock integration
- Local-first privacy approach

## Project Scope

BioAuth focuses on protecting an already logged-in Windows session.

Instead of relying only on a password at login time, the application continues checking whether the active user's behavior matches the enrolled owner profile.

Main workflow:

1. User login
2. Behavioral profile training
3. Protection start
4. Runtime keyboard and mouse monitoring
5. Risk evaluation
6. Face confirmation when suspicious behavior is detected
7. Windows lock when identity is not confirmed

## Technologies Used

- Python
- PySide6 / QML
- OpenCV
- ONNX face models
- Machine learning-based behavior analysis
- Windows desktop runtime integration

## Privacy

BioAuth is designed as a local-first security system.

Behavioral data, user profiles, and verification data are intended to be processed and stored locally on the user's device.

## Repository Notes

This repository contains the main source code for the BioAuth desktop application.

Generated runtime data, logs, local user sessions, build outputs, internal development notes, and experimental modules are excluded from the public repository.

## Status

This project is under active development as a behavioral biometric authentication system for Windows desktop protection.
