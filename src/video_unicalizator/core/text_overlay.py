from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from video_unicalizator.config import TARGET_HEIGHT, TARGET_WIDTH
from video_unicalizator.state import TextStyle
from video_unicalizator.utils.emoji_assets import resolve_emoji_asset
from video_unicalizator.utils.image_tools import hex_to_rgba, resolve_font_path

Alignment = Literal["left", "center", "right"]


@dataclass(slots=True)
class OverlayLayout:
    width: int
    height: int


@dataclass(slots=True)
class OverlayBounds:
    left: int
    top: int
    right: int
    bottom: int

    @classmethod
    def empty(cls) -> "OverlayBounds":
        return cls(0, 0, 0, 0)

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def center_x(self) -> float:
        return self.left + self.width / 2

    @property
    def center_y(self) -> float:
        return self.top + self.height / 2


@dataclass(slots=True)
class TextRun:
    kind: str
    text: str
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont | None
    width: int
    height: int
    image: Image.Image | None = None


@dataclass(slots=True)
class TextLine:
    text: str
    runs: list[TextRun]
    width: int
    height: int


@dataclass(slots=True)
class OverlayRenderResult:
    image: Image.Image
    bounds: OverlayBounds
    text_lines: list[str]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _layout_scale(layout: OverlayLayout) -> float:
    return min(layout.width / TARGET_WIDTH, layout.height / TARGET_HEIGHT)


def _scaled(value: float | int, layout: OverlayLayout, minimum: int = 1) -> int:
    return max(minimum, int(round(float(value) * _layout_scale(layout))))


@lru_cache(maxsize=256)
def _load_font(font_name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_path = resolve_font_path(font_name)
    if font_path:
        try:
            return ImageFont.truetype(font_path, size)
        except OSError:
            pass
    try:
        return ImageFont.truetype(font_name, size)
    except OSError:
        return ImageFont.load_default()


@lru_cache(maxsize=1024)
def _load_emoji_image(asset_path: str, size: int) -> Image.Image:
    return Image.open(asset_path).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)


def _font_height(font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    try:
        ascent, descent = font.getmetrics()
        return max(1, ascent + descent)
    except (AttributeError, OSError):
        bbox = font.getbbox("Ag")
        if bbox is None:
            return 16
        return max(1, bbox[3] - bbox[1])


def _measure_text(font: ImageFont.FreeTypeFont | ImageFont.ImageFont, text: str) -> int:
    if not text:
        return 0
    bbox = font.getbbox(text)
    if bbox is None:
        return 0
    return max(0, bbox[2] - bbox[0])


def _is_emoji_codepoint(codepoint: int) -> bool:
    return (
        0x1F300 <= codepoint <= 0x1FAFF
        or 0x2600 <= codepoint <= 0x27BF
        or 0x2300 <= codepoint <= 0x23FF
        or 0x1F1E6 <= codepoint <= 0x1F1FF
    )


def _cluster_looks_emoji_like(cluster: str) -> bool:
    for character in cluster:
        codepoint = ord(character)
        if _is_emoji_codepoint(codepoint):
            return True
        if character == "\u200d" or 0xFE00 <= codepoint <= 0xFE0F or 0x1F3FB <= codepoint <= 0x1F3FF:
            return True
    return False


def _split_clusters(text: str) -> list[str]:
    clusters: list[str] = []
    current = ""

    for character in text:
        codepoint = ord(character)
        if not current:
            current = character
            continue

        if (
            character == "\u200d"
            or current.endswith("\u200d")
            or unicodedata.combining(character)
            or 0xFE00 <= codepoint <= 0xFE0F
            or 0x1F3FB <= codepoint <= 0x1F3FF
        ):
            current += character
            continue

        clusters.append(current)
        current = character

    if current:
        clusters.append(current)
    return clusters


def _dedupe_names(names: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for name in names:
        normalized = name.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _font_candidates(primary_font: str, emoji_like: bool) -> list[str]:
    if emoji_like:
        return _dedupe_names(
            [
                "Segoe UI Emoji",
                "Segoe UI Symbol",
                primary_font,
                "Segoe UI",
                "Arial",
            ]
        )
    return _dedupe_names([primary_font, "Segoe UI", "Arial"])


@lru_cache(maxsize=64)
def _font_name_available(font_name: str) -> bool:
    font_path = resolve_font_path(font_name)
    if font_path:
        return True
    try:
        ImageFont.truetype(font_name, 16)
        return True
    except OSError:
        return False


def _select_font_for_cluster(
    primary_font: str,
    font_size: int,
    cluster: str,
) -> tuple[str, ImageFont.FreeTypeFont | ImageFont.ImageFont]:
    emoji_like = _cluster_looks_emoji_like(cluster)
    for font_name in _font_candidates(primary_font, emoji_like):
        if _font_name_available(font_name):
            return font_name, _load_font(font_name, font_size)
    return primary_font, _load_font(primary_font, font_size)


def _line_units(text: str, primary_font: str, font_size: int) -> list[TextRun]:
    runs: list[TextRun] = []
    current_text = ""
    current_font_name = primary_font
    current_font = _load_font(primary_font, font_size)
    emoji_size = max(font_size, int(round(font_size * 1.05)))

    def flush_text() -> None:
        nonlocal current_text
        if not current_text:
            return
        runs.append(
            TextRun(
                kind="text",
                text=current_text,
                font=current_font,
                width=_measure_text(current_font, current_text),
                height=_font_height(current_font),
            )
        )
        current_text = ""

    for cluster in _split_clusters(text):
        asset_path = resolve_emoji_asset(cluster)
        if asset_path is not None:
            flush_text()
            emoji_image = _load_emoji_image(str(asset_path), emoji_size)
            runs.append(
                TextRun(
                    kind="emoji",
                    text=cluster,
                    font=None,
                    width=emoji_size,
                    height=emoji_size,
                    image=emoji_image,
                )
            )
            continue
        font_name, font = _select_font_for_cluster(primary_font, font_size, cluster)
        if current_text and font_name != current_font_name:
            flush_text()
        current_font_name = font_name
        current_font = font
        current_text += cluster

    flush_text()
    return runs


def _measure_line_width(text: str, primary_font: str, font_size: int) -> int:
    return sum(run.width for run in _line_units(text, primary_font, font_size))


def _break_long_token(token: str, max_width: int, primary_font: str, font_size: int) -> list[str]:
    parts: list[str] = []
    current = ""
    for cluster in _split_clusters(token):
        candidate = current + cluster
        width = _measure_line_width(candidate, primary_font, font_size)
        if current and width > max_width:
            parts.append(current)
            current = cluster
            continue
        current = candidate
    if current:
        parts.append(current)
    return parts or [token]


def _wrap_paragraph(paragraph: str, max_width: int, primary_font: str, font_size: int) -> list[str]:
    normalized = " ".join(paragraph.split())
    if not normalized:
        return [""]

    words = normalized.split(" ")
    lines: list[str] = []
    current_words: list[str] = []

    def flush_current() -> None:
        if current_words:
            lines.append(" ".join(current_words))
            current_words.clear()

    for word in words:
        if not current_words:
            if _measure_line_width(word, primary_font, font_size) <= max_width:
                current_words.append(word)
                continue

            broken = _break_long_token(word, max_width, primary_font, font_size)
            lines.extend(broken[:-1])
            current_words = [broken[-1]]
            continue

        candidate = " ".join([*current_words, word])
        if _measure_line_width(candidate, primary_font, font_size) <= max_width:
            current_words.append(word)
            continue

        flush_current()
        if _measure_line_width(word, primary_font, font_size) <= max_width:
            current_words.append(word)
            continue

        broken = _break_long_token(word, max_width, primary_font, font_size)
        lines.extend(broken[:-1])
        current_words = [broken[-1]]

    flush_current()
    return lines or [normalized]


def _wrap_text(quote: str, max_width: int, primary_font: str, font_size: int) -> list[str]:
    lines: list[str] = []
    paragraphs = quote.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for paragraph in paragraphs:
        if paragraph.strip():
            lines.extend(_wrap_paragraph(paragraph, max_width, primary_font, font_size))
        else:
            lines.append("")
    return lines or [quote]


def _build_text_lines(lines: list[str], primary_font: str, font_size: int) -> list[TextLine]:
    result: list[TextLine] = []
    fallback_height = _font_height(_load_font(primary_font, font_size))
    for line in lines:
        runs = _line_units(line, primary_font, font_size) if line else []
        line_width = sum(run.width for run in runs)
        line_height = max((run.height for run in runs), default=fallback_height)
        result.append(TextLine(text=line, runs=runs, width=line_width, height=line_height))
    return result


def _draw_text_run(
    draw: ImageDraw.ImageDraw,
    position: tuple[float, float],
    run: TextRun,
    fill: tuple[int, int, int, int],
) -> None:
    if run.kind != "text" or run.font is None:
        return
    draw.text(position, run.text, fill=fill, font=run.font)


def _paste_emoji(target: Image.Image, position: tuple[int, int], run: TextRun) -> None:
    if run.kind != "emoji" or run.image is None:
        return
    target.alpha_composite(run.image, dest=position)


class TextOverlayRenderer:
    """Единый renderer цитаты для preview и финального экспорта."""

    def __init__(self, layout: OverlayLayout, style: TextStyle, quote: str) -> None:
        self.layout = layout
        self.style = style
        self.quote = quote.strip() or style.preview_text.strip()
        self._result = self._build_overlay()
        self.overlay_image = self._result.image
        self.overlay_rgba = np.array(self.overlay_image)
        self.bounds = self._result.bounds
        self.text_lines = self._result.text_lines

    def _scaled_font_size(self) -> int:
        return _scaled(self.style.font_size, self.layout, minimum=16)

    def _scaled_padding_x(self) -> int:
        return _scaled(self.style.padding_x, self.layout, minimum=12)

    def _scaled_padding_y(self) -> int:
        return _scaled(self.style.padding_y, self.layout, minimum=10)

    def _scaled_corner_radius(self) -> int:
        return _scaled(self.style.corner_radius, self.layout, minimum=10)

    def _shadow_blur_radius(self, font_size: int) -> int:
        return max(0, int(round(font_size * (0.02 + 0.16 * self.style.shadow_strength))))

    def _shadow_offset(self, font_size: int) -> int:
        return max(0, int(round(font_size * (0.02 + 0.06 * self.style.shadow_strength))))

    def _shadow_opacity(self) -> int:
        return int(round(255 * min(0.78, 0.20 + self.style.shadow_strength * 0.58)))

    def _target_block_width(self, padding_x: int) -> int:
        requested_width = int(round(self.layout.width * self.style.box_width_ratio))
        minimum_width = max(120 + padding_x * 2, 1)
        return min(self.layout.width, max(minimum_width, requested_width))

    def _measure_quote_block(
        self,
        quote: str,
        *,
        block_width: int,
        font_size: int,
        padding_x: int,
        padding_y: int,
    ) -> tuple[list[str], list[TextLine], int, int]:
        max_text_width = max(32, block_width - padding_x * 2)
        wrapped_lines = _wrap_text(quote, max_text_width, self.style.font_name, font_size)
        text_lines = _build_text_lines(wrapped_lines, self.style.font_name, font_size)

        line_gap = max(0, int(round(font_size * max(0.0, self.style.line_spacing - 1.0))))
        text_height = 0
        for index, line in enumerate(text_lines):
            text_height += line.height
            if index < len(text_lines) - 1:
                text_height += line_gap

        block_height = min(self.layout.height, max(1, text_height + padding_y * 2))
        return wrapped_lines, text_lines, line_gap, block_height

    def _place_centered_bounds(self, block_width: int, block_height: int) -> OverlayBounds:
        center_x = _clamp(self.layout.width * self.style.position_x, block_width / 2, self.layout.width - block_width / 2)
        center_y = _clamp(
            self.layout.height * self.style.position_y,
            block_height / 2,
            self.layout.height - block_height / 2,
        )
        x1 = int(round(center_x - block_width / 2))
        y1 = int(round(center_y - block_height / 2))
        return OverlayBounds(left=x1, top=y1, right=x1 + block_width, bottom=y1 + block_height)

    def _place_bounds_from_reference(self, reference_bounds: OverlayBounds, block_width: int, block_height: int) -> OverlayBounds:
        reference_center_x = reference_bounds.center_x
        reference_center_y = reference_bounds.center_y

        if reference_center_x <= self.layout.width * 0.35:
            x1 = float(reference_bounds.left)
        elif reference_center_x >= self.layout.width * 0.65:
            x1 = float(reference_bounds.right - block_width)
        else:
            x1 = float(reference_center_x - block_width / 2)

        if reference_center_y <= self.layout.height * 0.35:
            y1 = float(reference_bounds.top)
        elif reference_center_y >= self.layout.height * 0.65:
            y1 = float(reference_bounds.bottom - block_height)
        else:
            y1 = float(reference_center_y - block_height / 2)

        x1 = _clamp(x1, 0, self.layout.width - block_width)
        y1 = _clamp(y1, 0, self.layout.height - block_height)
        return OverlayBounds(
            left=int(round(x1)),
            top=int(round(y1)),
            right=int(round(x1 + block_width)),
            bottom=int(round(y1 + block_height)),
        )

    def _build_overlay(self) -> OverlayRenderResult:
        image = Image.new("RGBA", (self.layout.width, self.layout.height), (0, 0, 0, 0))
        if not self.quote:
            return OverlayRenderResult(image=image, bounds=OverlayBounds.empty(), text_lines=[])

        font_size = self._scaled_font_size()
        padding_x = self._scaled_padding_x()
        padding_y = self._scaled_padding_y()
        block_width = self._target_block_width(padding_x)
        reference_quote = self.style.preview_text.strip() or self.quote
        _, _, _, reference_height = self._measure_quote_block(
            reference_quote,
            block_width=block_width,
            font_size=font_size,
            padding_x=padding_x,
            padding_y=padding_y,
        )
        wrapped_lines, text_lines, line_gap, block_height = self._measure_quote_block(
            self.quote,
            block_width=block_width,
            font_size=font_size,
            padding_x=padding_x,
            padding_y=padding_y,
        )

        reference_bounds = self._place_centered_bounds(block_width, reference_height)
        bounds = self._place_bounds_from_reference(reference_bounds, block_width, block_height)
        x1, y1, x2, y2 = bounds.left, bounds.top, bounds.right, bounds.bottom

        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (x1, y1, x2, y2),
            radius=min(self._scaled_corner_radius(), max(1, min(block_width, block_height) // 2)),
            fill=hex_to_rgba(self.style.background_color, self.style.background_opacity),
        )

        content_width = block_width - padding_x * 2
        line_positions: list[tuple[TextLine, int, int]] = []
        current_y = y1 + padding_y
        align = self.style.text_align if self.style.text_align in {"left", "center", "right"} else "center"
        for line in text_lines:
            if align == "left":
                line_x = x1 + padding_x
            elif align == "right":
                line_x = x1 + padding_x + max(0, content_width - line.width)
            else:
                line_x = x1 + padding_x + max(0, (content_width - line.width) / 2)
            line_positions.append((line, int(round(line_x)), current_y))
            current_y += line.height + line_gap

        self._render_shadow(image, line_positions, font_size)

        text_fill = hex_to_rgba(self.style.text_color, 1.0)
        draw = ImageDraw.Draw(image)
        for line, line_x, line_y in line_positions:
            cursor_x = line_x
            for run in line.runs:
                if run.kind == "text":
                    _draw_text_run(draw, (cursor_x, line_y), run, text_fill)
                else:
                    _paste_emoji(image, (cursor_x, line_y), run)
                cursor_x += run.width

        return OverlayRenderResult(image=image, bounds=bounds, text_lines=wrapped_lines)

    def _render_shadow(self, image: Image.Image, line_positions: list[tuple[TextLine, int, int]], font_size: int) -> None:
        if self.style.shadow_strength <= 0.0:
            return

        mask = Image.new("L", image.size, 0)
        mask_draw = ImageDraw.Draw(mask)
        for line, line_x, line_y in line_positions:
            cursor_x = line_x
            for run in line.runs:
                if run.kind == "text" and run.font is not None:
                    mask_draw.text((cursor_x, line_y), run.text, fill=255, font=run.font)
                elif run.kind == "emoji" and run.image is not None:
                    alpha = run.image.getchannel("A")
                    mask.paste(alpha, (cursor_x, line_y), alpha)
                cursor_x += run.width

        blur_radius = self._shadow_blur_radius(font_size)
        if blur_radius > 0:
            mask = mask.filter(ImageFilter.GaussianBlur(blur_radius))

        offset = self._shadow_offset(font_size)
        if offset > 0:
            mask = ImageChops.offset(mask, offset, offset)

        opacity = self._shadow_opacity()
        mask = mask.point(lambda value: int(value * (opacity / 255.0)))
        shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
        shadow.putalpha(mask)
        image.alpha_composite(shadow)

    def apply(self, frame_rgb: np.ndarray) -> np.ndarray:
        overlay = self.overlay_rgba.astype(np.float32)
        frame = frame_rgb.astype(np.float32)
        alpha = overlay[..., 3:4] / 255.0
        frame = frame * (1.0 - alpha) + overlay[..., :3] * alpha
        return np.clip(frame, 0.0, 255.0).astype(np.uint8)
