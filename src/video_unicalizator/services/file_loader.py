from __future__ import annotations

from pathlib import Path

from video_unicalizator.config import (
    SUPPORTED_AUDIO_EXTENSIONS,
    SUPPORTED_TEXT_EXTENSIONS,
    SUPPORTED_VIDEO_EXTENSIONS,
)
from video_unicalizator.state import MediaLibrary
from video_unicalizator.utils.validation import (
    list_files_by_extensions,
    validate_music_tracks,
    validate_original_videos,
    validate_quotes_files,
)


def load_original_videos(paths: list[str]) -> list[Path]:
    return validate_original_videos([Path(path) for path in paths])


def load_original_videos_from_folder(folder: str) -> list[Path]:
    return validate_original_videos(list_files_by_extensions(Path(folder), SUPPORTED_VIDEO_EXTENSIONS))


def load_music_tracks(paths: list[str]) -> list[Path]:
    return validate_music_tracks([Path(path) for path in paths])


def load_music_tracks_from_folder(folder: str) -> list[Path]:
    return validate_music_tracks(list_files_by_extensions(Path(folder), SUPPORTED_AUDIO_EXTENSIONS))


def load_quote_files(paths: list[str]) -> list[Path]:
    return validate_quotes_files([Path(path) for path in paths])


def load_quote_files_from_folder(folder: str) -> list[Path]:
    return validate_quotes_files(list_files_by_extensions(Path(folder), SUPPORTED_TEXT_EXTENSIONS))


def merge_media_library(
    current: MediaLibrary,
    originals: list[Path] | None = None,
    music: list[Path] | None = None,
    quote_files: list[Path] | None = None,
    quotes: list[str] | None = None,
    quote_files_a: list[Path] | None = None,
    quote_files_b: list[Path] | None = None,
    quotes_a: list[str] | None = None,
    quotes_b: list[str] | None = None,
) -> MediaLibrary:
    legacy_quote_files_a = quote_files if quote_files_a is None and quote_files is not None else quote_files_a
    legacy_quotes_a = quotes if quotes_a is None and quotes is not None else quotes_a
    return MediaLibrary(
        original_videos=originals if originals is not None else list(current.original_videos),
        music_tracks=music if music is not None else list(current.music_tracks),
        quote_files_a=legacy_quote_files_a if legacy_quote_files_a is not None else list(current.quote_files_a),
        quote_files_b=quote_files_b if quote_files_b is not None else list(current.quote_files_b),
        quotes_a=legacy_quotes_a if legacy_quotes_a is not None else list(current.quotes_a),
        quotes_b=quotes_b if quotes_b is not None else list(current.quotes_b),
    )
