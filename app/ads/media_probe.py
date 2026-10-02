"""Bounded local media inspection and explicit preview derivatives; originals are never changed."""

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.core import input_rules

MAX_BYTES = 50 * 1024 * 1024
MAX_PIXELS = 64_000_000


class MediaError(ValueError):
    pass


SLOT_KINDS = frozenset({"image/jpeg", "image/png", "image/webp", "video/mp4", "video/quicktime"})


def sniff(content: bytes) -> str:
    """Campaign slot media: the shared content sniff (`app.core.input_rules`, F47 Contract A),
    limited to the kinds a slot accepts (no GIF)."""
    mime = input_rules.sniff(content)
    if mime not in SLOT_KINDS:
        raise MediaError("檔案內容不是支援的 JPEG、PNG、WebP、MP4 或 MOV。")
    return mime


def _run(args, timeout):
    try:
        return subprocess.run(
            args, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, check=True
        ).stdout
    except subprocess.TimeoutExpired:
        raise MediaError("媒體預覽處理逾時，原檔保留，可重試。") from None
    except (subprocess.CalledProcessError, OSError):
        raise MediaError("媒體無法解碼或預覽工具不可用，原檔保留。") from None


def preview(content: bytes) -> dict:
    if not content or len(content) > MAX_BYTES:
        raise MediaError("單檔必須介於 1 byte 與 50 MiB。")
    mime = sniff(content)
    probe, ffmpeg = shutil.which("ffprobe"), shutil.which("ffmpeg")
    if not probe or not ffmpeg:
        raise MediaError("缺少 FFprobe／FFmpeg，原檔已保留，待工具恢復後重試。")
    with tempfile.TemporaryDirectory(prefix="ads-media-") as folder:
        original = Path(folder) / "original.bin"
        original.write_bytes(content)
        raw = _run(
            [
                probe,
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-show_entries",
                "format=duration,format_name:stream=codec_type,codec_name,width,height,duration",
                "-of",
                "json",
                str(original),
            ],
            15,
        )
        try:
            metadata = json.loads(raw)
            stream = next(s for s in metadata.get("streams", []) if s.get("codec_type") == "video")
            width, height = int(stream["width"]), int(stream["height"])
            duration = float(
                metadata.get("format", {}).get("duration") or stream.get("duration") or 0
            )
        except (ValueError, KeyError, StopIteration, TypeError):
            raise MediaError("媒體缺少可驗證的尺寸或時長。") from None
        if width <= 0 or height <= 0 or width * height > MAX_PIXELS or max(width, height) > 16384:
            raise MediaError("媒體尺寸超過預覽處理上限。")
        if mime.startswith("image/") and stream.get("codec_name") not in {"png", "mjpeg", "webp"}:
            raise MediaError("檔案內容與圖片格式不符。")
        is_video = mime.startswith("video/")
        if is_video and (not math.isfinite(duration) or duration <= 0):
            raise MediaError("影片時長無法確認。")
        common = [
            ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-threads",
            "1",
            "-filter_threads",
            "1",
            "-protocol_whitelist",
            "file,pipe",
            "-i",
            str(original),
        ]
        thumb = Path(folder) / "poster.jpg"
        _run(
            common
            + [
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-vf",
                "scale=640:640:force_original_aspect_ratio=decrease",
                "-y",
                str(thumb),
            ],
            20,
        )
        poster = thumb.read_bytes()
        if is_video:
            output = Path(folder) / "preview.mp4"
            _run(
                common
                + [
                    "-t",
                    "15",
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0?",
                    "-vf",
                    "fps=30,scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2",
                    "-c:v",
                    "libx264",
                    "-threads",
                    "1",
                    "-maxrate",
                    "2M",
                    "-bufsize",
                    "4M",
                    "-fs",
                    "8388608",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "28",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "96k",
                    "-movflags",
                    "+faststart",
                    "-y",
                    str(output),
                ],
                60,
            )
            if output.stat().st_size >= 8 * 1024 * 1024:
                raise MediaError("預覽片段超過處理上限，原檔保留。")
            verification = json.loads(
                _run(
                    [
                        probe,
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "json",
                        str(output),
                    ],
                    10,
                )
            )
            encoded_duration = float(verification.get("format", {}).get("duration") or 0)
            if not math.isfinite(encoded_duration) or encoded_duration < min(duration, 15) - 0.5:
                raise MediaError("預覽片段未完整產生，原檔保留，可重試。")
            derivative = output.read_bytes()
        else:
            derivative = poster
        return {
            "mime_type": mime,
            "width": width,
            "height": height,
            "duration": duration if is_video else None,
            "thumbnail": poster,
            "preview": derivative,
            "preview_mime": "video/mp4" if is_video else "image/jpeg",
            "preview_duration": min(duration, 15) if is_video else None,
        }
