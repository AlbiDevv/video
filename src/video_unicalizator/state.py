from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from video_unicalizator.config import (
    DEFAULT_BG_COLOR,
    DEFAULT_BG_OPACITY,
    DEFAULT_BOX_WIDTH_RATIO,
    DEFAULT_CORNER_RADIUS,
    DEFAULT_FONT_SIZE,
    DEFAULT_LINE_SPACING,
    DEFAULT_PADDING_X_RATIO,
    DEFAULT_PADDING_Y_RATIO,
    DEFAULT_PREVIEW_TEXT,
    DEFAULT_SHADOW_STRENGTH,
    DEFAULT_TEXT_ALIGN,
    DEFAULT_TEXT_COLOR,
    DEFAULT_VARIATIONS,
    MUSIC_VOLUME,
    TIMELINE_DEFAULT_CLIP_SECONDS,
    TIMELINE_MIN_CLIP_SECONDS,
)
from video_unicalizator.paths import OUTPUT_DIR

LayerKey = Literal["A", "B"]
TimelineLane = Literal["A", "B", "Music"]
TimelineSourceMode = Literal["pool", "sample"]


def _clip_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}"


def _clamp_seconds(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(slots=True)
class TextStyle:
    """Настройки одного текстового слоя поверх видео."""

    text_color: str = DEFAULT_TEXT_COLOR
    background_color: str = DEFAULT_BG_COLOR
    background_opacity: float = DEFAULT_BG_OPACITY
    shadow_strength: float = DEFAULT_SHADOW_STRENGTH
    font_size: int = DEFAULT_FONT_SIZE
    font_name: str = "Arial"
    preview_text: str = DEFAULT_PREVIEW_TEXT
    position_x: float = 0.5
    position_y: float = 0.2
    box_width_ratio: float = DEFAULT_BOX_WIDTH_RATIO
    line_spacing: float = DEFAULT_LINE_SPACING
    padding_x: int = int(DEFAULT_FONT_SIZE * DEFAULT_PADDING_X_RATIO)
    padding_y: int = int(DEFAULT_FONT_SIZE * DEFAULT_PADDING_Y_RATIO)
    corner_radius: int = DEFAULT_CORNER_RADIUS
    text_align: str = DEFAULT_TEXT_ALIGN
    enabled: bool = True

    @property
    def max_width_ratio(self) -> float:
        return self.box_width_ratio

    @max_width_ratio.setter
    def max_width_ratio(self, value: float) -> None:
        self.box_width_ratio = value

    def with_preview_text(self, text: str) -> "TextStyle":
        return replace(self, preview_text=text)


QuoteLaneStyle = TextStyle


@dataclass(slots=True)
class TimelineClip:
    """Базовый клип на таймлайне."""

    clip_id: str = field(default_factory=lambda: _clip_id("clip"))
    start_sec: float = 0.0
    end_sec: float = TIMELINE_DEFAULT_CLIP_SECONDS
    enabled: bool = True

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.end_sec - self.start_sec)


@dataclass(slots=True)
class QuoteClip(TimelineClip):
    """Временной клип для одной дорожки цитаты."""

    lane: LayerKey = "A"
    sample_text: str = ""
    source_mode: TimelineSourceMode = "pool"


@dataclass(slots=True)
class MusicClip(TimelineClip):
    """Временной музыкальный клип."""

    volume: float = 1.0
    source_mode: TimelineSourceMode = "pool"
    bound_track: Path | None = None
    track_locked: bool = False
    track_offset_sec: float = 0.0


def normalize_music_track_pool(tracks: list[Path]) -> list[Path]:
    ordered: list[Path] = []
    seen: set[str] = set()
    for track in tracks:
        normalized = Path(track)
        key = str(normalized)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(normalized)
    return ordered


def resolve_music_track_bindings(
    clips: list[MusicClip],
    tracks: list[Path],
    *,
    preferred_first_track: Path | None = None,
) -> dict[str, tuple[Path | None, int]]:
    pool = normalize_music_track_pool(tracks)
    bindings: dict[str, tuple[Path | None, int]] = {}
    used_in_cycle: set[Path] = set()
    cycle_index = 0
    preferred_pending = Path(preferred_first_track) if preferred_first_track is not None else None
    ordered = sorted(clips, key=lambda item: (item.start_sec, item.end_sec, item.clip_id))
    continuity_counts: dict[str, int] = {}
    continuity_bindings: dict[str, tuple[Path | None, int]] = {}

    for clip in ordered:
        if clip.track_locked or clip.bound_track is None:
            continue
        key = str(Path(clip.bound_track))
        continuity_counts[key] = continuity_counts.get(key, 0) + 1

    def reserve_next_auto_track() -> tuple[Path | None, int]:
        nonlocal cycle_index, preferred_pending
        if not pool:
            return None, cycle_index

        available = [track for track in pool if track not in used_in_cycle]
        if not available:
            used_in_cycle.clear()
            cycle_index += 1
            available = list(pool)

        if preferred_pending is not None and preferred_pending in available:
            chosen_track = preferred_pending
            preferred_pending = None
        else:
            chosen_track = available[0]
        used_in_cycle.add(chosen_track)
        return chosen_track, cycle_index

    for clip in ordered:
        bound_track = Path(clip.bound_track) if clip.bound_track is not None else None
        if clip.track_locked and bound_track is not None:
            bindings[clip.clip_id] = (bound_track, cycle_index)
            if bound_track in pool:
                used_in_cycle.add(bound_track)
                if preferred_pending == bound_track:
                    preferred_pending = None
            continue

        continuity_key: str | None = None
        if bound_track is not None and continuity_counts.get(str(bound_track), 0) > 1:
            continuity_key = str(bound_track)

        if continuity_key is not None and continuity_key in continuity_bindings:
            bindings[clip.clip_id] = continuity_bindings[continuity_key]
            continue

        chosen_track, chosen_cycle_index = reserve_next_auto_track()
        bindings[clip.clip_id] = (chosen_track, chosen_cycle_index)
        if continuity_key is not None:
            continuity_bindings[continuity_key] = (chosen_track, chosen_cycle_index)
    return bindings


def bind_unassigned_music_clips(clips: list[MusicClip], tracks: list[Path]) -> list[MusicClip]:
    bindings = resolve_music_track_bindings(clips, tracks)
    bound: list[MusicClip] = []
    for clip in clips:
        if clip.track_locked and clip.bound_track is not None:
            bound.append(replace(clip))
            continue
        track, _cycle_index = bindings.get(clip.clip_id, (None, 0))
        if track is None:
            bound.append(replace(clip))
            continue
        bound.append(replace(clip, bound_track=track))
    return bound


@dataclass(slots=True)
class VideoTimelineProfile:
    """Таймлайн конкретного исходника."""

    quote_clips_a: list[QuoteClip] = field(default_factory=list)
    quote_clips_b: list[QuoteClip] = field(default_factory=list)
    music_clips: list[MusicClip] = field(default_factory=list)
    duration_hint: float = 0.0

    def copy(self) -> "VideoTimelineProfile":
        return VideoTimelineProfile(
            quote_clips_a=[replace(clip) for clip in self.quote_clips_a],
            quote_clips_b=[replace(clip) for clip in self.quote_clips_b],
            music_clips=[replace(clip) for clip in self.music_clips],
            duration_hint=self.duration_hint,
        )

    def clips_for_lane(self, lane: TimelineLane) -> list[TimelineClip]:
        if lane == "A":
            return self.quote_clips_a
        if lane == "B":
            return self.quote_clips_b
        return self.music_clips

    def set_clips_for_lane(self, lane: TimelineLane, clips: list[TimelineClip]) -> None:
        if lane == "A":
            self.quote_clips_a = [replace(clip) for clip in clips if isinstance(clip, QuoteClip)]
            return
        if lane == "B":
            self.quote_clips_b = [replace(clip) for clip in clips if isinstance(clip, QuoteClip)]
            return
        self.music_clips = [replace(clip) for clip in clips if isinstance(clip, MusicClip)]

    def active_quote_clip(self, lane: LayerKey, current_time: float) -> QuoteClip | None:
        clips = self.quote_clips_a if lane == "A" else self.quote_clips_b
        for clip in clips:
            if clip.enabled and clip.start_sec <= current_time <= clip.end_sec:
                return clip
        return None

    def active_music_clips(self, current_time: float) -> list[MusicClip]:
        return [
            replace(clip)
            for clip in self.music_clips
            if clip.enabled and clip.start_sec <= current_time <= clip.end_sec
        ]

    def normalize(self, *, duration: float, layer_a: QuoteLaneStyle, layer_b: QuoteLaneStyle) -> "VideoTimelineProfile":
        normalized = self.copy()
        normalized.duration_hint = max(0.0, duration)
        normalized.quote_clips_a = _normalize_quote_clips(
            normalized.quote_clips_a,
            duration=duration,
            lane="A",
            sample_text=layer_a.preview_text,
            ensure_default=layer_a.enabled,
        )
        normalized.quote_clips_b = _normalize_quote_clips(
            normalized.quote_clips_b,
            duration=duration,
            lane="B",
            sample_text=layer_b.preview_text,
            ensure_default=layer_b.enabled,
        )
        normalized.music_clips = _normalize_music_clips(normalized.music_clips, duration=duration)
        return normalized

    def cut_range(self, start_sec: float, end_sec: float) -> "VideoTimelineProfile":
        clipped = self.copy()
        clipped.quote_clips_a = [
            clip for clip in cut_timeline_clips_to_range(clipped.quote_clips_a, start_sec=start_sec, end_sec=end_sec)
            if isinstance(clip, QuoteClip)
        ]
        clipped.quote_clips_b = [
            clip for clip in cut_timeline_clips_to_range(clipped.quote_clips_b, start_sec=start_sec, end_sec=end_sec)
            if isinstance(clip, QuoteClip)
        ]
        clipped.music_clips = [
            clip for clip in cut_timeline_clips_to_range(clipped.music_clips, start_sec=start_sec, end_sec=end_sec)
            if isinstance(clip, MusicClip)
        ]
        return clipped


def _normalize_quote_clips(
    clips: list[QuoteClip],
    *,
    duration: float,
    lane: LayerKey,
    sample_text: str,
    ensure_default: bool,
) -> list[QuoteClip]:
    normalized = _normalize_lane_clips(clips, duration=duration, minimum_duration=TIMELINE_MIN_CLIP_SECONDS)
    if normalized:
        return [
            QuoteClip(
                clip_id=clip.clip_id,
                start_sec=clip.start_sec,
                end_sec=clip.end_sec,
                enabled=clip.enabled,
                lane=lane,
                sample_text=clip.sample_text or sample_text,
                source_mode=clip.source_mode,
            )
            for clip in normalized
        ]
    if ensure_default and duration > 0:
        return [
            QuoteClip(
                clip_id=_clip_id(f"quote_{lane.lower()}"),
                start_sec=0.0,
                end_sec=duration,
                enabled=True,
                lane=lane,
                sample_text=sample_text,
                source_mode="pool",
            )
        ]
    return []


def cut_timeline_clips_to_range(
    clips: list[TimelineClip],
    *,
    start_sec: float,
    end_sec: float,
) -> list[TimelineClip]:
    """Удаляет/режет клипы так, чтобы внутри диапазона осталась пустая зона."""

    cut_start = min(start_sec, end_sec)
    cut_end = max(start_sec, end_sec)
    if cut_end <= cut_start:
        return [replace(clip) for clip in clips]

    result: list[TimelineClip] = []
    for original in sorted(clips, key=lambda item: (item.start_sec, item.end_sec, item.clip_id)):
        clip = replace(original)
        if clip.end_sec <= cut_start or clip.start_sec >= cut_end:
            result.append(clip)
            continue
        if clip.start_sec >= cut_start and clip.end_sec <= cut_end:
            continue
        if clip.start_sec < cut_start and clip.end_sec > cut_end:
            left_clip = _copy_clip_with_range(
                clip,
                start_sec=round(clip.start_sec, 3),
                end_sec=round(cut_start, 3),
                preserve_clip_id=True,
            )
            right_clip = _copy_clip_with_range(
                clip,
                start_sec=round(cut_end, 3),
                end_sec=round(clip.end_sec, 3),
                preserve_clip_id=False,
                track_progress_sec=round(max(0.0, cut_start - clip.start_sec), 3),
            )
            if left_clip.duration_sec >= TIMELINE_MIN_CLIP_SECONDS:
                result.append(left_clip)
            if right_clip.duration_sec >= TIMELINE_MIN_CLIP_SECONDS:
                result.append(right_clip)
            continue
        if clip.start_sec < cut_start:
            trimmed = _copy_clip_with_range(
                clip,
                start_sec=round(clip.start_sec, 3),
                end_sec=round(cut_start, 3),
                preserve_clip_id=True,
            )
            if trimmed.duration_sec >= TIMELINE_MIN_CLIP_SECONDS:
                result.append(trimmed)
            continue
        trimmed = _copy_clip_with_range(
            clip,
            start_sec=round(cut_end, 3),
            end_sec=round(clip.end_sec, 3),
            preserve_clip_id=True,
            track_progress_sec=round(max(0.0, cut_start - clip.start_sec), 3),
        )
        if trimmed.duration_sec >= TIMELINE_MIN_CLIP_SECONDS:
            result.append(trimmed)

    return result


def _copy_clip_with_range(
    clip: TimelineClip,
    *,
    start_sec: float,
    end_sec: float,
    preserve_clip_id: bool,
    track_progress_sec: float | None = None,
) -> TimelineClip:
    if isinstance(clip, QuoteClip):
        return QuoteClip(
            clip_id=clip.clip_id if preserve_clip_id else _clip_id(f"quote_{clip.lane.lower()}"),
            start_sec=start_sec,
            end_sec=end_sec,
            enabled=clip.enabled,
            lane=clip.lane,
            sample_text=clip.sample_text,
            source_mode=clip.source_mode,
        )
    if isinstance(clip, MusicClip):
        start_delta = (start_sec - clip.start_sec) if track_progress_sec is None else track_progress_sec
        return MusicClip(
            clip_id=clip.clip_id if preserve_clip_id else _clip_id("music"),
            start_sec=start_sec,
            end_sec=end_sec,
            enabled=clip.enabled,
            volume=clip.volume,
            source_mode=clip.source_mode,
            bound_track=clip.bound_track,
            track_locked=clip.track_locked,
            track_offset_sec=max(0.0, round(clip.track_offset_sec + start_delta, 3)),
        )
    return TimelineClip(
        clip_id=clip.clip_id if preserve_clip_id else _clip_id("clip"),
        start_sec=start_sec,
        end_sec=end_sec,
        enabled=clip.enabled,
    )


def _normalize_music_clips(clips: list[MusicClip], *, duration: float) -> list[MusicClip]:
    normalized = _normalize_lane_clips(clips, duration=duration, minimum_duration=TIMELINE_MIN_CLIP_SECONDS)
    return [
        MusicClip(
            clip_id=clip.clip_id,
            start_sec=clip.start_sec,
            end_sec=clip.end_sec,
            enabled=clip.enabled,
            volume=max(0.0, min(2.0, clip.volume)),
            source_mode=clip.source_mode,
            bound_track=clip.bound_track,
            track_locked=clip.track_locked,
            track_offset_sec=max(0.0, round(clip.track_offset_sec, 3)),
        )
        for clip in normalized
    ]


def _normalize_lane_clips(
    clips: list[TimelineClip],
    *,
    duration: float,
    minimum_duration: float,
) -> list[TimelineClip]:
    if duration <= 0:
        return []

    normalized: list[TimelineClip] = []
    ordered = sorted(
        (replace(clip) for clip in clips),
        key=lambda item: (item.start_sec, item.end_sec, item.clip_id),
    )

    for clip in ordered:
        start_sec = _clamp_seconds(float(clip.start_sec), 0.0, duration)
        end_sec = _clamp_seconds(float(clip.end_sec), 0.0, duration)
        if end_sec <= start_sec:
            end_sec = min(duration, start_sec + minimum_duration)
        if normalized:
            start_sec = max(start_sec, normalized[-1].end_sec)
            if end_sec <= start_sec:
                end_sec = min(duration, start_sec + minimum_duration)
        if end_sec - start_sec < minimum_duration:
            if start_sec + minimum_duration > duration:
                continue
            end_sec = start_sec + minimum_duration
        if end_sec > duration:
            if duration - start_sec < minimum_duration:
                continue
            end_sec = duration
        clip.start_sec = round(start_sec, 3)
        clip.end_sec = round(end_sec, 3)
        normalized.append(clip)

    return normalized


@dataclass(slots=True)
class VideoEditProfile:
    """Полный макет конкретного исходника: два слоя цитат и их таймлайн."""

    layer_a: QuoteLaneStyle = field(default_factory=QuoteLaneStyle)
    layer_b: QuoteLaneStyle = field(
        default_factory=lambda: QuoteLaneStyle(
            preview_text="",
            position_y=0.78,
            font_size=max(28, DEFAULT_FONT_SIZE - 8),
            box_width_ratio=0.68,
            background_opacity=0.36,
            enabled=False,
        )
    )
    timeline: VideoTimelineProfile = field(default_factory=VideoTimelineProfile)

    def copy(self) -> "VideoEditProfile":
        return VideoEditProfile(
            layer_a=replace(self.layer_a),
            layer_b=replace(self.layer_b),
            timeline=self.timeline.copy(),
        )

    def normalized_for_duration(self, duration: float) -> "VideoEditProfile":
        normalized = self.copy()
        normalized.timeline = normalized.timeline.normalize(
            duration=duration,
            layer_a=normalized.layer_a,
            layer_b=normalized.layer_b,
        )
        return normalized


@dataclass(slots=True)
class ColorGradeProfile:
    """Диапазоны генерации фильтров и цветокоррекции."""

    brightness_jitter: float = 0.08
    contrast_jitter: float = 0.10
    saturation_jitter: float = 0.16
    accent_jitter: float = 0.14


@dataclass(slots=True)
class GenerationSettings:
    """Общие настройки генерации."""

    variation_count: int = DEFAULT_VARIATIONS
    music_volume: float = MUSIC_VOLUME
    apply_text_style_to_all: bool = True
    enforce_quality_gate: bool = True
    quality_gate_mode: Literal["soft", "strict", "off"] = "soft"
    max_quality_attempts: int = 2
    continue_on_variation_error: bool = True
    max_warning_variations: int = 1
    candidate_search_attempts: int = 40
    render_retry_attempts: int = 4
    duration_uniqueness_precision: float = 0.1
    enhance_sharpness: bool = False


class GenerationCancelledError(RuntimeError):
    """Сигнализирует, что генерация была остановлена пользователем."""


class GenerationCancelToken:
    """Thread-safe токен немедленной отмены текущего запуска."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[], None]] = []

    def cancel(self) -> bool:
        with self._lock:
            if self._event.is_set():
                return False
            self._event.set()
            callbacks = list(self._callbacks)
        for callback in callbacks:
            try:
                callback()
            except Exception:
                continue
        return True

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def throw_if_cancelled(self, message: str = "Генерация остановлена пользователем.") -> None:
        if self.is_cancelled():
            raise GenerationCancelledError(message)

    def register_callback(self, callback: Callable[[], None]) -> None:
        should_call_now = False
        with self._lock:
            if self._event.is_set():
                should_call_now = True
            else:
                self._callbacks.append(callback)
        if should_call_now:
            callback()

    def unregister_callback(self, callback: Callable[[], None]) -> None:
        with self._lock:
            self._callbacks = [item for item in self._callbacks if item is not callback]


@dataclass(slots=True)
class MediaLibrary:
    """Файлы, которые пользователь загрузил в интерфейсе."""

    original_videos: list[Path] = field(default_factory=list)
    music_tracks: list[Path] = field(default_factory=list)
    quote_files_a: list[Path] = field(default_factory=list)
    quote_files_b: list[Path] = field(default_factory=list)
    quotes_a: list[str] = field(default_factory=list)
    quotes_b: list[str] = field(default_factory=list)

    @property
    def quote_files(self) -> list[Path]:
        return [*self.quote_files_a, *self.quote_files_b]

    @property
    def quotes(self) -> list[str]:
        return [*self.quotes_a, *self.quotes_b]


@dataclass(slots=True)
class EditorLayoutState:
    """Текущее состояние workspace редактора."""

    media_rail_width: int = 280
    inspector_width: int = 320
    timeline_height: int = 360
    media_rail_visible: bool = True
    inspector_visible: bool = True
    drawer_visible: bool = False
    timeline_visible: bool = True
    console_visible: bool = False


@dataclass(slots=True)
class RenderedQuoteAssignment:
    """Итоговое назначение текста на конкретный клип дорожки."""

    lane: LayerKey
    clip_id: str
    text: str
    start_sec: float
    end_sec: float
    source_mode: TimelineSourceMode = "pool"
    cycle_index: int = 0


@dataclass(slots=True)
class RenderedMusicAssignment:
    """Итоговое назначение трека на музыкальный клип."""

    clip_id: str
    track: Path | None
    start_sec: float
    end_sec: float
    volume: float
    track_offset_sec: float = 0.0
    source_mode: TimelineSourceMode = "pool"
    cycle_index: int = 0
    track_locked: bool = False


@dataclass(slots=True)
class GeneratedVariation:
    """Описание одного сгенерированного ролика."""

    source_video: Path
    output_video: Path
    quote: str
    music_track: Path | None
    speed_factor: float
    sharpness_score: float
    visual_difference_score: float
    quality_warnings: list[str] = field(default_factory=list)
    accepted_after_soft_gate: bool = False
    primary_quote: str = ""
    secondary_quote: str = ""
    music_cycle_index: int = 0
    music_master_volume: float = MUSIC_VOLUME
    filter_preset: str = "neutral_contrast"
    trim_start: float = 0.0
    trim_end: float = 0.0
    output_duration: float = 0.0
    warning_reason_codes: list[str] = field(default_factory=list)
    recipe_key: str = ""
    skip_reason: str = ""
    nearest_reference_video: Path | None = None
    nearest_distance_score: float | None = None
    quote_assignments: list[RenderedQuoteAssignment] = field(default_factory=list)
    music_assignments: list[RenderedMusicAssignment] = field(default_factory=list)


@dataclass(slots=True)
class ScheduleEntry:
    """Одна строка таблицы публикаций."""

    file_name: str
    publish_time: str


@dataclass(slots=True)
class GenerationProgressEvent:
    """Событие прогресса генерации для UI и логов."""

    stage: str
    message: str
    progress: float
    level: str = "info"
    current_file: str | None = None
    rendered_seconds: float | None = None
    total_seconds: float | None = None
    fps: float | None = None
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def timestamp(self) -> str:
        return self.created_at.strftime("%H:%M:%S")


@dataclass(slots=True)
class AppState:
    """Глобальное состояние приложения."""

    media: MediaLibrary = field(default_factory=MediaLibrary)
    text_style: TextStyle = field(default_factory=TextStyle)
    generation: GenerationSettings = field(default_factory=GenerationSettings)
    color_grade: ColorGradeProfile = field(default_factory=ColorGradeProfile)
    selected_video: Path | None = None
    selected_layer: TimelineLane = "A"
    default_layer_a_sample_text: str = DEFAULT_PREVIEW_TEXT
    default_layer_b_sample_text: str = ""
    video_profiles: dict[str, VideoEditProfile] = field(default_factory=dict)
    generated_variations: list[GeneratedVariation] = field(default_factory=list)
    schedule_entries: list[ScheduleEntry] = field(default_factory=list)
    schedule_file: Path | None = None
    output_dir: Path = field(default_factory=lambda: OUTPUT_DIR)
    ffmpeg_available: bool = False
    last_music_track: Path | None = None
    editor_layout: EditorLayoutState = field(default_factory=EditorLayoutState)

    @property
    def variations_output_dir(self) -> Path:
        return self.output_dir

    @variations_output_dir.setter
    def variations_output_dir(self, value: Path) -> None:
        self.output_dir = value

    @property
    def schedules_output_dir(self) -> Path:
        return self.output_dir

    @schedules_output_dir.setter
    def schedules_output_dir(self, value: Path) -> None:
        self.output_dir = value

    def build_default_profile(self) -> VideoEditProfile:
        default_layer_a = replace(
            self.text_style,
            preview_text=(self.default_layer_a_sample_text or self.text_style.preview_text).strip() or DEFAULT_PREVIEW_TEXT,
            enabled=True,
        )
        default_layer_b = QuoteLaneStyle(
            preview_text=(self.default_layer_b_sample_text or "").strip(),
            position_y=0.78,
            font_size=max(28, self.text_style.font_size - 8),
            font_name=self.text_style.font_name,
            box_width_ratio=min(0.82, self.text_style.box_width_ratio),
            background_color=self.text_style.background_color,
            text_color=self.text_style.text_color,
            background_opacity=max(0.0, self.text_style.background_opacity - 0.08),
            shadow_strength=self.text_style.shadow_strength,
            corner_radius=self.text_style.corner_radius,
            enabled=bool((self.default_layer_b_sample_text or "").strip()),
        )
        return VideoEditProfile(layer_a=default_layer_a, layer_b=default_layer_b)

    def set_default_layer_sample(self, layer: LayerKey, text: str) -> None:
        normalized = text.strip()
        if layer == "A":
            self.default_layer_a_sample_text = normalized or DEFAULT_PREVIEW_TEXT
            self.text_style.preview_text = self.default_layer_a_sample_text
        else:
            self.default_layer_b_sample_text = normalized

    def ensure_video_profile(self, video_path: Path) -> VideoEditProfile:
        key = str(video_path)
        if key not in self.video_profiles:
            self.video_profiles[key] = self.build_default_profile()
        return self.video_profiles[key]

    def remove_original(self, video_path: Path) -> Path | None:
        originals = list(self.media.original_videos)
        if video_path not in originals:
            return self.selected_video

        removed_index = originals.index(video_path)
        originals.pop(removed_index)
        self.media.original_videos = originals
        self.video_profiles.pop(str(video_path), None)

        if not originals:
            self.selected_video = None
            return None

        if self.selected_video == video_path:
            replacement_index = min(removed_index, len(originals) - 1)
            self.selected_video = originals[replacement_index]
        elif self.selected_video not in originals:
            self.selected_video = originals[min(removed_index, len(originals) - 1)]

        return self.selected_video
