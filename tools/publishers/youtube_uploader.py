"""YouTube publisher tool for OpenMontage export bundles.

This module exposes the YouTube upload as a proper OpenMontage publish tool so it
can participate in the registry, dependency reporting, and result auditing. The
script wrapper in tools/publish/youtube_uploader.py remains available as a thin
CLI facade over the same execution logic.
"""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path
from typing import Any, Optional

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
)


class YouTubeUploader(BaseTool):
    """Upload a rendered export bundle to YouTube via OAuth 2.0."""

    name = "youtube_uploader"
    version = "0.1.0"
    tier = ToolTier.PUBLISH
    capability = "publish"
    provider = "youtube"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.API

    dependencies = [
        "python:googleapiclient",
        "python:google_auth_oauthlib",
        "python:google.auth",
    ]
    install_instructions = (
        "Install the optional Google client stack with: "
        "pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
    )

    capabilities = ["upload_video", "set_thumbnail"]
    supports = {
        "account_required": True,
        "network_required": True,
        "free": False,
        "uploads": True,
        "local_offline": False,
        "batch_upload": False,
    }
    best_for = [
        "publishing a finished OpenMontage export to a YouTube channel",
        "uploading a single final render with title, description, tags, and privacy",
        "headless / CI publishing with OAuth refresh tokens",
    ]
    not_good_for = [
        "offline local rendering without Google OAuth access",
        "non-YouTube publishing workflows",
        "bulk channel automation without explicit human approval",
    ]

    input_schema = {
        "type": "object",
        "required": ["video_path", "client_secrets_path"],
        "properties": {
            "video_path": {
                "type": "string",
                "description": "Path to the rendered video file to upload.",
            },
            "title": {
                "type": "string",
                "description": "YouTube title. Defaults to the filename when omitted.",
            },
            "description": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "client_secrets_path": {
                "type": "string",
                "description": "Path to the Google OAuth desktop client JSON file.",
            },
            "token_path": {
                "type": "string",
                "description": "Optional path to the refresh-token cache. Defaults to ~/.config/openmontage/.youtube-token.json or YOUTUBE_TOKEN_PATH.",
            },
            "privacy": {"type": "string", "enum": ["public", "private", "unlisted"]},
            "thumbnail_path": {"type": "string"},
            "export_path": {
                "type": "string",
                "description": "Optional export bundle path to read metadata and thumbnails from.",
            },
            "metadata_path": {"type": "string"},
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "video_id": {"type": "string"},
            "youtube_url": {"type": "string"},
            "privacy": {"type": "string"},
            "title": {"type": "string"},
            "thumbnail_set": {"type": "boolean"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=0, network_required=True
    )
    retry_policy = RetryPolicy(
        max_retries=5,
        backoff_seconds=2.0,
        retryable_errors=["HttpError_5xx", "TransientError", "ConnectionError"],
    )
    side_effects = [
        "uploads a video to YouTube",
        "writes an OAuth refresh token file to disk",
    ]
    user_visible_verification = [
        "Confirm the returned YouTube URL and the uploaded title/privacy status in the channel UI",
    ]

    @staticmethod
    def _token_cache_path(explicit_path: Optional[str] = None) -> Path:
        if explicit_path:
            return Path(explicit_path).expanduser()
        env_path = os.environ.get("YOUTUBE_TOKEN_PATH")
        if env_path:
            return Path(env_path).expanduser()
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")).expanduser()
        return config_home / "openmontage" / ".youtube-token.json"

    @staticmethod
    def _safe_write_json(path: Path, payload: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(payload)
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    @staticmethod
    def _scopes() -> list[str]:
        return ["https://www.googleapis.com/auth/youtube.upload"]

    @staticmethod
    def _import_google_clients() -> Any:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
            from googleapiclient.errors import HttpError
            from googleapiclient.http import MediaFileUpload
        except ImportError as exc:  # pragma: no cover - exercised by dependency check
            raise RuntimeError(
                "Google client libraries are not installed. Install the optional publisher stack: "
                "pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
            ) from exc
        return {
            "Request": Request,
            "Credentials": Credentials,
            "InstalledAppFlow": InstalledAppFlow,
            "build": build,
            "HttpError": HttpError,
            "MediaFileUpload": MediaFileUpload,
        }

    def _build_youtube_client(self, client_secrets_path: str, token_path: Optional[str] = None):
        google = self._import_google_clients()
        Request = google["Request"]
        Credentials = google["Credentials"]
        InstalledAppFlow = google["InstalledAppFlow"]
        build = google["build"]

        cache_path = self._token_cache_path(token_path)
        creds = None
        if cache_path.exists():
            creds = Credentials.from_authorized_user_file(str(cache_path), self._scopes())

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(client_secrets_path, self._scopes())
                creds = flow.run_local_server(port=0)
            self._safe_write_json(cache_path, creds.to_json())

        return build("youtube", "v3", credentials=creds)

    @staticmethod
    def _load_metadata(export_path: Optional[str] = None, metadata_path: Optional[str] = None) -> dict[str, Any]:
        if metadata_path:
            path = Path(metadata_path).expanduser()
        elif export_path:
            path = Path(export_path).expanduser() / "metadata" / "metadata.json"
        else:
            raise FileNotFoundError("Either export_path or metadata_path must be provided.")
        if not path.is_file():
            raise FileNotFoundError(f"metadata.json not found at {path}")
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _get_video_file(export_path: Optional[str] = None, video_path: Optional[str] = None) -> Path:
        if video_path:
            candidate = Path(video_path).expanduser()
            if candidate.is_file():
                return candidate
            raise FileNotFoundError(f"video_path not found: {candidate}")
        if not export_path:
            raise FileNotFoundError("video_path or export_path required")
        bundle = Path(export_path).expanduser()
        video_dir = bundle / "video"
        if not video_dir.is_dir():
            raise FileNotFoundError(f"video directory not found at {video_dir}")
        files = sorted(
            p for p in video_dir.iterdir() if p.is_file() and p.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}
        )
        if not files:
            raise FileNotFoundError(f"No video file found in {video_dir}")
        return files[0]

    @staticmethod
    def _resolve_thumbnail_path(export_path: Optional[str], explicit_path: Optional[str]) -> Optional[str]:
        if explicit_path:
            return explicit_path
        if not export_path:
            return None
        thumb_dir = Path(export_path).expanduser() / "thumbnails"
        if not thumb_dir.is_dir():
            return None
        matches = sorted(
            p for p in thumb_dir.iterdir() if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg"}
        )
        if not matches:
            return None
        return str(matches[0])

    def _upload_video(self, youtube: Any, body: dict[str, Any], media_path: str) -> dict[str, Any]:
        try:
            google = self._import_google_clients()
            MediaFileUpload = google["MediaFileUpload"]
            HttpError = google["HttpError"]
        except RuntimeError:
            MediaFileUpload = None
            HttpError = None

        media_body = (
            MediaFileUpload(media_path, chunksize=10 * 1024 * 1024, resumable=True)
            if MediaFileUpload is not None
            else object()
        )

        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media_body,
        )

        response: Optional[dict[str, Any]] = None
        retries = 0
        while response is None:
            try:
                status, response = request.next_chunk()
                if status is not None:
                    progress = status.progress() if hasattr(status, "progress") else 0.0
                    if progress and progress < 1.0:
                        pass
            except Exception as exc:  # noqa: BLE001 - handle transient upload errors only
                if HttpError is not None and isinstance(exc, HttpError):
                    if getattr(exc, "resp", None) is not None and getattr(exc.resp, "status", 0) < 500:
                        raise
                retries += 1
                if retries > self.retry_policy.max_retries:
                    raise RuntimeError(f"Upload failed after {retries} transient retries: {exc}") from exc
                backoff = min(self.retry_policy.backoff_seconds * (2 ** (retries - 1)), 60.0)
                time.sleep(backoff)
                continue
        return response

    def _set_thumbnail(self, youtube: Any, video_id: str, thumbnail_path: str) -> bool:
        try:
            google = self._import_google_clients()
            MediaFileUpload = google["MediaFileUpload"]
        except RuntimeError:
            MediaFileUpload = None
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=(MediaFileUpload(thumbnail_path) if MediaFileUpload is not None else object()),
            ).execute()
            return True
        except Exception:  # pragma: no cover - network-dependent path
            return False

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        video_path = inputs.get("video_path")
        export_path = inputs.get("export_path")
        if not video_path and export_path:
            try:
                video_path = str(self._get_video_file(video_path=None, export_path=export_path))
            except FileNotFoundError as exc:
                return ToolResult(success=False, error=str(exc))
        if not video_path:
            return ToolResult(success=False, error="video_path or export_path is required")
        try:
            final_video = self._get_video_file(video_path=video_path, export_path=export_path)
        except FileNotFoundError as exc:
            return ToolResult(success=False, error=str(exc))

        client_secrets = inputs.get("client_secrets_path")
        if not client_secrets:
            return ToolResult(success=False, error="client_secrets_path is required")

        metadata = self._load_metadata(
            export_path=inputs.get("export_path"),
            metadata_path=inputs.get("metadata_path"),
        ) if inputs.get("export_path") or inputs.get("metadata_path") else {}

        title = inputs.get("title") or metadata.get("title") or final_video.name
        description = inputs.get("description") or metadata.get("description") or ""
        tags = inputs.get("tags") or metadata.get("tags") or []
        privacy = inputs.get("privacy") or metadata.get("visibility") or "private"
        thumbnail_path = inputs.get("thumbnail_path") or self._resolve_thumbnail_path(
            inputs.get("export_path"), None
        )

        try:
            youtube = self._build_youtube_client(client_secrets, inputs.get("token_path"))
        except Exception as exc:  # pragma: no cover - real OAuth flow is interactive
            return ToolResult(success=False, error=f"Failed to initialize YouTube OAuth client: {exc}")

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
            },
            "status": {"privacyStatus": privacy},
        }

        try:
            response = self._upload_video(youtube, body, str(final_video))
        except Exception as exc:
            return ToolResult(success=False, error=f"YouTube upload failed: {exc}")

        video_id = response.get("id") if isinstance(response, dict) else None
        if not video_id:
            return ToolResult(success=False, error=f"Upload response missing video id: {response}")

        thumbnail_set = False
        if thumbnail_path and Path(thumbnail_path).expanduser().is_file():
            thumbnail_set = self._set_thumbnail(youtube, video_id, thumbnail_path)

        return ToolResult(
            success=True,
            data={
                "video_id": video_id,
                "youtube_url": f"https://youtu.be/{video_id}",
                "privacy": privacy,
                "title": title,
                "thumbnail_set": thumbnail_set,
            },
            artifacts=[str(final_video)],
            cost_usd=0.0,
        )
