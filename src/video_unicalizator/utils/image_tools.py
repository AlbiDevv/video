from __future__ import annotations

import math
import os
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import ImageColor, ImageFont

from video_unicalizator.config import TARGET_HEIGHT, TARGET_WIDTH


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    return ImageColor.getrgb(color)


def hex_to_rgba(color: str, alpha: float) -> tuple[int, int, int, int]:
    r, g, b = hex_to_rgb(color)
    return r, g, b, int(clamp(alpha, 0.0, 1.0) * 255)


@lru_cache(maxsize=64)
def resolve_font_path(font_name: str) -> str | None:
    """Пытается найти системный шрифт по имени для PIL."""

    candidates = [font_name, f"{font_name}.ttf", f"{font_name}.otf"]
    for candidate in candidates:
        try:
            ImageFont.truetype(candidate, 32)
            return candidate
        except OSError:
            continue

    windows_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    if not windows_fonts.exists():
        return None

    normalized = "".join(ch for ch in font_name.lower() if ch.isalnum())
    for extension in ("*.ttf", "*.otf", "*.ttc"):
        for path in windows_fonts.glob(extension):
            stem = "".join(ch for ch in path.stem.lower() if ch.isalnum())
            if normalized and normalized in stem:
                return str(path)
    return None


def load_font(font_name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_path = resolve_font_path(font_name)
    if font_path:
        try:
            return ImageFont.truetype(font_path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def apply_color_grade(
    frame_bgr: np.ndarray,
    brightness_shift: float,
    contrast_shift: float,
    saturation_shift: float,
    accent_color: tuple[int, int, int],
    accent_strength: float,
) -> np.ndarray:
    """Лёгкая творческая коррекция без агрессивных артефактов."""

    image = frame_bgr.astype(np.float32) / 255.0
    image = np.clip((image - 0.5) * (1.0 + contrast_shift) + 0.5 + brightness_shift, 0.0, 1.0)

    hsv = cv2.cvtColor((image * 255).astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 1] = np.clip(hsv[..., 1] * (1.0 + saturation_shift), 0.0, 255.0)
    image = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32) / 255.0

    accent = np.array(accent_color[::-1], dtype=np.float32) / 255.0
    image = np.clip(image * (1.0 - accent_strength) + accent * accent_strength, 0.0, 1.0)
    return (image * 255).astype(np.uint8)


def resize_to_preview(width: int, height: int, max_width: int, max_height: int) -> tuple[int, int]:
    scale = min(max_width / width, max_height / height)
    return max(1, math.floor(width * scale)), max(1, math.floor(height * scale))


def fit_cover_frame(
    frame_rgb: np.ndarray,
    target_width: int = TARGET_WIDTH,
    target_height: int = TARGET_HEIGHT,
    *,
    interpolation: int = cv2.INTER_LANCZOS4,
) -> np.ndarray:
    """Приводит кадр к целевому вертикальному формату через cover-scale и center crop."""

    source_height, source_width = frame_rgb.shape[:2]
    scale = max(target_width / source_width, target_height / source_height)
    resized_width = max(1, int(round(source_width * scale)))
    resized_height = max(1, int(round(source_height * scale)))
    resized = cv2.resize(frame_rgb, (resized_width, resized_height), interpolation=interpolation)

    x_offset = max(0, (resized_width - target_width) // 2)
    y_offset = max(0, (resized_height - target_height) // 2)
    cropped = resized[y_offset : y_offset + target_height, x_offset : x_offset + target_width]
    return cropped.copy()
