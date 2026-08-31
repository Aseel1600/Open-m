"""Tests for the YouTube uploader publisher tool.

These tests verify the exact YouTube API contract without making live network
calls, plus retry handling for transient upload failures and thumbnail updates.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

from tools.base_tool import ToolTier
from tools.publishers.youtube_uploader import YouTubeUploader

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class FakeProgress:
    def __init__(self, value):
        self._value = value

    def progress(self):
        return self._value


class FakeHttpError(Exception):
    def __init__(self, status):
        self.resp = SimpleNamespace(status=status)


class FakeInsertRequest:
    def __init__(self, seen, responses):
        self.seen = seen
        self._responses = responses
        self.calls = 0

    def next_chunk(self):
        self.calls += 1
        if self.calls <= len(self._responses):
            item = self._responses[self.calls - 1]
            if isinstance(item, Exception):
                raise item
            return item
        return (FakeProgress(1.0), {"id": "abc123"})


class FakeVideos:
    def __init__(self, seen, responses):
        self.seen = seen
        self.responses = responses

    def insert(self, **kwargs):
        self.seen.update(kwargs)
        return FakeInsertRequest(self.seen, self.responses)


class FakeThumbnailRequest:
    def __init__(self, seen):
        self.seen = seen

    def execute(self):
        self.seen["executed"] = True
        return {"success": True}


class FakeThumbnailService:
    def __init__(self, seen):
        self.seen = seen

    def set(self, **kwargs):
        self.seen.update(kwargs)
        return FakeThumbnailRequest(self.seen)


def test_contract_metadata():
    tool = YouTubeUploader()
    info = tool.get_info()
    assert info["name"] == "youtube_uploader"
    assert info["capability"] == "publish"
    assert info["tier"] == ToolTier.PUBLISH.value
    assert info["provider"] == "youtube"
    assert info["supports"]["uploads"] is True
    assert info["resource_profile"]["network_required"] is True


def test_upload_body_uses_nested_snippet_and_status(tmp_path, monkeypatch):
    video = tmp_path / "final.mp4"
    video.write_bytes(b"fake-video")
    seen = {}
    responses = [(FakeProgress(1.0), {"id": "abc123"})]
    fake_youtube = SimpleNamespace(videos=lambda: FakeVideos(seen, responses))

    tool = YouTubeUploader()
    body = {
        "snippet": {"title": "Demo title", "description": "desc", "tags": ["demo"]},
        "status": {"privacyStatus": "private"},
    }

    response = tool._upload_video(fake_youtube, body, str(video))

    assert response == {"id": "abc123"}
    assert seen["part"] == "snippet,status"
    assert seen["body"] == body
    assert seen["media_body"] is not None


def test_retries_transient_http_errors_then_succeeds(tmp_path, monkeypatch):
    seen = {}
    responses = [
        FakeHttpError(500),
        FakeHttpError(503),
        (FakeProgress(1.0), {"id": "retry-ok"}),
    ]
    fake_youtube = SimpleNamespace(videos=lambda: FakeVideos(seen, responses))
    media_path = tmp_path / "video.mp4"
    media_path.write_bytes(b"video")

    tool = YouTubeUploader()
    monkeypatch.setattr(tool, "retry_policy", SimpleNamespace(max_retries=5, backoff_seconds=0.0))
    response = tool._upload_video(fake_youtube, {"snippet": {}, "status": {}}, str(media_path))

    assert response == {"id": "retry-ok"}


def test_retry_exhaustion_raises_runtime_error(tmp_path, monkeypatch):
    seen = {}
    responses = [
        FakeHttpError(500),
        FakeHttpError(500),
        FakeHttpError(500),
        FakeHttpError(500),
        FakeHttpError(500),
        FakeHttpError(500),
    ]
    fake_youtube = SimpleNamespace(videos=lambda: FakeVideos(seen, responses))
    media_path = tmp_path / "video.mp4"
    media_path.write_bytes(b"video")

    tool = YouTubeUploader()
    monkeypatch.setattr(tool, "retry_policy", SimpleNamespace(max_retries=5, backoff_seconds=0.0))

    try:
        tool._upload_video(fake_youtube, {"snippet": {}, "status": {}}, str(media_path))
        raise AssertionError("Expected RuntimeError")
    except RuntimeError as exc:
        assert "Upload failed after" in str(exc)


def test_thumbnail_set_calls_api(monkeypatch):
    seen = {}
    fake_youtube = SimpleNamespace(thumbnails=lambda: FakeThumbnailService(seen))

    tool = YouTubeUploader()
    monkeypatch.setattr(tool, "_import_google_clients", lambda: {"MediaFileUpload": lambda *args, **kwargs: object(),})

    assert tool._set_thumbnail(fake_youtube, "abc123", "thumb.jpg") is True
    assert seen["videoId"] == "abc123"
    assert seen["executed"] is True
