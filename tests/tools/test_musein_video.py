"""Contract tests for the Musein CLI video provider.

The real CLI is never invoked here. Musein can bill from a subprocess, which
the session-wide socket guard cannot intercept, so every transport is faked.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools.base_tool import ToolStatus
from tools.musein_cli import (
    MuseinCli,
    MuseinCliError,
    find_musein_executable,
)
from tools.tool_registry import ToolRegistry
from tools.video.musein_video import MuseinVideo
from tools.video.pexels_video import PexelsVideo
from tools.video.video_selector import VideoSelector


class _FakeMuseinCli:
    def __init__(
        self,
        *,
        quote=None,
        result=None,
        collect_result=None,
        resolve_result=None,
        quote_error=None,
        generate_error=None,
        collect_error=None,
        resolve_error=None,
        media=b"video",
    ):
        self.quote = quote or {
            "schema_version": "musein.cli.v1",
            "status": "estimated",
            "model_id": "model-a",
            "usage": {
                "points_estimated": 16,
                "balance_before": 100,
                "balance_remaining": 100,
            },
        }
        self.result = result or {
            "schema_version": "musein.cli.v1",
            "status": "succeeded",
            "model_id": "model-a",
            "task_id": "task-1",
            "usage": {
                "points_estimated": 16,
                "points_consumed": 15,
                "balance_remaining": 85,
            },
        }
        self.collect_result = collect_result or self.result
        self.resolve_result = resolve_result or {
            "schema_version": "musein.cli.v1",
            "status": "succeeded",
            "findings": [
                {
                    "client_request_id": "request-1",
                    "task_id": "task-1",
                    "server_state": "succeeded",
                    "consumed_points": 15,
                }
            ],
        }
        self.quote_error = quote_error
        self.generate_error = generate_error
        self.collect_error = collect_error
        self.resolve_error = resolve_error
        self.media = media
        self.quote_calls = []
        self.generate_calls = []
        self.collect_calls = []
        self.resolve_calls = []

    def quote_generation(self, **kwargs):
        self.quote_calls.append(kwargs)
        if self.quote_error:
            raise self.quote_error
        return self.quote

    def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        if self.generate_error:
            raise self.generate_error
        output_dir = Path(kwargs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "generated.mp4").write_bytes(self.media)
        return self.result

    def collect_task(self, **kwargs):
        self.collect_calls.append(kwargs)
        if self.collect_error:
            raise self.collect_error
        output_dir = Path(kwargs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "collected.mp4").write_bytes(self.media)
        return self.collect_result

    def resolve_task(self, identifier):
        self.resolve_calls.append(identifier)
        if self.resolve_error:
            raise self.resolve_error
        return self.resolve_result


def _inputs(tmp_path: Path) -> dict:
    return {
        "prompt": "A camera circles the subject",
        "model": "model-a",
        "operation": "text_to_video",
        "duration": "6",
        "aspect_ratio": "16:9",
        "approved_points": 16,
        "output_path": str(tmp_path / "shot-01.mp4"),
    }


def _fake_executable(tmp_path: Path) -> Path:
    executable = tmp_path / "musein.exe"
    executable.write_bytes(b"binary")
    return executable


def test_find_executable_honors_explicit_path(monkeypatch, tmp_path):
    exe = tmp_path / "musein.exe"
    exe.write_bytes(b"binary")
    monkeypatch.setenv("MUSEIN_CLI_PATH", str(exe))
    assert find_musein_executable() == exe.resolve()


def test_cli_command_keeps_prompt_as_one_argument_and_never_contains_key(tmp_path):
    cli = MuseinCli(executable=_fake_executable(tmp_path), endpoint="ai")
    prompt = "night city; echo $env:MUSEIN_KEY"
    args = cli.build_generation_args(
        generation_type="video",
        model="model-a",
        prompt=prompt,
        output_dir=tmp_path,
        wait_seconds=900,
        dry_run=False,
        params={"duration": 6, "generate_audio": True},
    )

    assert prompt in args
    assert args.count(prompt) == 1
    assert "--strict-model" in args
    assert "--wait=900s" in args
    assert all("musein_sk_" not in value for value in args)


def test_cli_model_fallback_requires_an_explicit_opt_in(tmp_path):
    cli = MuseinCli(executable=_fake_executable(tmp_path))
    common = {
        "generation_type": "video",
        "model": "model-a",
        "prompt": "test",
        "output_dir": tmp_path,
        "wait_seconds": 900,
        "dry_run": True,
        "params": {},
    }

    assert "--strict-model" in cli.build_generation_args(**common)
    assert "--strict-model" not in cli.build_generation_args(**common, strict_model=False)


def test_cli_dry_run_command_prices_without_submit(tmp_path):
    cli = MuseinCli(executable=_fake_executable(tmp_path))
    args = cli.build_generation_args(
        generation_type="video",
        model="model-a",
        prompt="test",
        output_dir=tmp_path,
        wait_seconds=900,
        dry_run=True,
        params={},
    )
    assert "--dry-run" in args
    assert not any(value.startswith("--wait=") for value in args)


def test_cli_exit_9_is_explicitly_not_retry_safe(monkeypatch, tmp_path):
    cli = MuseinCli(executable=_fake_executable(tmp_path))
    proc = subprocess.CompletedProcess(
        [str(tmp_path / "musein.exe")],
        9,
        stdout=json.dumps(
            {
                "schema_version": "musein.cli.v1",
                "status": "dispatch_unknown",
                "error": {
                    "cli_code": "dispatch_unknown",
                    "message": "submission outcome is unknown",
                    "next_step": (
                        "DO NOT retry; run `musein task resolve request-unknown` first"
                    ),
                },
            }
        ),
        stderr="",
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: proc)

    with pytest.raises(MuseinCliError) as raised:
        cli.run(["task", "resolve", "task-unknown"])

    assert raised.value.returncode == 9
    assert raised.value.retry_safe is False
    assert raised.value.cli_code == "dispatch_unknown"
    assert raised.value.next_step.endswith("request-unknown` first")
    assert raised.value.resolution_id == "request-unknown"


def test_cli_errors_redact_long_lived_keys(monkeypatch, tmp_path):
    cli = MuseinCli(executable=_fake_executable(tmp_path))
    proc = subprocess.CompletedProcess(
        [str(tmp_path / "musein.exe")],
        2,
        stdout="",
        stderr="bad key musein_sk_ai_supersecretvalue",
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: proc)

    with pytest.raises(MuseinCliError) as raised:
        cli.run(["whoami"])

    assert "supersecretvalue" not in str(raised.value)
    assert "[REDACTED]" in str(raised.value)


def test_cli_fails_closed_on_a_breaking_schema_version(monkeypatch, tmp_path):
    cli = MuseinCli(executable=_fake_executable(tmp_path))
    proc = subprocess.CompletedProcess(
        [str(tmp_path / "musein.exe")],
        0,
        stdout=json.dumps({"schema_version": "musein.cli.v2", "status": "succeeded"}),
        stderr="",
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: proc)

    with pytest.raises(MuseinCliError, match="Unsupported Musein CLI schema_version"):
        cli.run(["whoami"])


def test_provider_is_discoverable():
    registry = ToolRegistry()
    registry.discover("tools")
    tool = registry.get("musein_video")
    assert isinstance(tool, MuseinVideo)
    assert tool.provider == "musein"
    assert tool.capability == "video_generation"


def test_selector_allow_list_hard_locks_musein(monkeypatch):
    selector = VideoSelector()
    musein = MuseinVideo()
    other = PexelsVideo()
    monkeypatch.setattr(musein, "get_status", lambda: ToolStatus.AVAILABLE)
    monkeypatch.setattr(other, "get_status", lambda: ToolStatus.AVAILABLE)
    inputs = {
        "prompt": "cinematic portrait",
        "operation": "text_to_video",
        "preferred_provider": "musein",
        "allowed_providers": ["musein"],
    }

    selected, _ = selector._select_best_tool(
        inputs,
        [other, musein],
        selector._prepare_task_context(inputs),
    )

    assert selected is musein


def test_status_requires_cli_and_credentials(monkeypatch, tmp_path):
    exe = tmp_path / "musein.exe"
    exe.write_bytes(b"binary")
    credentials = tmp_path / "credentials"
    credentials.write_text("{}", encoding="utf-8")
    tool = MuseinVideo()
    monkeypatch.setattr(tool, "_resolve_executable", lambda: exe)
    monkeypatch.setattr(tool, "_credentials_path", lambda: credentials)
    assert tool.get_status() == ToolStatus.AVAILABLE

    credentials.unlink()
    assert tool.get_status() == ToolStatus.UNAVAILABLE

    monkeypatch.setenv("MUSEIN_TOKEN", "ephemeral-token")
    assert tool.get_status() == ToolStatus.AVAILABLE


def test_dry_run_returns_live_point_quote_without_pretending_usd(monkeypatch, tmp_path):
    fake = _FakeMuseinCli()
    tool = MuseinVideo()
    monkeypatch.setattr(tool, "_client", lambda: fake)
    monkeypatch.delenv("MUSEIN_USD_PER_POINT", raising=False)

    result = tool.dry_run(_inputs(tmp_path))

    assert result["status"] == "estimated"
    assert result["points_estimated"] == 16
    assert result["estimated_cost_usd"] is None
    assert result["cost_currency"] == "musein_points"
    assert result["paid_submission"] is False
    assert result["would_execute"] is False
    assert len(fake.quote_calls) == 1


def test_dry_run_converts_points_only_with_explicit_rate(monkeypatch, tmp_path):
    fake = _FakeMuseinCli()
    tool = MuseinVideo()
    monkeypatch.setattr(tool, "_client", lambda: fake)
    monkeypatch.setenv("MUSEIN_USD_PER_POINT", "0.01")

    result = tool.dry_run(_inputs(tmp_path))

    assert result["estimated_cost_usd"] == pytest.approx(0.16)
    assert result["usd_conversion_source"] == "MUSEIN_USD_PER_POINT"


def test_execute_writes_exact_output_and_reports_points(monkeypatch, tmp_path):
    fake = _FakeMuseinCli()
    tool = MuseinVideo()
    monkeypatch.setattr(tool, "_client", lambda: fake)
    monkeypatch.setattr(tool, "_validate_video", lambda path: {"file_size_bytes": path.stat().st_size})
    monkeypatch.setenv("MUSEIN_USD_PER_POINT", "0.01")

    result = tool.execute(_inputs(tmp_path))

    output = tmp_path / "shot-01.mp4"
    assert result.success is True
    assert result.artifacts == [str(output)]
    assert output.read_bytes() == b"video"
    assert result.data["provider"] == "musein"
    assert result.data["task_id"] == "task-1"
    assert result.data["points_estimated"] == 16
    assert result.data["points_consumed"] == 15
    assert result.data["balance_remaining"] == 85
    assert result.data["cost_provenance"] == "actual_from_usage"
    assert result.data["estimated_cost_usd"] == pytest.approx(0.16)
    assert result.data["actual_cost_usd"] == pytest.approx(0.15)
    assert result.cost_usd == pytest.approx(0.15)
    assert len(fake.generate_calls) == 1


def test_execute_reports_actual_model_and_server_overrides(monkeypatch, tmp_path):
    fake = _FakeMuseinCli(
        quote={
            "schema_version": "musein.cli.v1",
            "status": "estimated",
            "model_id": "model-b",
            "usage": {"points_estimated": 16},
        },
        result={
            "schema_version": "musein.cli.v1",
            "status": "succeeded",
            "model_id": "model-b",
            "task_id": "task-1",
            "overrides": {"resolution": {"from": "1080p", "to": "720p"}},
            "usage": {"points_estimated": 16, "points_consumed": 17},
        }
    )
    tool = MuseinVideo()
    monkeypatch.setattr(tool, "_client", lambda: fake)
    monkeypatch.setattr(tool, "_validate_video", lambda path: {"file_size_bytes": path.stat().st_size})

    result = tool.execute({
        **_inputs(tmp_path),
        "allow_model_fallback": True,
        "approved_model": "model-b",
    })

    assert result.success is True
    assert result.data["requested_model"] == "model-a"
    assert result.data["model"] == "model-b"
    assert result.data["overrides"]["resolution"]["to"] == "720p"
    assert fake.quote_calls[0]["strict_model"] is False
    assert fake.generate_calls[0]["strict_model"] is False


def test_execute_requotes_and_blocks_a_price_increase(monkeypatch, tmp_path):
    fake = _FakeMuseinCli(quote={
        "schema_version": "musein.cli.v1",
        "status": "estimated",
        "model_id": "model-a",
        "usage": {"points_estimated": 17},
    })
    tool = MuseinVideo()
    monkeypatch.setattr(tool, "_client", lambda: fake)

    result = tool.execute(_inputs(tmp_path))

    assert result.success is False
    assert "above the approved maximum" in result.error
    assert fake.generate_calls == []


def test_invalid_usd_conversion_fails_before_any_remote_call(monkeypatch, tmp_path):
    fake = _FakeMuseinCli()
    tool = MuseinVideo()
    monkeypatch.setattr(tool, "_client", lambda: fake)
    monkeypatch.setenv("MUSEIN_USD_PER_POINT", "-1")

    result = tool.execute(_inputs(tmp_path))

    assert result.success is False
    assert "must be a finite number greater than 0" in result.error
    assert fake.quote_calls == []
    assert fake.generate_calls == []


def test_execute_refuses_to_overwrite_existing_output(monkeypatch, tmp_path):
    output = tmp_path / "shot-01.mp4"
    output.write_bytes(b"keep-me")
    fake = _FakeMuseinCli()
    tool = MuseinVideo()
    monkeypatch.setattr(tool, "_client", lambda: fake)

    result = tool.execute(_inputs(tmp_path))

    assert result.success is False
    assert "Refusing to overwrite" in result.error
    assert output.read_bytes() == b"keep-me"
    assert fake.generate_calls == []


def test_execute_never_retries_dispatch_unknown(monkeypatch, tmp_path):
    error = MuseinCliError(
        "submission outcome is unknown",
        returncode=9,
        payload={
            "task_id": "task-unknown",
            "status": "dispatch_unknown",
            "error": {
                "cli_code": "dispatch_unknown",
                "message": "submission outcome is unknown",
                "next_step": "run `musein task resolve request-unknown`",
            },
        },
    )
    fake = _FakeMuseinCli(generate_error=error)
    tool = MuseinVideo()
    monkeypatch.setattr(tool, "_client", lambda: fake)

    result = tool.execute(_inputs(tmp_path))

    assert result.success is False
    assert result.data["task_id"] == "task-unknown"
    assert result.data["retry_safe"] is False
    assert result.data["requires_manual_resolution"] is True
    assert result.data["resolution_id"] == "request-unknown"
    assert len(fake.generate_calls) == 1


def test_execute_timeout_requires_collection_not_resubmission(monkeypatch, tmp_path):
    error = MuseinCliError(
        "wait elapsed",
        returncode=6,
        payload={
            "schema_version": "musein.cli.v1",
            "status": "failed",
            "task_id": "task-slow",
            "error": {
                "cli_code": "timeout",
                "message": "wait elapsed",
                "next_step": "run `musein task get task-slow --wait`",
            },
        },
    )
    fake = _FakeMuseinCli(generate_error=error)
    tool = MuseinVideo()
    monkeypatch.setattr(tool, "_client", lambda: fake)

    result = tool.execute(_inputs(tmp_path))

    assert result.success is False
    assert result.data["task_id"] == "task-slow"
    assert result.data["requires_collection"] is True
    assert result.data["requires_manual_resolution"] is False
    assert len(fake.generate_calls) == 1


def test_collect_recovers_existing_task_without_pricing_or_resubmitting(monkeypatch, tmp_path):
    fake = _FakeMuseinCli()
    tool = MuseinVideo()
    monkeypatch.setattr(tool, "_client", lambda: fake)
    monkeypatch.setattr(tool, "_validate_video", lambda path: {"file_size_bytes": path.stat().st_size})

    result = tool.execute({
        "task_action": "collect",
        "task_id": "task-1",
        "output_path": str(tmp_path / "recovered.mp4"),
        "timeout_seconds": 300,
    })

    assert result.success is True
    assert result.data["task_action"] == "collect"
    assert result.data["points_consumed"] == 15
    assert fake.quote_calls == []
    assert fake.generate_calls == []
    assert fake.collect_calls[0]["task_id"] == "task-1"
    assert (tmp_path / "recovered.mp4").exists()


def test_resolve_is_read_only_and_returns_cli_findings(monkeypatch):
    fake = _FakeMuseinCli()
    tool = MuseinVideo()
    monkeypatch.setattr(tool, "_client", lambda: fake)

    result = tool.execute({
        "task_action": "resolve",
        "client_request_id": "request-1",
    })

    assert result.success is True
    assert result.data["task_action"] == "resolve"
    assert result.data["findings"][0]["task_id"] == "task-1"
    assert result.artifacts == []
    assert fake.resolve_calls == ["request-1"]
    assert fake.quote_calls == []
    assert fake.generate_calls == []


def test_execute_rejects_invalid_download_before_publish(monkeypatch, tmp_path):
    fake = _FakeMuseinCli(media=b"not-a-video")
    tool = MuseinVideo()
    monkeypatch.setattr(tool, "_client", lambda: fake)

    def reject(_path):
        raise ValueError("downloaded artifact has no video stream")

    monkeypatch.setattr(tool, "_validate_video", reject)
    result = tool.execute(_inputs(tmp_path))

    assert result.success is False
    assert "no video stream" in result.error
    assert not (tmp_path / "shot-01.mp4").exists()
