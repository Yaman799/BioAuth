from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from bioauth_version import get_app_version, normalize_version
from paths import app_data_dir

MANIFEST_NAME = "bioauth-update.json"
RELEASE_CONFIG_NAME = "release_config.json"
DEFAULT_UPDATE_CHANNEL = "beta"
DEFAULT_API_BASE = "https://api.github.com"
DEFAULT_REPO_OWNER = "CHANGE_ME_OWNER"
DEFAULT_REPO_NAME = "BioAuth"
USER_AGENT = "BioAuthDesktop-Updater/1.0"
OPTIONAL_MANIFEST_FIELDS = {"artifact_names", "checksums", "update_manifest_name", "release_notes_url"}

REQUIRED_MANIFEST_FIELDS = {
    "app",
    "channel",
    "version",
    "installer_name",
    "installer_sha256",
    "min_supported_version",
    "mandatory",
    "release_notes",
    "published_at",
}
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_PRE_SPLIT_RE = re.compile(r"[.-]")


class UpdateError(Exception):
    """Base class for safe updater failures."""


class UpdateNetworkError(UpdateError):
    """The network request failed or the release endpoint could not be reached."""


class InvalidUpdateManifest(UpdateError):
    """The update manifest is missing required data or has invalid values."""


class HashVerificationError(UpdateError):
    """The downloaded installer did not match the manifest hash."""


class UpdateNotConfigured(UpdateError):
    """The public GitHub release endpoint has not been configured yet."""


def _runtime_base_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def default_release_config_paths() -> List[Path]:
    candidates: List[Path] = []
    env_path = os.environ.get("BIOAUTH_RELEASE_CONFIG")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(_runtime_base_dir() / RELEASE_CONFIG_NAME)
    module_dir = Path(__file__).resolve().parent
    if module_dir != _runtime_base_dir():
        candidates.append(module_dir / RELEASE_CONFIG_NAME)
    seen: set[str] = set()
    unique: List[Path] = []
    for path in candidates:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def load_release_config(paths: Iterable[Path] | None = None) -> Dict[str, Any]:
    for path in paths or default_release_config_paths():
        try:
            if not path.is_file():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, Mapping):
            return dict(payload)
    return {}


def _config_value(payload: Mapping[str, Any], *names: str, default: str = "") -> str:
    for name in names:
        value = payload.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _config_bool(payload: Mapping[str, Any], name: str, default: bool = False) -> bool:
    value = payload.get(name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


@dataclass(frozen=True)
class UpdateConfig:
    repo_owner: str = DEFAULT_REPO_OWNER
    repo_name: str = DEFAULT_REPO_NAME
    channel: str = DEFAULT_UPDATE_CHANNEL
    api_base: str = DEFAULT_API_BASE
    manifest_name: str = MANIFEST_NAME
    verification: str = "sha256"
    silent_install: bool = False
    signing_required: bool = False

    @classmethod
    def from_env(cls) -> "UpdateConfig":
        file_payload = load_release_config()
        repo_owner = (
            os.environ.get("BIOAUTH_UPDATE_REPO_OWNER")
            or _config_value(file_payload, "update_repo_owner", "repo_owner", default=DEFAULT_REPO_OWNER)
        ).strip()
        repo_name = (
            os.environ.get("BIOAUTH_UPDATE_REPO_NAME")
            or _config_value(file_payload, "update_repo_name", "repo_name", default=DEFAULT_REPO_NAME)
        ).strip()
        channel = (
            os.environ.get("BIOAUTH_UPDATE_CHANNEL")
            or _config_value(file_payload, "update_channel", "channel", default=DEFAULT_UPDATE_CHANNEL)
        ).strip().lower()
        api_base = (
            os.environ.get("BIOAUTH_UPDATE_API_BASE")
            or _config_value(file_payload, "update_api_base", "api_base", default=DEFAULT_API_BASE)
        ).strip().rstrip("/")
        manifest_name = (
            os.environ.get("BIOAUTH_UPDATE_MANIFEST_NAME")
            or _config_value(file_payload, "manifest_name", "update_manifest_name", default=MANIFEST_NAME)
        ).strip()
        verification = _config_value(file_payload, "verification", default="sha256").lower()
        return cls(
            repo_owner=repo_owner,
            repo_name=repo_name,
            channel=channel,
            api_base=api_base,
            manifest_name=manifest_name,
            verification=verification,
            silent_install=_config_bool(file_payload, "silent_install", False),
            signing_required=_config_bool(file_payload, "signing_required", False),
        )

    @property
    def configured(self) -> bool:
        return (
            bool(self.repo_owner)
            and bool(self.repo_name)
            and self.repo_owner != DEFAULT_REPO_OWNER
            and self.repo_name != "CHANGE_ME_REPO"
        )

    @property
    def releases_url(self) -> str:
        return f"{self.api_base}/repos/{self.repo_owner}/{self.repo_name}/releases"

    @property
    def uses_hash_verification_only(self) -> bool:
        return self.verification == "sha256" and not self.signing_required


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    browser_download_url: str


@dataclass(frozen=True)
class CandidateUpdate:
    manifest: Dict[str, Any]
    release: Dict[str, Any]
    manifest_asset: ReleaseAsset
    installer_asset: ReleaseAsset

    @property
    def latest_version(self) -> str:
        return str(self.manifest.get("version") or "")

    @property
    def installer_name(self) -> str:
        return str(self.manifest.get("installer_name") or "")


def _prerelease_key(value: str) -> Tuple[int, Tuple[Tuple[int, Any], ...]]:
    if not value:
        return (1, ())
    tokens: List[Tuple[int, Any]] = []
    for token in [part for part in _PRE_SPLIT_RE.split(value) if part != ""]:
        if token.isdigit():
            tokens.append((0, int(token)))
        else:
            tokens.append((1, token.lower()))
    return (0, tuple(tokens))


def version_key(version: str) -> Tuple[int, int, int, Tuple[int, Tuple[Tuple[int, Any], ...]]]:
    normalized = normalize_version(version)
    core, _, prerelease = normalized.partition("-")
    major, minor, patch = [int(part) for part in core.split(".")]
    return major, minor, patch, _prerelease_key(prerelease)


def compare_versions(left: str, right: str) -> int:
    left_key = version_key(left)
    right_key = version_key(right)
    return (left_key > right_key) - (left_key < right_key)


def is_update_available(current_version: str, candidate_version: str) -> bool:
    return compare_versions(candidate_version, current_version) > 0


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_update_manifest(payload: Mapping[str, Any], *, channel: str | None = None) -> Dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise InvalidUpdateManifest("Update manifest is not a JSON object.")
    missing = sorted(REQUIRED_MANIFEST_FIELDS.difference(payload.keys()))
    if missing:
        raise InvalidUpdateManifest("Update manifest is missing required fields: " + ", ".join(missing))
    manifest = dict(payload)
    if str(manifest.get("app") or "").strip() != "BioAuth":
        raise InvalidUpdateManifest("Update manifest is for a different app.")
    manifest["channel"] = str(manifest.get("channel") or "").strip().lower()
    if not manifest["channel"]:
        raise InvalidUpdateManifest("Update manifest channel is empty.")
    if channel and manifest["channel"] != str(channel).strip().lower():
        raise InvalidUpdateManifest("Update manifest channel does not match the configured channel.")
    manifest["version"] = normalize_version(str(manifest.get("version") or ""))
    manifest["min_supported_version"] = normalize_version(str(manifest.get("min_supported_version") or ""))
    manifest["installer_name"] = str(manifest.get("installer_name") or "").strip()
    if not manifest["installer_name"] or "/" in manifest["installer_name"] or "\\" in manifest["installer_name"]:
        raise InvalidUpdateManifest("Update manifest installer_name is invalid.")
    manifest["installer_sha256"] = str(manifest.get("installer_sha256") or "").strip().lower()
    if not _SHA256_RE.match(manifest["installer_sha256"]):
        raise InvalidUpdateManifest("Update manifest installer_sha256 is missing or invalid.")
    if not isinstance(manifest.get("mandatory"), bool):
        raise InvalidUpdateManifest("Update manifest mandatory field must be a boolean.")
    manifest["release_notes"] = str(manifest.get("release_notes") or "").strip()
    if not manifest["release_notes"]:
        raise InvalidUpdateManifest("Update manifest release_notes is empty.")
    manifest["published_at"] = str(manifest.get("published_at") or "").strip()
    if not manifest["published_at"]:
        raise InvalidUpdateManifest("Update manifest published_at is empty.")
    try:
        _dt.datetime.fromisoformat(manifest["published_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidUpdateManifest("Update manifest published_at is not an ISO-8601 timestamp.") from exc
    if "artifact_names" in manifest:
        names = manifest.get("artifact_names")
        if not isinstance(names, list) or not all(isinstance(item, str) and item.strip() and "/" not in item and "\\" not in item for item in names):
            raise InvalidUpdateManifest("Update manifest artifact_names must be a list of safe file names.")
        if manifest["installer_name"] not in names:
            raise InvalidUpdateManifest("Update manifest artifact_names must include installer_name.")
    if "checksums" in manifest:
        checksums = manifest.get("checksums")
        if not isinstance(checksums, Mapping):
            raise InvalidUpdateManifest("Update manifest checksums must be an object.")
        for name, digest in checksums.items():
            if not isinstance(name, str) or not name.strip() or "/" in name or "\\" in name:
                raise InvalidUpdateManifest("Update manifest checksum names must be safe file names.")
            if not _SHA256_RE.match(str(digest or "")):
                raise InvalidUpdateManifest("Update manifest checksums must contain SHA256 values.")
        if str(checksums.get(manifest["installer_name"]) or "").lower() != manifest["installer_sha256"]:
            raise InvalidUpdateManifest("Update manifest checksum for installer_name must match installer_sha256.")
    if "update_manifest_name" in manifest:
        manifest_name = str(manifest.get("update_manifest_name") or "").strip()
        if not manifest_name or "/" in manifest_name or "\\" in manifest_name:
            raise InvalidUpdateManifest("Update manifest update_manifest_name is invalid.")
    if "release_notes_url" in manifest and str(manifest.get("release_notes_url") or "").strip():
        manifest["release_notes_url"] = _validate_https_download_url(str(manifest.get("release_notes_url") or ""), field="release_notes_url")
    return manifest


def _headers() -> Dict[str, str]:
    return {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}


def _urllib_get(url: str, *, timeout: float = 20.0) -> bytes:
    request = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateNetworkError("Could not reach the update server.") from exc


def _json_from_bytes(data: bytes) -> Any:
    try:
        return json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise InvalidUpdateManifest("Update response was not valid JSON.") from exc


def _validate_https_download_url(url: str, *, field: str) -> str:
    candidate = str(url or "").strip()
    parsed = urlparse(candidate)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise InvalidUpdateManifest(f"{field} must be an HTTPS URL.")
    return candidate


def _asset_from_payload(payload: Mapping[str, Any]) -> ReleaseAsset:
    return ReleaseAsset(
        name=str(payload.get("name") or ""),
        browser_download_url=_validate_https_download_url(str(payload.get("browser_download_url") or ""), field="release asset download URL"),
    )


def find_release_asset(release: Mapping[str, Any], asset_name: str) -> Optional[ReleaseAsset]:
    for asset in release.get("assets", []) or []:
        if not isinstance(asset, Mapping):
            continue
        if str(asset.get("name") or "") != asset_name:
            continue
        candidate = _asset_from_payload(asset)
        if candidate.browser_download_url:
            return candidate
    return None


def iter_candidate_releases(releases_payload: Any, *, channel: str) -> Iterable[Dict[str, Any]]:
    if isinstance(releases_payload, Mapping):
        releases: Sequence[Any] = [releases_payload]
    elif isinstance(releases_payload, Sequence):
        releases = releases_payload
    else:
        releases = []
    channel = str(channel or DEFAULT_UPDATE_CHANNEL).lower()
    for release in releases:
        if not isinstance(release, Mapping):
            continue
        if bool(release.get("draft")):
            continue
        if channel == "beta" and not bool(release.get("prerelease")):
            # Beta channels should prefer pre-releases. A manifest channel match still protects stable channels below.
            continue
        yield dict(release)


def select_best_candidate(candidates: Iterable[CandidateUpdate]) -> Optional[CandidateUpdate]:
    best: Optional[CandidateUpdate] = None
    for candidate in candidates:
        if best is None or compare_versions(candidate.latest_version, best.latest_version) > 0:
            best = candidate
    return best


class GitHubReleaseUpdateClient:
    def __init__(
        self,
        config: UpdateConfig | None = None,
        *,
        current_version: str | None = None,
        http_get: Callable[..., bytes] | None = None,
        download_dir: str | Path | None = None,
    ) -> None:
        self.config = config or UpdateConfig.from_env()
        self.current_version = normalize_version(current_version or get_app_version())
        self._http_get = http_get or _urllib_get
        self.download_dir = Path(download_dir) if download_dir else Path(app_data_dir()) / "updates"
        self._candidate: Optional[CandidateUpdate] = None

    def _get_json(self, url: str) -> Any:
        try:
            data = self._http_get(url, timeout=20.0)
        except UpdateNetworkError:
            raise
        except Exception as exc:
            raise UpdateNetworkError("Could not reach the update server.") from exc
        return _json_from_bytes(data)

    def _manifest_for_release(self, release: Mapping[str, Any]) -> Optional[CandidateUpdate]:
        manifest_asset = find_release_asset(release, self.config.manifest_name)
        if manifest_asset is None:
            return None
        manifest_payload = self._get_json(manifest_asset.browser_download_url)
        manifest = validate_update_manifest(manifest_payload, channel=self.config.channel)
        installer_asset = find_release_asset(release, str(manifest.get("installer_name") or ""))
        if installer_asset is None:
            raise InvalidUpdateManifest("Update installer asset listed in the manifest was not found on the release.")
        return CandidateUpdate(dict(manifest), dict(release), manifest_asset, installer_asset)

    def fetch_candidate_update(self) -> CandidateUpdate:
        if not self.config.configured:
            raise UpdateNotConfigured("Update repository owner/name are not configured.")
        releases_payload = self._get_json(self.config.releases_url)
        candidates: List[CandidateUpdate] = []
        first_manifest_error: Optional[InvalidUpdateManifest] = None
        for release in iter_candidate_releases(releases_payload, channel=self.config.channel):
            try:
                candidate = self._manifest_for_release(release)
                if candidate is not None:
                    candidates.append(candidate)
            except InvalidUpdateManifest as exc:
                if first_manifest_error is None:
                    first_manifest_error = exc
        best = select_best_candidate(candidates)
        if best is None:
            if first_manifest_error:
                raise first_manifest_error
            raise InvalidUpdateManifest("No release with a valid BioAuth update manifest was found.")
        self._candidate = best
        return best

    def check_for_update(self) -> Dict[str, Any]:
        try:
            candidate = self.fetch_candidate_update()
        except UpdateNotConfigured as exc:
            return {
                "ok": False,
                "state": "not_configured",
                "currentVersion": self.current_version,
                "latestVersion": "",
                "message": str(exc),
            }
        except UpdateNetworkError as exc:
            return {
                "ok": False,
                "state": "download_failed",
                "currentVersion": self.current_version,
                "latestVersion": "",
                "message": str(exc),
            }
        except InvalidUpdateManifest as exc:
            return {
                "ok": False,
                "state": "invalid_update_manifest",
                "currentVersion": self.current_version,
                "latestVersion": "",
                "message": str(exc),
            }

        latest = candidate.latest_version
        if compare_versions(latest, self.current_version) == 0:
            return {
                "ok": True,
                "state": "up_to_date",
                "currentVersion": self.current_version,
                "latestVersion": latest,
                "message": "BioAuth is up to date.",
                "manifest": candidate.manifest,
            }
        if compare_versions(latest, self.current_version) < 0:
            return {
                "ok": False,
                "state": "downgrade_rejected",
                "currentVersion": self.current_version,
                "latestVersion": latest,
                "message": "The release is older than the installed BioAuth version.",
                "manifest": candidate.manifest,
            }
        return {
            "ok": True,
            "state": "update_available",
            "currentVersion": self.current_version,
            "latestVersion": latest,
            "message": "A BioAuth update is available.",
            "mandatory": bool(candidate.manifest.get("mandatory")),
            "releaseNotes": str(candidate.manifest.get("release_notes") or ""),
            "installerName": candidate.installer_name,
            "manifestName": self.config.manifest_name,
            "artifactNames": list(candidate.manifest.get("artifact_names") or [candidate.installer_name, self.config.manifest_name]),
            "manifest": candidate.manifest,
        }

    def download_candidate(self, candidate: CandidateUpdate | None = None) -> Dict[str, Any]:
        candidate = candidate or self._candidate or self.fetch_candidate_update()
        if not is_update_available(self.current_version, candidate.latest_version):
            return {
                "ok": False,
                "state": "downgrade_rejected" if compare_versions(candidate.latest_version, self.current_version) < 0 else "up_to_date",
                "currentVersion": self.current_version,
                "latestVersion": candidate.latest_version,
                "message": "No newer installer is available to download.",
            }
        self.download_dir.mkdir(parents=True, exist_ok=True)
        final_path = self.download_dir / candidate.installer_name
        fd, tmp_name = tempfile.mkstemp(prefix="bioauth-update-", suffix=".tmp", dir=str(self.download_dir))
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            data = self._http_get(candidate.installer_asset.browser_download_url, timeout=120.0)
            tmp_path.write_bytes(data)
            calculated = sha256_file(tmp_path)
            expected = str(candidate.manifest.get("installer_sha256") or "").lower()
            if calculated.lower() != expected:
                tmp_path.unlink(missing_ok=True)
                final_path.unlink(missing_ok=True)
                raise HashVerificationError("Downloaded installer failed SHA256 verification.")
            shutil.move(str(tmp_path), str(final_path))
        except HashVerificationError:
            raise
        except UpdateNetworkError:
            tmp_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            tmp_path.unlink(missing_ok=True)
            raise UpdateNetworkError("Installer download failed.") from exc
        return {
            "ok": True,
            "state": "ready_to_install",
            "currentVersion": self.current_version,
            "latestVersion": candidate.latest_version,
            "message": "Update downloaded and verified. Install only if you approve the installer prompt.",
            "downloadedPath": str(final_path),
            "installerName": candidate.installer_name,
        }

    def safe_download_candidate(self, candidate: CandidateUpdate | None = None) -> Dict[str, Any]:
        try:
            return self.download_candidate(candidate)
        except HashVerificationError as exc:
            return {
                "ok": False,
                "state": "hash_verification_failed",
                "currentVersion": self.current_version,
                "latestVersion": candidate.latest_version if candidate else "",
                "message": str(exc),
            }
        except InvalidUpdateManifest as exc:
            return {
                "ok": False,
                "state": "invalid_update_manifest",
                "currentVersion": self.current_version,
                "latestVersion": candidate.latest_version if candidate else "",
                "message": str(exc),
            }
        except (UpdateNetworkError, UpdateNotConfigured) as exc:
            return {
                "ok": False,
                "state": "download_failed",
                "currentVersion": self.current_version,
                "latestVersion": candidate.latest_version if candidate else "",
                "message": str(exc),
            }


__all__ = [
    "CandidateUpdate",
    "GitHubReleaseUpdateClient",
    "HashVerificationError",
    "InvalidUpdateManifest",
    "MANIFEST_NAME",
    "RELEASE_CONFIG_NAME",
    "REQUIRED_MANIFEST_FIELDS",
    "ReleaseAsset",
    "UpdateConfig",
    "UpdateError",
    "UpdateNetworkError",
    "UpdateNotConfigured",
    "compare_versions",
    "default_release_config_paths",
    "find_release_asset",
    "is_update_available",
    "load_release_config",
    "sha256_file",
    "validate_update_manifest",
    "version_key",
]
