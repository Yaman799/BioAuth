from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict

from bioauth_version import get_app_version
from .shared import Slot


_UPDATE_MANIFEST_NAME = "bioauth-update.json"
_RELEASE_CONFIG_NAME = "release_config.json"
_DEFAULT_UPDATE_CHANNEL = "beta"
_DEFAULT_REPO_OWNER = "CHANGE_ME_OWNER"
_DEFAULT_REPO_NAME = "BioAuth"


def _runtime_base_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def _load_release_config_summary() -> Dict[str, Any]:
    candidates = []
    env_path = os.environ.get("BIOAUTH_RELEASE_CONFIG")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(_runtime_base_dir() / _RELEASE_CONFIG_NAME)
    source_release_dir = Path(__file__).resolve().parents[1] / "src" / "bioauth" / "release"
    candidates.append(source_release_dir / _RELEASE_CONFIG_NAME)
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            if path.is_file():
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    return dict(payload)
        except Exception:
            continue
    return {}


def _config_value(payload: Dict[str, Any], *names: str, default: str = "") -> str:
    for name in names:
        value = payload.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _update_config_summary() -> Dict[str, Any]:
    payload = _load_release_config_summary()
    owner = (
        os.environ.get("BIOAUTH_UPDATE_REPO_OWNER")
        or _config_value(payload, "update_repo_owner", "repo_owner", default=_DEFAULT_REPO_OWNER)
    ).strip()
    repo = (
        os.environ.get("BIOAUTH_UPDATE_REPO_NAME")
        or _config_value(payload, "update_repo_name", "repo_name", default=_DEFAULT_REPO_NAME)
    ).strip()
    channel = (
        os.environ.get("BIOAUTH_UPDATE_CHANNEL")
        or _config_value(payload, "update_channel", "channel", default=_DEFAULT_UPDATE_CHANNEL)
    ).strip().lower()
    return {
        "configured": bool(owner) and bool(repo) and owner != _DEFAULT_REPO_OWNER and repo != "CHANGE_ME_REPO",
        "channel": channel,
    }


def _update_client_classes():
    from update_client import GitHubReleaseUpdateClient, UpdateConfig

    return GitHubReleaseUpdateClient, UpdateConfig


class UpdateMixin:
    def _default_update_state(self) -> Dict[str, Any]:
        config = _update_config_summary()
        return {
            "state": "idle",
            "status": "Idle",
            "currentVersion": get_app_version(),
            "latestVersion": "",
            "message": "Click Check for updates to contact the configured public GitHub Releases endpoint.",
            "releaseNotes": "",
            "installerName": "",
            "downloadedPath": "",
            "canCheck": True,
            "canDownload": False,
            "canInstall": False,
            "configured": bool(config.get("configured")),
            "channel": str(config.get("channel") or _DEFAULT_UPDATE_CHANNEL),
        }

    def _ensure_update_state(self) -> Dict[str, Any]:
        state = getattr(self, "_update_state", None)
        if not isinstance(state, dict):
            state = self._default_update_state()
            self._update_state = dict(state)
        return dict(state)

    def _set_update_state(self, **changes: Any) -> None:
        state = self._ensure_update_state()
        state.update(changes)
        state.setdefault("currentVersion", get_app_version())
        code = str(state.get("state") or "idle")
        state["status"] = self._update_status_label(code)
        self._update_state = dict(state)
        signal = getattr(self, "updateStateChanged", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()

    def _update_status_label(self, code: str) -> str:
        labels = {
            "idle": "Idle",
            "checking": "Checking for updates",
            "up_to_date": "Up to date",
            "update_available": "Update available",
            "downloading": "Downloading",
            "ready_to_install": "Ready to install",
            "download_failed": "Download failed",
            "hash_verification_failed": "Hash verification failed",
            "invalid_update_manifest": "Invalid update manifest",
            "downgrade_rejected": "Downgrade rejected",
            "not_configured": "Update endpoint not configured",
            "install_failed": "Install failed",
        }
        return labels.get(str(code or "idle"), "Idle")


    @Slot()
    def checkForUpdates(self) -> None:
        if bool(getattr(self, "_update_operation_inflight", False)):
            return
        _client_cls, config_cls = _update_client_classes()
        config = config_cls.from_env()
        self._update_operation_inflight = True
        self._set_update_state(
            state="checking",
            message="Checking public GitHub Releases for a BioAuth update...",
            latestVersion="",
            releaseNotes="",
            installerName="",
            downloadedPath="",
            canCheck=False,
            canDownload=False,
            canInstall=False,
            configured=config.configured,
            channel=config.channel,
        )

        def worker() -> None:
            try:
                client = _client_cls(config, current_version=get_app_version())
                result = client.check_for_update()
                self._update_client = client
                state_code = str(result.get("state") or "download_failed")
                self._set_update_state(
                    state=state_code,
                    currentVersion=str(result.get("currentVersion") or get_app_version()),
                    latestVersion=str(result.get("latestVersion") or ""),
                    message=str(result.get("message") or "Update check finished."),
                    releaseNotes=str(result.get("releaseNotes") or ""),
                    installerName=str(result.get("installerName") or ""),
                    downloadedPath="",
                    canCheck=True,
                    canDownload=state_code == "update_available",
                    canInstall=False,
                    configured=config.configured,
                    channel=config.channel,
                )
            finally:
                self._update_operation_inflight = False

        threading.Thread(target=worker, name="bioauth-update-check", daemon=True).start()

    @Slot()
    def downloadAvailableUpdate(self) -> None:
        if bool(getattr(self, "_update_operation_inflight", False)):
            return
        client = getattr(self, "_update_client", None)
        if client is None:
            self.checkForUpdates()
            return
        self._update_operation_inflight = True
        previous = self._ensure_update_state()
        self._set_update_state(
            state="downloading",
            message="Downloading the installer after your approval. BioAuth will verify SHA256 before install is enabled.",
            canCheck=False,
            canDownload=False,
            canInstall=False,
        )

        def worker() -> None:
            try:
                result = client.safe_download_candidate()
                state_code = str(result.get("state") or "download_failed")
                self._set_update_state(
                    state=state_code,
                    currentVersion=str(result.get("currentVersion") or previous.get("currentVersion") or get_app_version()),
                    latestVersion=str(result.get("latestVersion") or previous.get("latestVersion") or ""),
                    message=str(result.get("message") or "Update download finished."),
                    releaseNotes=str(previous.get("releaseNotes") or ""),
                    installerName=str(result.get("installerName") or previous.get("installerName") or ""),
                    downloadedPath=str(result.get("downloadedPath") or ""),
                    canCheck=True,
                    canDownload=state_code in {"download_failed", "hash_verification_failed"},
                    canInstall=state_code == "ready_to_install" and bool(result.get("downloadedPath")),
                )
            finally:
                self._update_operation_inflight = False

        threading.Thread(target=worker, name="bioauth-update-download", daemon=True).start()

    @Slot(result=bool)
    def openDownloadedUpdateInstaller(self) -> bool:
        state = self._ensure_update_state()
        if str(state.get("state") or "") != "ready_to_install" or not bool(state.get("canInstall")):
            self._set_update_state(state="install_failed", message="No verified update installer is ready to run.", canCheck=True, canDownload=False, canInstall=False)
            return False
        path = Path(str(state.get("downloadedPath") or ""))
        if not path.is_file():
            self._set_update_state(state="install_failed", message="The verified installer file no longer exists.", canCheck=True, canDownload=False, canInstall=False)
            return False
        try:
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                subprocess.Popen([str(path)], shell=False)
            self._set_update_state(message="Verified installer launched after explicit user confirmation. Follow the installer prompts to continue.")
            return True
        except Exception:
            self._set_update_state(state="install_failed", message="Could not launch the verified installer.", canCheck=True, canDownload=False, canInstall=True)
            return False
