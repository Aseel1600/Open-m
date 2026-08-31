"""Safe subprocess adapter for the agent-oriented Musein CLI.

The CLI owns authentication and remote task recovery. OpenMontage passes no
long-lived key on the command line and never retries a paid submission here.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable


_KEY_RE = re.compile(r"\bmusein_sk_[A-Za-z0-9_-]+", re.IGNORECASE)
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]+=*", re.IGNORECASE)
_RESOLVE_COMMAND_RE = re.compile(
    r"\bmusein\s+task\s+resolve\s+([A-Za-z0-9._:-]+)", re.IGNORECASE
)
_SUPPORTED_SCHEMA_VERSIONS = {"musein.cli.v1"}


def _redact(value: str) -> str:
    value = _KEY_RE.sub("[REDACTED]", value or "")
    return _BEARER_RE.sub("Bearer [REDACTED]", value)


def find_musein_executable() -> Path | None:
    """Resolve Musein without requiring a fresh shell after Windows install."""
    explicit = os.environ.get("MUSEIN_CLI_PATH", "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_file():
            return path.resolve()

    discovered = shutil.which("musein")
    if discovered:
        return Path(discovered).resolve()

    if os.name == "nt":
        roots = []
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            roots.append(Path(local_app_data))
        roots.append(Path.home() / "AppData" / "Local")
        for root in roots:
            candidate = root / "Programs" / "Musein" / "musein.exe"
            if candidate.is_file():
                return candidate.resolve()
    return None


class MuseinCliError(RuntimeError):
    """A structured CLI failure with conservative retry semantics."""

    def __init__(
        self,
        message: str,
        *,
        returncode: int,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(_redact(message))
        self.returncode = returncode
        self.payload = payload or {}
        error = self.payload.get("error")
        error_data = error if isinstance(error, dict) else {}
        self.cli_code = str(error_data.get("cli_code") or "").strip() or None
        self.server_code = error_data.get("server_code")
        self.next_step = _redact(str(error_data.get("next_step") or "").strip()) or None
        self.task_id = _find_string(self.payload, ("task_id", "taskId"))
        self.resolution_id = _find_string(
            self.payload, ("client_request_id", "clientRequestId")
        )
        if self.resolution_id is None and self.next_step:
            match = _RESOLVE_COMMAND_RE.search(self.next_step)
            if match:
                self.resolution_id = match.group(1)
        # The CLI may have reached the provider even for an ordinary transport
        # failure. Exit 9 explicitly means dispatch_unknown. The adapter never
        # auto-retries any paid command; a human/agent must inspect first.
        self.retry_safe = False


def _find_string(payload: Any, keys: Iterable[str]) -> str | None:
    key_set = set(keys)
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in key_set and isinstance(value, str) and value.strip():
                return value.strip()
        for value in payload.values():
            found = _find_string(value, key_set)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_string(value, key_set)
            if found:
                return found
    return None


class MuseinCli:
    """JSON-only Musein CLI client. It never invokes a shell."""

    def __init__(
        self,
        *,
        executable: str | Path | None = None,
        endpoint: str | None = None,
    ) -> None:
        resolved = Path(executable).expanduser() if executable else find_musein_executable()
        if resolved is None or not resolved.is_file():
            raise MuseinCliError(
                "Musein CLI executable was not found. Install it or set MUSEIN_CLI_PATH.",
                returncode=127,
            )
        self.executable = resolved.resolve()
        self.endpoint = (endpoint or os.environ.get("MUSEIN_ENDPOINT") or "ai").strip()

    def _global_flags(self) -> list[str]:
        return [
            "--endpoint",
            self.endpoint,
            "--json",
            "--quiet",
            "--no-color",
            "--timeout=60s",
        ]

    def run(self, args: list[str], *, timeout_seconds: int = 120) -> dict[str, Any]:
        command = [str(self.executable), *args, *self._global_flags()]
        kwargs: dict[str, Any] = {
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "timeout": timeout_seconds,
            "check": False,
            "shell": False,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            process = subprocess.run(command, **kwargs)
        except subprocess.TimeoutExpired as exc:
            raise MuseinCliError(
                "Musein CLI timed out. Inspect the local task ledger before retrying.",
                returncode=124,
            ) from exc
        except OSError as exc:
            raise MuseinCliError(str(exc), returncode=127) from exc

        payload: dict[str, Any] = {}
        stdout = (process.stdout or "").strip()
        if stdout:
            try:
                parsed = json.loads(stdout)
                if isinstance(parsed, dict):
                    payload = parsed
            except json.JSONDecodeError:
                if process.returncode == 0:
                    raise MuseinCliError(
                        "Musein CLI returned non-JSON stdout in JSON mode.",
                        returncode=0,
                    )

        if process.returncode != 0:
            error = payload.get("error")
            if isinstance(error, dict):
                detail = error.get("message") or payload.get("message")
            else:
                detail = payload.get("message") or error
            if isinstance(detail, (dict, list)):
                detail = json.dumps(detail, ensure_ascii=False)
            message = str(detail or (process.stderr or "").strip() or "Musein CLI failed")
            raise MuseinCliError(
                message,
                returncode=process.returncode,
                payload=payload,
            )

        schema_version = payload.get("schema_version")
        if schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
            raise MuseinCliError(
                f"Unsupported Musein CLI schema_version: {schema_version!r}.",
                returncode=0,
                payload=payload,
            )
        return payload

    def build_generation_args(
        self,
        *,
        generation_type: str,
        model: str,
        prompt: str,
        output_dir: str | Path,
        wait_seconds: int,
        dry_run: bool,
        params: dict[str, Any],
        images: Iterable[str] = (),
        end_image: str | None = None,
        videos: Iterable[str] = (),
        audio: str | None = None,
        strict_model: bool = True,
    ) -> list[str]:
        args = [
            "gen",
            "--type",
            generation_type,
            "--model",
            model,
            "--prompt",
            prompt,
            "--quantity",
            "1",
            "--output",
            str(Path(output_dir)),
        ]
        if strict_model:
            # OpenMontage asks the user to approve an exact model and quote.
            # Musein itself allows fallback by default, so opting out of this
            # flag is exposed explicitly rather than happening silently.
            args.insert(5, "--strict-model")
        for image in images:
            args.extend(["--image", str(image)])
        if end_image:
            args.extend(["--end-image", str(end_image)])
        for video in videos:
            args.extend(["--video", str(video)])
        if audio:
            args.extend(["--audio", str(audio)])
        for key in sorted(params):
            value = params[key]
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                args.extend(["--param-json", f"{key}={encoded}"])
            else:
                if isinstance(value, bool):
                    value = "true" if value else "false"
                args.extend(["--param", f"{key}={value}"])
        if dry_run:
            args.append("--dry-run")
        else:
            args.append(f"--wait={int(wait_seconds)}s")
        return args

    def quote_generation(self, **kwargs: Any) -> dict[str, Any]:
        args = self.build_generation_args(dry_run=True, **kwargs)
        return self.run(args, timeout_seconds=120)

    def generate(self, **kwargs: Any) -> dict[str, Any]:
        wait_seconds = int(kwargs.get("wait_seconds", 900))
        args = self.build_generation_args(dry_run=False, **kwargs)
        return self.run(args, timeout_seconds=wait_seconds + 120)

    def whoami(self) -> dict[str, Any]:
        return self.run(["whoami"], timeout_seconds=30)

    def list_models(self, generation_type: str) -> dict[str, Any]:
        return self.run(["models", "--type", generation_type], timeout_seconds=60)

    def show_model(self, model: str) -> dict[str, Any]:
        return self.run(["models", "show", model], timeout_seconds=60)

    def collect_task(
        self,
        *,
        task_id: str,
        output_dir: str | Path,
        wait_seconds: int = 900,
    ) -> dict[str, Any]:
        """Collect an already-submitted task without creating a new charge."""
        args = [
            "task",
            "get",
            task_id,
            f"--wait={int(wait_seconds)}s",
            "--output",
            str(Path(output_dir)),
        ]
        return self.run(args, timeout_seconds=int(wait_seconds) + 120)

    def resolve_task(self, identifier: str) -> dict[str, Any]:
        """Read-only reconciliation for a dispatch-unknown ledger entry."""
        return self.run(["task", "resolve", identifier], timeout_seconds=120)
