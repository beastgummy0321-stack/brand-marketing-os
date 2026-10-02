"""Real local decoding fixtures; no platform calls or generated media service."""

import json
import shutil
import subprocess
from unittest.mock import patch

import pytest

from app.ads import media_probe as media

# A 1x1 PNG with a valid IHDR: uploads are checked by content and header (F47 Contract A).
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
       b"\x08\x00\x00\x00\x00:~\x9bU\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
       b"H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82")


@pytest.mark.parametrize(
    "extension,codec,mime",
    [
        ("png", "png", "image/png"),
        ("jpg", "mjpeg", "image/jpeg"),
        ("webp", "libwebp", "image/webp"),
        ("mp4", "libx264", "video/mp4"),
        ("mov", "libx264", "video/quicktime"),
    ],
)
def test_real_preview_and_original_bytes(tmp_path, extension, codec, mime):
    tool = shutil.which("ffmpeg")
    assert tool, "FFmpeg is required to verify real preview decoding"
    path = tmp_path / ("fixture." + extension)
    args = [
        tool,
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=320x240:r=10",
        "-frames:v",
        "3" if mime.startswith("video") else "1",
        "-c:v",
        codec,
        "-threads",
        "1",
        "-y",
        str(path),
    ]
    subprocess.run(args, check=True, timeout=20, capture_output=True)
    original = path.read_bytes()
    result = media.preview(original)
    assert result["mime_type"] == mime
    assert (result["width"], result["height"]) == (320, 240)
    assert result["thumbnail"].startswith(b"\xff\xd8\xff")
    assert path.read_bytes() == original
    if mime.startswith("video"):
        assert result["preview_mime"] == "video/mp4"
        assert result["preview"][4:8] == b"ftyp"
        assert 0 < result["preview_duration"] <= 15


def test_corrupt_magic_missing_tools_and_timeout():
    with pytest.raises(media.MediaError):
        media.preview(b"\x89PNG\r\n\x1a\ncorrupt")  # header does not decode
    with pytest.raises(media.MediaError):
        media.sniff(b"pretend.jpg")
    with (
        patch.object(media.shutil, "which", return_value=None),
        pytest.raises(media.MediaError, match="FFprobe"),
    ):
        media.preview(PNG)
    with (
        patch.object(media.subprocess, "run", side_effect=subprocess.TimeoutExpired("ffmpeg", 1)),
        pytest.raises(media.MediaError, match="逾時"),
    ):
        media._run(["ffmpeg"], 1)


@pytest.mark.parametrize("duration,width", [("NaN", 320), ("Infinity", 320), ("1", 100000)])
def test_unbounded_metadata_rejected(duration, width):
    raw = json.dumps(
        {
            "streams": [{"codec_type": "video", "width": width, "height": 240}],
            "format": {"duration": duration},
        }
    ).encode()
    with patch.object(media, "_run", return_value=raw), pytest.raises(media.MediaError):
        media.preview(b"\x00\x00\x00\x18ftypisom")


def test_sniff_delegates_to_the_shared_rule_and_keeps_slot_kinds():
    """F47 Contract A: one content sniff (`app.core.input_rules.sniff`); a slot still accepts
    only JPEG / PNG / WebP / MP4 / MOV (a GIF is a library-asset kind, not a slot kind)."""
    assert media.sniff(PNG) == "image/png"
    assert media.sniff(b"\x00\x00\x00\x18ftypqt  ") == "video/quicktime"
    with pytest.raises(media.MediaError, match="JPEG、PNG、WebP、MP4 或 MOV"):
        media.sniff(b"GIF89a....")
    with patch.object(media.input_rules, "sniff", return_value="image/webp") as shared:
        assert media.sniff(b"anything") == "image/webp"
    shared.assert_called_once_with(b"anything")
