from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class MusicChoice:
    track: Path | None
    cycle_index: int = 0


@dataclass(slots=True)
class QuoteChoice:
    text: str
    cycle_index: int = 0
    source_mode: str = "pool"


class _UnusedFirstRotation(Generic[T]):
    def __init__(self) -> None:
        self._last_item: T | None = None
        self._remaining_items: list[T] = []
        self._known_signature: tuple[str, ...] = ()
        self._cycle_index: int = 0

    def reset(self) -> None:
        self._last_item = None
        self._remaining_items = []
        self._known_signature = ()
        self._cycle_index = 0

    def _normalize_items(self, items: list[T]) -> list[T]:
        raise NotImplementedError

    def _item_key(self, item: T) -> str:
        return str(item)

    def _ensure_pool(self, items: list[T]) -> list[T]:
        normalized = self._normalize_items(items)
        signature = tuple(self._item_key(item) for item in normalized)
        if signature != self._known_signature:
            self._known_signature = signature
            self._remaining_items = list(normalized)
            self._cycle_index = 0
            self._last_item = None
        elif not self._remaining_items:
            self._remaining_items = list(normalized)
            self._cycle_index += 1
        return normalized

    def _preview_choice(self, items: list[T], accept_index: int) -> tuple[T | None, int]:
        normalized = self._normalize_items(items)
        if not normalized:
            return None, 0

        safe_index = max(0, accept_index)
        item_count = len(normalized)
        cycle_index = safe_index // item_count
        item_index = safe_index % item_count
        return normalized[item_index], cycle_index

    def pick(
        self,
        items: list[T],
        *,
        used_in_roll: set[T] | None = None,
        preferred_item: T | None = None,
    ) -> tuple[T | None, int]:
        normalized = self._ensure_pool(items)
        if not normalized:
            return None, self._cycle_index

        roll_items = used_in_roll or set()
        options = [item for item in self._remaining_items if item not in roll_items]
        if not options:
            options = list(self._remaining_items)

        non_repeating = [item for item in options if item != self._last_item]
        if non_repeating:
            options = non_repeating

        chosen = preferred_item if preferred_item in options else random.choice(options)
        self._remaining_items = [item for item in self._remaining_items if item != chosen]
        self._last_item = chosen
        return chosen, self._cycle_index


class MusicRotation(_UnusedFirstRotation[Path]):
    """Выбирает музыку по циклам: сначала неиспользованные треки, потом новый круг."""

    def _normalize_items(self, items: list[Path]) -> list[Path]:
        return sorted({Path(item) for item in items}, key=lambda item: item.name.lower())

    def preview_for_accept_index(self, tracks: list[Path], accept_index: int) -> MusicChoice:
        track, cycle_index = self._preview_choice(tracks, accept_index)
        return MusicChoice(track=track, cycle_index=cycle_index)

    def pick(
        self,
        tracks: list[Path],
        *,
        used_in_roll: set[Path] | None = None,
        preferred_track: Path | None = None,
    ) -> MusicChoice:
        track, cycle_index = super().pick(
            tracks,
            used_in_roll=used_in_roll,
            preferred_item=preferred_track,
        )
        return MusicChoice(track=track, cycle_index=cycle_index)


class QuoteRotation(_UnusedFirstRotation[str]):
    """Выбирает цитаты по циклам: сначала новые, потом повтор после исчерпания пула."""

    def _normalize_items(self, items: list[str]) -> list[str]:
        normalized = [item.strip() for item in items if item and item.strip()]
        seen: set[str] = set()
        ordered: list[str] = []
        for item in normalized:
            if item in seen:
                continue
            seen.add(item)
            ordered.append(item)
        return ordered

    def pick(
        self,
        quotes: list[str],
        *,
        used_in_roll: set[str] | None = None,
        preferred_quote: str | None = None,
    ) -> QuoteChoice:
        text, cycle_index = super().pick(
            quotes,
            used_in_roll=used_in_roll,
            preferred_item=preferred_quote,
        )
        return QuoteChoice(text=text or "", cycle_index=cycle_index, source_mode="pool")
