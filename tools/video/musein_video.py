"""Musein CLI video provider for OpenMontage."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)
from tools.musein_cli import MuseinCli, MuseinCliError, find_musein_executable


class MuseinVideo(BaseTool):
    name = "musein_video"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "musein"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.ASYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies: list[str] = []
    install_instructions = (
        "Install Musein CLI, sign in with `musein login --method key`, and verify "
        "the session with `musein whoami`. OpenMontage never needs the key in .env."
    )
    capabilities = [
        "text_to_video",
        "image_to_video",
        "reference_to_video",
        "video_edit",
        "dynamic_model_catalog",
        "provider_point_quote",
        "local_reference_upload",
    ]
    supports = {
        "text_to_video": True,
        "image_to_video": True,
        "reference_to_video": True,
        "video_edit": True,
        "reference_image": True,
        "multiple_reference_images": True,
        "first_last_frame": True,
        "reference_video": True,
        "reference_audio": True,
        "native_audio": True,
        "aspect_ratio": True,
        "dynamic_models": True,
        "live_point_quote": True,
        "cost_currency": "musein_points",
        "usd_cost_known": False,
    }
    best_for = [
        "multi-model AI video generation through one authenticated CLI",
        "cinematic text-to-video with live provider pricing",
        "image, video, and audio referenced video generation",
        "agent workflows that need JSON results and recoverable task IDs",
    ]
    not_good_for = [
        "offline generation",
        "unattended retries after an unknown submission outcome",
        "USD budget tracking without an explicit point conversion rate",
    ]
    agent_skills = ["musein-cli", "ai-video-gen"]

    input_schema = {
        "type": "object",
        "oneOf": [
            {
                "properties": {"task_action": {"enum": ["generate"]}},
                "required": ["prompt", "model", "output_path"],
            },
            {
                "properties": {"task_action": {"const": "collect"}},
                "required": ["task_action", "task_id", "output_path"],
            },
            {
                "properties": {"task_action": {"const": "resolve"}},
                "required": ["task_action"],
                "anyOf": [
                    {"required": ["client_request_id"]},
                    {"required": ["task_id"]},
                ],
            },
        ],
        "properties": {
            "task_action": {
                "type": "string",
                "enum": ["generate", "collect", "resolve"],
                "default": "generate",
                "description": (
                    "generate submits once; collect downloads an existing task; "
                    "resolve performs read-only dispatch reconciliation"
                ),
            },
            "task_id": {"type": "string", "minLength": 1},
            "client_request_id": {"type": "string", "minLength": 1},
            "prompt": {"type": "string", "minLength": 1},
            "model": {
                "type": "string",
                "minLength": 1,
                "description": "Exact live model id from `musein models --type video`; no silent fallback.",
            },
            "operation": {
                "type": "string",
                "enum": ["text_to_video", "image_to_video", "reference_to_video", "video_edit"],
                "default": "text_to_video",
            },
            "duration": {"type": ["string", "integer"]},
            "aspect_ratio": {"type": "string"},
            "resolution": {"type": "string"},
            "generate_audio": {"type": "boolean"},
            "watermark": {"type": "boolean"},
            "reference_image_path": {"type": "string"},
            "reference_image_url": {"type": "string"},
            "reference_image_paths": {"type": "array", "items": {"type": "string"}},
            "reference_image_urls": {"type": "array", "items": {"type": "string"}},
            "last_image_path": {"type": "string"},
            "last_image_url": {"type": "string"},
            "reference_video_path": {"type": "string"},
            "reference_video_url": {"type": "string"},
            "reference_video_paths": {"type": "array", "items": {"type": "string"}},
            "reference_video_urls": {"type": "array", "items": {"type": "string"}},
            "reference_audio_path": {"type": "string"},
            "reference_audio_url": {"type": "string"},
            "model_params": {"type": "object"},
            "allow_model_fallback": {
                "type": "boolean",
                "default": False,
                "description": (
                    "Explicitly allow Musein to substitute an available model. "
                    "Requires approved_model from dry_run."
                ),
            },
            "approved_model": {
                "type": "string",
                "minLength": 1,
                "description": "Resolved model id shown by the approved dry_run quote.",
            },
            "approved_points": {
                "type": "integer",
                "minimum": 1,
                "description": (
                    "Highest re-quoted Musein point estimate approved after dry_run. "
                    "The final points_consumed billing record remains authoritative."
                ),
            },
            "timeout_seconds": {"type": "integer", "minimum": 60, "default": 900},
            "output_path": {"type": "string"},
        },
    }
    output_schema = {
        "type": "object",
        "required": ["provider", "task_action"],
        "properties": {
            "provider": {"const": "musein"},
            "task_action": {"enum": ["generate", "collect", "resolve"]},
            "model": {"type": ["string", "null"]},
            "output_path": {"type": "string"},
            "task_id": {"type": ["string", "null"]},
            "points_estimated": {"type": ["integer", "null"]},
            "points_consumed": {"type": ["integer", "null"]},
        },
    }
    resource_profile = ResourceProfile(
        cpu_cores=1,
        ram_mb=256,
        vram_mb=0,
        disk_mb=2048,
        network_required=True,
    )
    retry_policy = RetryPolicy(max_retries=0)
    idempotency_key_fields = ["prompt", "model", "operation", "duration", "aspect_ratio"]
    side_effects = [
        "prices the exact request before submission",
        "spends Musein points after approval",
        "uploads local reference files through Musein CLI",
        "writes a downloaded MP4 to output_path",
        "records recoverable task state in the Musein CLI ledger",
    ]
    fallback_tools: list[str] = []
    user_visible_verification = [
        "Open the generated MP4 and inspect prompt adherence, motion coherence, and audio",
        "Confirm task_id and point quote are present in the asset metadata",
    ]

    def _resolve_executable(self) -> Path | None:
        return find_musein_executable()

    @staticmethod
    def _credentials_path() -> Path:
        return Path.home() / ".musein" / "credentials"

    def get_status(self) -> ToolStatus:
        executable = self._resolve_executable()
        has_auth = bool(os.environ.get("MUSEIN_KEY") or os.environ.get("MUSEIN_TOKEN"))
        credentials = self._credentials_path()
        has_auth = has_auth or (credentials.is_file() and credentials.stat().st_size > 0)
        return ToolStatus.AVAILABLE if executable and has_auth else ToolStatus.UNAVAILABLE

    def _client(self) -> MuseinCli:
        executable = self._resolve_executable()
        return MuseinCli(executable=executable)

    @staticmethod
    def _usd_per_point() -> float | None:
        raw = os.environ.get("MUSEIN_USD_PER_POINT", "").strip()
        if not raw:
            return None
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError("MUSEIN_USD_PER_POINT must be a finite number greater than 0") from exc
        if not math.isfinite(value) or value <= 0:
            raise ValueError("MUSEIN_USD_PER_POINT must be a finite number greater than 0")
        return value

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        rate = self._usd_per_point()
        points = inputs.get("points_estimated") or inputs.get("approved_points")
        if rate is None or points is None:
            return 0.0
        return round(float(points) * rate, 4)

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return float(inputs.get("timeout_seconds", 900))

    @staticmethod
    def _values(inputs: dict[str, Any], singular: Iterable[str], plural: Iterable[str]) -> list[str]:
        values: list[str] = []
        for key in plural:
            raw = inputs.get(key) or []
            if isinstance(raw, list):
                values.extend(str(value) for value in raw if str(value).strip())
        for key in singular:
            value = inputs.get(key)
            if value and str(value).strip():
                values.append(str(value))
        return list(dict.fromkeys(values))

    def _request(self, inputs: dict[str, Any], *, require_output: bool) -> dict[str, Any]:
        prompt = str(inputs.get("prompt") or "").strip()
        model = str(inputs.get("model") or "").strip()
        if not prompt:
            raise ValueError("prompt is required")
        if not model:
            raise ValueError("model is required; select an exact id from the live Musein catalog")

        operation = str(inputs.get("operation") or "text_to_video")
        allowed = {"text_to_video", "image_to_video", "reference_to_video", "video_edit"}
        if operation not in allowed:
            raise ValueError(f"Unsupported Musein video operation: {operation}")

        params = dict(inputs.get("model_params") or {})
        common = {
            "duration": inputs.get("duration"),
            "ratio": inputs.get("aspect_ratio"),
            "resolution": inputs.get("resolution"),
            "generate_audio": inputs.get("generate_audio"),
            "watermark": inputs.get("watermark"),
        }
        params.update({key: value for key, value in common.items() if value is not None})

        images = self._values(
            inputs,
            ("reference_image_path", "reference_image_url", "image_url"),
            ("reference_image_paths", "reference_image_urls"),
        )
        videos = self._values(
            inputs,
            ("reference_video_path", "reference_video_url", "video_path", "video_url"),
            ("reference_video_paths", "reference_video_urls"),
        )
        audio_values = self._values(
            inputs,
            ("reference_audio_path", "reference_audio_url", "audio_path", "audio_url"),
            (),
        )
        if len(audio_values) > 1:
            raise ValueError("Musein CLI accepts one reference audio item per request")
        if operation == "image_to_video" and not images:
            raise ValueError("image_to_video requires a reference image")
        if operation == "reference_to_video" and not (images or videos):
            raise ValueError("reference_to_video requires at least one image or video reference")
        if operation == "video_edit" and not videos:
            raise ValueError("video_edit requires a reference video")

        output_path: Path | None = None
        if require_output:
            raw_output = str(inputs.get("output_path") or "").strip()
            if not raw_output:
                raise ValueError("output_path is required")
            output_path = Path(raw_output).expanduser()
            if output_path.suffix.lower() != ".mp4":
                raise ValueError("Musein video output_path must end in .mp4")

        end_image = inputs.get("last_image_path") or inputs.get("last_image_url")
        return {
            "generation_type": "video",
            "model": model,
            "prompt": prompt,
            "params": params,
            "images": images,
            "end_image": str(end_image) if end_image else None,
            "videos": videos,
            "audio": audio_values[0] if audio_values else None,
            "wait_seconds": int(inputs.get("timeout_seconds", 900)),
            "strict_model": not bool(inputs.get("allow_model_fallback", False)),
            "output_path": output_path,
            "operation": operation,
        }

    @staticmethod
    def _usage(payload: dict[str, Any]) -> dict[str, Any]:
        return payload.get("usage") if isinstance(payload.get("usage"), dict) else {}

    @classmethod
    def _estimated_points(cls, payload: dict[str, Any]) -> int:
        usage = cls._usage(payload)
        value = usage.get("points_estimated")
        if not isinstance(value, (int, float)):
            value = payload.get("points_estimated")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
        raise ValueError("Musein response did not include a point quote")

    @classmethod
    def _consumed_points(cls, payload: dict[str, Any]) -> int | None:
        value = cls._usage(payload).get("points_consumed")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
        return None

    def dry_run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        try:
            request = self._request(inputs, require_output=False)
            output = Path(inputs.get("output_path") or Path.cwd() / "outputs")
            output_dir = output.parent if output.suffix else output
            quote = self._client().quote_generation(
                **{key: value for key, value in request.items() if key not in {"output_path", "operation"}},
                output_dir=output_dir,
            )
            points = self._estimated_points(quote)
            rate = self._usd_per_point()
            usage = quote.get("usage") if isinstance(quote.get("usage"), dict) else {}
            return {
                "tool": self.name,
                "status": quote.get("status", "estimated"),
                "requested_model": request["model"],
                "model": quote.get("model_id") or request["model"],
                "operation": request["operation"],
                "points_estimated": points,
                "balance_before": usage.get("balance_before"),
                "balance_remaining": usage.get("balance_remaining"),
                "estimated_cost_usd": round(points * rate, 4) if rate is not None else None,
                "usd_conversion_source": "MUSEIN_USD_PER_POINT" if rate is not None else None,
                "cost_currency": "musein_points",
                "cost_estimate_confidence": "provider_quote",
                "paid_submission": False,
                "would_execute": False,
                "requires_user_approval": True,
                "strict_model": request["strict_model"],
                "overrides": quote.get("overrides") or {},
                "schema_version": quote.get("schema_version"),
            }
        except (MuseinCliError, ValueError) as exc:
            return {
                "tool": self.name,
                "status": "failed",
                "would_execute": False,
                "paid_submission": False,
                "error": str(exc),
            }

    @staticmethod
    def _find_download(staging_dir: Path) -> Path:
        candidates = [
            path
            for path in staging_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}
        ]
        if len(candidates) != 1:
            raise ValueError(
                f"Musein CLI downloaded {len(candidates)} video artifacts; expected exactly one"
            )
        if candidates[0].suffix.lower() != ".mp4":
            raise ValueError(f"Musein CLI returned unsupported video container: {candidates[0].suffix}")
        return candidates[0]

    @staticmethod
    def _validate_video(path: Path) -> dict[str, Any]:
        if not path.is_file() or path.stat().st_size < 1024:
            raise ValueError("downloaded artifact is empty or too small to be a valid video")
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            header = path.read_bytes()[:64]
            if b"ftyp" not in header:
                raise ValueError("downloaded artifact is not a recognizable MP4")
            return {"file_size_bytes": path.stat().st_size}

        process = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
            shell=False,
        )
        if process.returncode != 0:
            raise ValueError("downloaded artifact failed ffprobe validation")
        try:
            probe = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("ffprobe returned invalid JSON") from exc
        video_stream = next(
            (stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"),
            None,
        )
        if not video_stream:
            raise ValueError("downloaded artifact has no video stream")
        duration = float((probe.get("format") or {}).get("duration") or 0)
        if duration <= 0:
            raise ValueError("downloaded artifact has no positive duration")
        return {
            "file_size_bytes": path.stat().st_size,
            "file_size_mb": round(path.stat().st_size / (1024 * 1024), 2),
            "duration_seconds": duration,
            "video_width": int(video_stream.get("width") or 0),
            "video_height": int(video_stream.get("height") or 0),
            "video_codec": str(video_stream.get("codec_name") or ""),
        }

    @staticmethod
    def _error_data(exc: MuseinCliError, staging_dir: Path | None) -> dict[str, Any]:
        status_by_code = {
            2: "invalid_request",
            3: "unauthenticated",
            4: "insufficient_credits",
            5: "generation_failed",
            6: "wait_timeout",
            9: "dispatch_unknown",
            10: "service_unavailable",
            124: "cli_process_timeout",
            127: "cli_unavailable",
        }
        return {
            "provider": "musein",
            "error_type": status_by_code.get(exc.returncode, "cli_error"),
            "cli_exit_code": exc.returncode,
            "cli_code": exc.cli_code,
            "server_code": exc.server_code,
            "next_step": exc.next_step,
            "task_id": exc.task_id,
            "resolution_id": exc.resolution_id,
            "retry_safe": False,
            "requires_manual_resolution": exc.returncode == 9,
            "requires_collection": exc.returncode == 6 and bool(exc.task_id),
            "recovery_staging_dir": str(staging_dir) if staging_dir else None,
        }

    @staticmethod
    def _output_path(inputs: dict[str, Any]) -> Path:
        raw_output = str(inputs.get("output_path") or "").strip()
        if not raw_output:
            raise ValueError("output_path is required")
        output_path = Path(raw_output).expanduser()
        if output_path.suffix.lower() != ".mp4":
            raise ValueError("Musein video output_path must end in .mp4")
        if output_path.exists():
            raise ValueError(f"Refusing to overwrite existing output_path: {output_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        return output_path

    @staticmethod
    def _staging_dir(output_path: Path) -> Path:
        return Path(
            tempfile.mkdtemp(prefix=f".{output_path.stem}.musein-", dir=output_path.parent)
        )

    def _publish_result(
        self,
        *,
        payload: dict[str, Any],
        output_path: Path,
        staging_dir: Path,
        started: float,
        task_action: str,
        requested_model: str | None,
        operation: str | None,
        prompt: str | None,
        quoted_points: int | None,
    ) -> ToolResult:
        rate = self._usd_per_point()
        downloaded = self._find_download(staging_dir)
        probe = self._validate_video(downloaded)
        downloaded.replace(output_path)
        try:
            staging_dir.rmdir()
        except OSError:
            pass

        usage = self._usage(payload)
        points_consumed = self._consumed_points(payload)
        if quoted_points is None:
            try:
                quoted_points = self._estimated_points(payload)
            except ValueError:
                quoted_points = None
        billed_points = points_consumed if points_consumed is not None else quoted_points
        cost_usd = round(billed_points * rate, 4) if rate and billed_points is not None else None
        estimated_cost_usd = (
            round(quoted_points * rate, 4) if rate and quoted_points is not None else None
        )
        actual_cost_usd = (
            round(points_consumed * rate, 4)
            if rate and points_consumed is not None
            else None
        )
        task_id = _payload_string(payload, ("task_id", "taskId"))
        model = str(payload.get("model_id") or requested_model or "") or None
        return ToolResult(
            success=True,
            data={
                "provider": "musein",
                "task_action": task_action,
                "requested_model": requested_model,
                "model": model,
                "operation": operation,
                "prompt": prompt,
                "task_id": task_id,
                "points_estimated": quoted_points,
                "points_consumed": points_consumed,
                "balance_before": usage.get("balance_before"),
                "balance_remaining": usage.get("balance_remaining"),
                "cost_currency": "musein_points",
                "cost_provenance": (
                    "actual_from_usage"
                    if points_consumed is not None
                    else "estimate_only_missing_usage"
                ),
                "cost_usd": cost_usd,
                "estimated_cost_usd": estimated_cost_usd,
                "actual_cost_usd": actual_cost_usd,
                "usd_conversion_source": "MUSEIN_USD_PER_POINT" if rate else None,
                "overrides": payload.get("overrides") or {},
                "output": str(output_path),
                "output_path": str(output_path),
                "format": "mp4",
                "schema_version": payload.get("schema_version"),
                **probe,
            },
            artifacts=[str(output_path)],
            cost_usd=cost_usd,  # type: ignore[arg-type]
            duration_seconds=round(time.monotonic() - started, 2),
            model=model,
        )

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.monotonic()
        staging_dir: Path | None = None
        try:
            task_action = str(inputs.get("task_action") or "generate").strip().lower()
            if task_action == "resolve":
                identifier = str(
                    inputs.get("client_request_id") or inputs.get("task_id") or ""
                ).strip()
                if not identifier:
                    raise ValueError("client_request_id or task_id is required for resolve")
                payload = self._client().resolve_task(identifier)
                return ToolResult(
                    success=True,
                    data={
                        "provider": "musein",
                        "task_action": "resolve",
                        "identifier": identifier,
                        **payload,
                    },
                    cost_usd=0.0,
                    duration_seconds=round(time.monotonic() - started, 2),
                )

            if task_action == "collect":
                task_id = str(inputs.get("task_id") or "").strip()
                if not task_id:
                    raise ValueError("task_id is required for collect")
                self._usd_per_point()
                output_path = self._output_path(inputs)
                staging_dir = self._staging_dir(output_path)
                payload = self._client().collect_task(
                    task_id=task_id,
                    output_dir=staging_dir,
                    wait_seconds=int(inputs.get("timeout_seconds", 900)),
                )
                return self._publish_result(
                    payload=payload,
                    output_path=output_path,
                    staging_dir=staging_dir,
                    started=started,
                    task_action="collect",
                    requested_model=None,
                    operation=None,
                    prompt=None,
                    quoted_points=None,
                )

            if task_action != "generate":
                raise ValueError(f"Unsupported Musein task_action: {task_action}")

            self._usd_per_point()
            request = self._request(inputs, require_output=True)
            output_path: Path = request.pop("output_path")
            if output_path.exists():
                return ToolResult(
                    success=False,
                    error=f"Refusing to overwrite existing output_path: {output_path}",
                )
            approved_points = inputs.get("approved_points")
            if (
                not isinstance(approved_points, int)
                or isinstance(approved_points, bool)
                or approved_points <= 0
            ):
                return ToolResult(
                    success=False,
                    error=(
                        "approved_points is required. Run dry_run(), show the exact Musein "
                        "point quote to the user, then pass the approved maximum."
                    ),
                )

            output_path.parent.mkdir(parents=True, exist_ok=True)
            client = self._client()
            generation_args = {
                key: value for key, value in request.items() if key != "operation"
            }
            quote = client.quote_generation(**generation_args, output_dir=output_path.parent)
            quoted_points = self._estimated_points(quote)
            quoted_model = str(quote.get("model_id") or request["model"])
            if request["strict_model"] and quoted_model != request["model"]:
                return ToolResult(
                    success=False,
                    data={
                        "provider": "musein",
                        "requested_model": request["model"],
                        "quoted_model": quoted_model,
                        "retry_safe": False,
                    },
                    error="Musein changed the model during a strict quote; no generation was submitted.",
                )
            if not request["strict_model"]:
                approved_model = str(inputs.get("approved_model") or "").strip()
                if not approved_model or approved_model != quoted_model:
                    return ToolResult(
                        success=False,
                        data={
                            "provider": "musein",
                            "requested_model": request["model"],
                            "quoted_model": quoted_model,
                            "approved_model": approved_model or None,
                            "retry_safe": False,
                        },
                        error=(
                            "Model fallback requires approved_model matching the current dry-run "
                            "quote; no generation was submitted."
                        ),
                    )
            if quoted_points > approved_points:
                return ToolResult(
                    success=False,
                    data={
                        "provider": "musein",
                        "model": request["model"],
                        "points_estimated": quoted_points,
                        "approved_points": approved_points,
                        "retry_safe": False,
                    },
                    error=(
                        f"Musein quote increased to {quoted_points} points, above the approved "
                        f"maximum of {approved_points}; no generation was submitted."
                    ),
                )

            staging_dir = self._staging_dir(output_path)
            payload = client.generate(**generation_args, output_dir=staging_dir)
            return self._publish_result(
                payload=payload,
                output_path=output_path,
                staging_dir=staging_dir,
                started=started,
                task_action="generate",
                requested_model=request["model"],
                operation=request["operation"],
                prompt=request["prompt"],
                quoted_points=quoted_points,
            )
        except MuseinCliError as exc:
            return ToolResult(
                success=False,
                data=self._error_data(exc, staging_dir),
                error=str(exc),
                duration_seconds=round(time.monotonic() - started, 2),
            )
        except (OSError, ValueError) as exc:
            return ToolResult(
                success=False,
                data={
                    "provider": "musein",
                    "retry_safe": False,
                    "recovery_staging_dir": str(staging_dir) if staging_dir else None,
                },
                error=str(exc),
                duration_seconds=round(time.monotonic() - started, 2),
            )


def _payload_string(payload: Any, keys: Iterable[str]) -> str | None:
    key_set = set(keys)
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in key_set and isinstance(value, str) and value.strip():
                return value.strip()
        for value in payload.values():
            found = _payload_string(value, key_set)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _payload_string(value, key_set)
            if found:
                return found
    return None
