"""Regression tests for provider scoring tokenization."""

from __future__ import annotations

from lib.scoring import _tokenize_text, score_provider
from tools.base_tool import ToolStatus


class _FakeVideoTool:
    name = "fake-video"

    def get_info(self) -> dict[str, object]:
        return {
            "name": "fake-video",
            "provider": "fake",
            "best_for": ["cinematic video"],
            "supports": {
                "native_audio": True,
                "multi_shot": True,
                "camera_direction": True,
                "lip_sync": True,
                "cinematic_quality": True,
            },
            "stability": "production",
            "runtime": "api",
        }

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE

    def estimate_cost(self, inputs: dict[str, object]) -> float:
        return 0.0


class _UnknownNonUsdCostTool(_FakeVideoTool):
    def get_info(self) -> dict[str, object]:
        info = super().get_info()
        info["supports"] = {
            **info["supports"],
            "cost_currency": "provider_points",
            "usd_cost_known": False,
        }
        return info


def test_tokenize_text_strips_trailing_punctuation() -> None:
    assert _tokenize_text("cinematic.") == ["cinematic"]
    assert _tokenize_text("v1.5.") == ["v1.5"]
    assert _tokenize_text("gpt-4.1") == ["gpt-4.1"]


def test_cinematic_bonus_ignores_adjacent_punctuation() -> None:
    tool = _FakeVideoTool()
    plain = score_provider(tool, {"asset_type": "video", "intent": "make it cinematic and fast"})
    punctuated = score_provider(tool, {"asset_type": "video", "intent": "make it cinematic, and fast"})

    assert punctuated.task_fit == plain.task_fit
    assert punctuated.output_quality == plain.output_quality


def test_unknown_non_usd_price_is_neutral_not_scored_as_free() -> None:
    score = score_provider(
        _UnknownNonUsdCostTool(),
        {"asset_type": "video", "intent": "cinematic video"},
    )

    assert score.cost_efficiency == 0.5
