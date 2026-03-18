from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Literal

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
)
from video_unicalizator.paths import OUTPUT_DIR


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


QuoteLayerStyle = TextStyle


@dataclass(slots=True)
class VideoEditProfile:
    """Полный макет конкретного исходника: два слоя цитат."""

    layer_a: QuoteLayerStyle = field(default_factory=QuoteLayerStyle)
    layer_b: QuoteLayerStyle = field(
        default_factory=lambda: QuoteLayerStyle(
            preview_text="",
            position_y=0.78,
            font_size=max(28, DEFAULT_FONT_SIZE - 8),
            box_width_ratio=0.68,
            background_opacity=0.36,
            enabled=False,
        )
    )

    def copy(self) -> "VideoEditProfile":
        return VideoEditProfile(layer_a=replace(self.layer_a), layer_b=replace(self.layer_b))


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
    filter_preset: str = "neutral_contrast"
    trim_start: float = 0.0
    trim_end: float = 0.0
    output_duration: float = 0.0
    warning_reason_codes: list[str] = field(default_factory=list)
    recipe_key: str = ""
    skip_reason: str = ""
    nearest_reference_video: Path | None = None
    nearest_distance_score: float | None = None


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
    selected_layer: Literal["A", "B"] = "A"
    default_layer_a_sample_text: str = DEFAULT_PREVIEW_TEXT
    default_layer_b_sample_text: str = ""
    video_profiles: dict[str, VideoEditProfile] = field(default_factory=dict)
    generated_variations: list[GeneratedVariation] = field(default_factory=list)
    schedule_entries: list[ScheduleEntry] = field(default_factory=list)
    schedule_file: Path | None = None
    output_dir: Path = field(default_factory=lambda: OUTPUT_DIR)
    ffmpeg_available: bool = False
    last_music_track: Path | None = None

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
        default_layer_b = QuoteLayerStyle(
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

    def set_default_layer_sample(self, layer: Literal["A", "B"], text: str) -> None:
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
