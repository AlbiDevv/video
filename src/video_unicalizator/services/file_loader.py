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
) -> MediaLibrary:
    return MediaLibrary(
        original_videos=originals if originals is not None else list(current.original_videos),
        music_tracks=music if music is not None else list(current.music_tracks),
        quote_files=quote_files if quote_files is not None else list(current.quote_files),
        quotes=quotes if quotes is not None else list(current.quotes),
    )
