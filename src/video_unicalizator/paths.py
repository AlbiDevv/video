from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = PROJECT_ROOT / "assets"
EMOJI_ASSETS_DIR = ASSETS_DIR / "emoji"
TWEMOJI_DIR = EMOJI_ASSETS_DIR / "twemoji" / "72x72"
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"
SRC_DIR = PROJECT_ROOT / "src"

ORIGINALS_DIR = DATA_DIR / "originals"
MUSIC_DIR = DATA_DIR / "music"
QUOTES_DIR = DATA_DIR / "quotes"

VARIATIONS_DIR = OUTPUT_DIR
SCHEDULES_DIR = OUTPUT_DIR
LOGS_DIR = OUTPUT_DIR / "logs"

RUNTIME_DIRS = (
    ASSETS_DIR,
    EMOJI_ASSETS_DIR,
    TWEMOJI_DIR,
    DATA_DIR,
    OUTPUT_DIR,
    ORIGINALS_DIR,
    MUSIC_DIR,
    QUOTES_DIR,
    LOGS_DIR,
)


def ensure_runtime_dirs() -> None:
    for directory in RUNTIME_DIRS:
        directory.mkdir(parents=True, exist_ok=True)
