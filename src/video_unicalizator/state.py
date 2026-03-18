from __future__ import annotations

from dataclasses import dataclass, field
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
from video_unicalizator.paths import SCHEDULES_DIR, VARIATIONS_DIR


@dataclass(slots=True)
class TextStyle:
    """Настройки текстового блока поверх видео."""

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

    @property
    def max_width_ratio(self) -> float:
        return self.box_width_ratio

    @max_width_ratio.setter
    def max_width_ratio(self, value: float) -> None:
        self.box_width_ratio = value


@dataclass(slots=True)
class ColorGradeProfile:
    """Диапазоны творческой цветокоррекции для вариаций."""

    brightness_jitter: float = 0.08
    contrast_jitter: float = 0.10
    saturation_jitter: float = 0.18
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


@dataclass(slots=True)
class MediaLibrary:
    """Файлы, которые пользователь загрузил в интерфейсе."""

    original_videos: list[Path] = field(default_factory=list)
    music_tracks: list[Path] = field(default_factory=list)
    quote_files: list[Path] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)


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
    generated_variations: list[GeneratedVariation] = field(default_factory=list)
    schedule_entries: list[ScheduleEntry] = field(default_factory=list)
    schedule_file: Path | None = None
    variations_output_dir: Path = field(default_factory=lambda: VARIATIONS_DIR)
    schedules_output_dir: Path = field(default_factory=lambda: SCHEDULES_DIR)
    ffmpeg_available: bool = False
    last_music_track: Path | None = None
