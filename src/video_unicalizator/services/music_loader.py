from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class MusicChoice:
    track: Path | None
    cycle_index: int = 0


class MusicRotation:
    """Выбирает музыку по циклам: сначала неиспользованные треки, потом новый круг."""

    def __init__(self) -> None:
        self._last_track: Path | None = None
        self._remaining_tracks: list[Path] = []
        self._known_tracks: tuple[str, ...] = ()
        self._cycle_index: int = 0

    def reset(self) -> None:
        self._last_track = None
        self._remaining_tracks = []
        self._known_tracks = ()
        self._cycle_index = 0

    def _normalize_tracks(self, tracks: list[Path]) -> list[Path]:
        return sorted({Path(track) for track in tracks}, key=lambda item: item.name.lower())

    def _ensure_pool(self, tracks: list[Path]) -> list[Path]:
        normalized = self._normalize_tracks(tracks)
        signature = tuple(str(track) for track in normalized)
        if signature != self._known_tracks:
            self._known_tracks = signature
            self._remaining_tracks = list(normalized)
            self._cycle_index = 0
            self._last_track = None
        elif not self._remaining_tracks:
            self._remaining_tracks = list(normalized)
            self._cycle_index += 1
        return normalized

    def preview_for_accept_index(self, tracks: list[Path], accept_index: int) -> MusicChoice:
        normalized = self._normalize_tracks(tracks)
        if not normalized:
            return MusicChoice(track=None, cycle_index=0)

        safe_index = max(0, accept_index)
        track_count = len(normalized)
        cycle_index = safe_index // track_count
        track_index = safe_index % track_count
        return MusicChoice(track=normalized[track_index], cycle_index=cycle_index)

    def pick(self, tracks: list[Path]) -> MusicChoice:
        normalized = self._ensure_pool(tracks)
        if not normalized:
            return MusicChoice(track=None, cycle_index=self._cycle_index)

        options = [track for track in self._remaining_tracks if track != self._last_track]
        if not options:
            options = list(self._remaining_tracks)

        chosen = random.choice(options)
        self._remaining_tracks = [track for track in self._remaining_tracks if track != chosen]
        self._last_track = chosen
        return MusicChoice(track=chosen, cycle_index=self._cycle_index)
