from __future__ import annotations

import random
from pathlib import Path


class MusicRotation:
    """Выбирает музыку так, чтобы подряд не повторялся один и тот же трек."""

    def __init__(self) -> None:
        self._last_track: Path | None = None

    def pick(self, tracks: list[Path]) -> Path | None:
        if not tracks:
            return None
        if len(tracks) == 1:
            self._last_track = tracks[0]
            return tracks[0]

        options = [track for track in tracks if track != self._last_track]
        chosen = random.choice(options or tracks)
        self._last_track = chosen
        return chosen

