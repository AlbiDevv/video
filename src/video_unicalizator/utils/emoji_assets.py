from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from video_unicalizator.paths import TWEMOJI_DIR


def _codepoints(cluster: str, keep_variation_selectors: bool) -> list[str]:
    codepoints: list[str] = []
    for character in cluster:
        value = ord(character)
        if not keep_variation_selectors and value == 0xFE0F:
            continue
        codepoints.append(f"{value:x}")
    return codepoints


def _candidate_names(cluster: str) -> list[str]:
    candidates: list[str] = []
    with_variation = "-".join(_codepoints(cluster, keep_variation_selectors=True))
    without_variation = "-".join(_codepoints(cluster, keep_variation_selectors=False))
    if with_variation:
        candidates.append(with_variation)
    if without_variation and without_variation != with_variation:
        candidates.append(without_variation)
    return candidates


@lru_cache(maxsize=512)
def resolve_emoji_asset(cluster: str) -> Path | None:
    for candidate in _candidate_names(cluster):
        asset_path = TWEMOJI_DIR / f"{candidate}.png"
        if asset_path.exists():
            return asset_path
    return None
