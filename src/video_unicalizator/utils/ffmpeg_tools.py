from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(slots=True)
class MediaProbeInfo:
    width: int
    height: int
    duration: float
    fps: float
    has_audio: bool


@dataclass(slots=True)
class ExportMetadataProbeInfo:
    format_name: str
    duration: float
    video_codec: str
    audio_codec: str
    creation_time: str
    format_tags: dict[str, str]
    chapter_count: int


def no_window_creationflags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _binary_candidates(binary_name: str) -> list[Path]:
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    search_roots = [
        local_app_data / "Microsoft" / "WinGet" / "Packages",
        local_app_data / "Microsoft" / "WinGet" / "Links",
        Path(r"C:\ffmpeg"),
        Path(r"C:\Program Files\ffmpeg"),
        Path(r"C:\Program Files (x86)\ffmpeg"),
    ]

    candidates: list[Path] = []
    for root in search_roots:
        if not root.exists():
            continue
        if root.is_file() and root.name.lower() == binary_name.lower():
            candidates.append(root)
            continue
        candidates.extend(root.rglob(binary_name))
    return candidates


@lru_cache(maxsize=4)
def resolve_binary(binary_name: str) -> str | None:
    direct = shutil.which(binary_name)
    if direct:
        return direct

    for candidate in _binary_candidates(binary_name):
        if candidate.is_file():
            return str(candidate)
    return None


def ensure_ffmpeg_environment() -> tuple[str | None, str | None]:
    ffmpeg_path = resolve_binary("ffmpeg.exe") or resolve_binary("ffmpeg")
    ffprobe_path = resolve_binary("ffprobe.exe") or resolve_binary("ffprobe")

    for binary_path in (ffmpeg_path, ffprobe_path):
        if not binary_path:
            continue
        binary_dir = str(Path(binary_path).parent)
        path_entries = os.environ.get("PATH", "").split(os.pathsep)
        if binary_dir not in path_entries:
            os.environ["PATH"] = binary_dir + os.pathsep + os.environ.get("PATH", "")

    if ffmpeg_path:
        os.environ.setdefault("IMAGEIO_FFMPEG_EXE", ffmpeg_path)
    return ffmpeg_path, ffprobe_path


def ffmpeg_available() -> bool:
    ffmpeg_path, ffprobe_path = ensure_ffmpeg_environment()
    return ffmpeg_path is not None and ffprobe_path is not None


def ffmpeg_status_message() -> str:
    ffmpeg_path, ffprobe_path = ensure_ffmpeg_environment()
    if ffmpeg_path and ffprobe_path:
        return f"FFmpeg найден: {ffmpeg_path}"
    return "FFmpeg не найден. Установите ffmpeg и ffprobe, затем добавьте их в PATH."


def _parse_fps(value: str) -> float:
    if not value or value == "0/0":
        return 0.0
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        denominator_value = float(denominator or 1.0)
        if denominator_value == 0:
            return 0.0
        return float(numerator) / denominator_value
    return float(value)


def probe_media(video_path: Path) -> MediaProbeInfo:
    _, ffprobe_path = ensure_ffmpeg_environment()
    if not ffprobe_path:
        raise RuntimeError("ffprobe не найден.")

    resolved = video_path.resolve()
    stat = resolved.stat()
    return _probe_media_cached(str(resolved), stat.st_mtime_ns, stat.st_size, ffprobe_path)


def probe_export_metadata(video_path: Path) -> ExportMetadataProbeInfo:
    _, ffprobe_path = ensure_ffmpeg_environment()
    if not ffprobe_path:
        raise RuntimeError("ffprobe не найден.")

    resolved = video_path.resolve()
    stat = resolved.stat()
    return _probe_export_metadata_cached(str(resolved), stat.st_mtime_ns, stat.st_size, ffprobe_path)


@lru_cache(maxsize=256)
def _probe_media_cached(video_path: str, _mtime_ns: int, _size: int, ffprobe_path: str) -> MediaProbeInfo:
    command = [
        ffprobe_path,
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        video_path,
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True,
        creationflags=no_window_creationflags(),
    )
    payload = json.loads(completed.stdout or "{}")

    streams = payload.get("streams", [])
    format_payload = payload.get("format", {})
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    fps = _parse_fps(str(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "0/0"))
    duration = float(video_stream.get("duration") or format_payload.get("duration") or 0.0)

    return MediaProbeInfo(
        width=width,
        height=height,
        duration=max(0.0, duration),
        fps=fps,
        has_audio=audio_stream is not None,
    )


@lru_cache(maxsize=256)
def _probe_export_metadata_cached(
    video_path: str,
    _mtime_ns: int,
    _size: int,
    ffprobe_path: str,
) -> ExportMetadataProbeInfo:
    command = [
        ffprobe_path,
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-show_chapters",
        "-of",
        "json",
        video_path,
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True,
        creationflags=no_window_creationflags(),
    )
    payload = json.loads(completed.stdout or "{}")

    streams = payload.get("streams", [])
    format_payload = payload.get("format", {})
    chapters = payload.get("chapters", [])
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    format_tags = {
        str(key): str(value)
        for key, value in (format_payload.get("tags") or {}).items()
        if value is not None
    }
    creation_time = str(format_tags.get("creation_time") or "")
    if not creation_time:
        stream_tags = video_stream.get("tags") or {}
        creation_time = str(stream_tags.get("creation_time") or "")

    return ExportMetadataProbeInfo(
        format_name=str(format_payload.get("format_name") or ""),
        duration=max(0.0, float(format_payload.get("duration") or 0.0)),
        video_codec=str(video_stream.get("codec_name") or ""),
        audio_codec=str(audio_stream.get("codec_name") or ""),
        creation_time=creation_time,
        format_tags=format_tags,
        chapter_count=len(chapters),
    )


def parse_ffmpeg_progress_time(progress_fields: dict[str, str]) -> float:
    value = progress_fields.get("out_time_ms") or progress_fields.get("out_time_us")
    if value and value.upper() != "N/A":
        try:
            numeric = float(value)
        except ValueError:
            numeric = 0.0
        return numeric / 1_000_000.0

    out_time = progress_fields.get("out_time")
    if not out_time or out_time.upper() == "N/A":
        return 0.0

    parts = out_time.split(":")
    if len(parts) != 3:
        return 0.0
    hours, minutes, seconds = parts
    return float(hours) * 3600.0 + float(minutes) * 60.0 + float(seconds)
