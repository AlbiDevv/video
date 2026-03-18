from __future__ import annotations

from pathlib import Path

from video_unicalizator.utils.validation import ValidationError, validate_quotes_file, validate_quotes_files


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _split_quote_blocks(raw_text: str) -> list[str]:
    blocks: list[str] = []
    current_lines: list[str] = []

    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    for line in normalized.split("\n"):
        if line.strip():
            current_lines.append(line.rstrip())
            continue
        if current_lines:
            blocks.append("\n".join(current_lines).strip())
            current_lines.clear()

    if current_lines:
        blocks.append("\n".join(current_lines).strip())
    return [block for block in blocks if block]


def load_quotes(path: Path) -> list[str]:
    validate_quotes_file(path)
    quotes = _split_quote_blocks(_read_text(path))
    if not quotes:
        raise ValidationError("Файл с цитатами пуст.")
    return quotes


def load_quotes_from_files(paths: list[Path]) -> list[str]:
    validate_quotes_files(paths)
    quotes: list[str] = []
    for path in paths:
        quotes.extend(load_quotes(path))
    if not quotes:
        raise ValidationError("Не удалось загрузить ни одной цитаты.")
    return quotes
