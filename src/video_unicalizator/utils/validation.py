from __future__ import annotations

from pathlib import Path

from video_unicalizator.config import (
    MAX_ORIGINALS,
    MAX_VARIATIONS,
    MIN_VARIATIONS,
    SUPPORTED_AUDIO_EXTENSIONS,
    SUPPORTED_TEXT_EXTENSIONS,
    SUPPORTED_VIDEO_EXTENSIONS,
    TARGET_HEIGHT,
    TARGET_WIDTH,
)


class ValidationError(ValueError):
    """Ошибка пользовательских данных."""


def list_files_by_extensions(folder: Path, extensions: set[str]) -> list[Path]:
    if not folder.exists() or not folder.is_dir():
        raise ValidationError(f"Папка не найдена: {folder}")
    files = sorted(path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in extensions)
    if not files:
        suffixes = ", ".join(sorted(extensions))
        raise ValidationError(f"В папке {folder} не найдено файлов с расширениями: {suffixes}")
    return files


def ensure_existing_files(paths: list[Path]) -> list[Path]:
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise ValidationError(f"Не найдены файлы: {', '.join(missing)}")
    return paths


def validate_original_videos(paths: list[Path]) -> list[Path]:
    if not paths:
        raise ValidationError("Выберите хотя бы один mp4-файл.")
    if len(paths) > MAX_ORIGINALS:
        raise ValidationError(f"Можно загрузить не более {MAX_ORIGINALS} оригиналов.")
    ensure_existing_files(paths)
    invalid = [path.name for path in paths if path.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS]
    if invalid:
        raise ValidationError(f"Поддерживаются только mp4-файлы: {', '.join(invalid)}")
    return paths


def validate_music_tracks(paths: list[Path]) -> list[Path]:
    ensure_existing_files(paths)
    invalid = [path.name for path in paths if path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS]
    if invalid:
        raise ValidationError(f"Поддерживаются только mp3-файлы: {', '.join(invalid)}")
    return paths


def validate_quotes_file(path: Path) -> Path:
    ensure_existing_files([path])
    if path.suffix.lower() not in SUPPORTED_TEXT_EXTENSIONS:
        raise ValidationError("Файл с цитатами должен иметь расширение .txt")
    return path


def validate_quotes_files(paths: list[Path]) -> list[Path]:
    if not paths:
        raise ValidationError("Выберите хотя бы один txt-файл с цитатами.")
    return [validate_quotes_file(path) for path in paths]


def validate_variation_count(value: int) -> int:
    if value < MIN_VARIATIONS or value > MAX_VARIATIONS:
        raise ValidationError(
            f"Количество вариаций должно быть в диапазоне {MIN_VARIATIONS}-{MAX_VARIATIONS}."
        )
    return value


def is_target_vertical_resolution(width: int, height: int) -> bool:
    return width == TARGET_WIDTH and height == TARGET_HEIGHT
