from __future__ import annotations

import tkinter as tk
from dataclasses import replace

from PIL import ImageTk

from video_unicalizator.config import TARGET_HEIGHT, TARGET_WIDTH
from video_unicalizator.core.text_overlay import OverlayBounds, OverlayLayout, TextOverlayRenderer
from video_unicalizator.state import TextStyle


class DraggableTextOverlay:
    """WYSIWYG-оверлей цитаты для preview без тяжёлого full-rerender на каждый drag."""

    HANDLE_SIZE = 11
    MIN_BOX_RATIO = 0.18
    MAX_BOX_RATIO = 0.94
    MIN_FONT_SIZE = 18
    MAX_FONT_SIZE = 180
    RESIZE_DEBOUNCE_MS = 110

    def __init__(self, canvas: tk.Canvas, on_change) -> None:
        self.canvas = canvas
        self.on_change = on_change
        self.style = TextStyle()
        self.preview_text = self.style.preview_text

        self._video_size = (TARGET_WIDTH, TARGET_HEIGHT)
        self._viewport = (0, 0, 1, 1)

        self._overlay_bounds_video = OverlayBounds.empty()
        self._overlay_bounds_local = OverlayBounds.empty()
        self._proxy_bounds_local = OverlayBounds.empty()

        self._image_item: int | None = None
        self._selection_item: int | None = None
        self._handle_items: dict[str, int] = {}
        self._display_photo: ImageTk.PhotoImage | None = None
        self._preview_crop = None
        self._last_image_signature: tuple | None = None
        self._debounce_after_id: str | None = None

        self._active_mode: str | None = None
        self._start_style = replace(self.style)
        self._start_bounds_video = OverlayBounds.empty()
        self._start_bounds_local = OverlayBounds.empty()
        self._start_pointer_video = (0.0, 0.0)

    def update_scene(self, style: TextStyle, preview_text: str, viewport: tuple[int, int, int, int]) -> None:
        self.style = replace(style)
        self.preview_text = preview_text
        self._viewport = viewport
        if self._active_mode is None:
            self._render(force=False)

    def set_viewport(self, viewport: tuple[int, int, int, int]) -> None:
        self._viewport = viewport
        self._render(force=True)

    def has_overlay(self) -> bool:
        return bool((self.preview_text or self.style.preview_text).strip())

    def is_interacting(self) -> bool:
        return self._active_mode is not None

    def contains_canvas_point(self, canvas_x: int, canvas_y: int) -> bool:
        handle = self._handle_hit_test(canvas_x, canvas_y)
        if handle:
            return True
        bounds = self._current_canvas_bounds()
        return bounds.left <= canvas_x <= bounds.right and bounds.top <= canvas_y <= bounds.bottom

    def start_interaction(self, canvas_x: int, canvas_y: int) -> bool:
        if not self.has_overlay():
            self._active_mode = None
            return False

        handle = self._handle_hit_test(canvas_x, canvas_y)
        if handle:
            self._active_mode = handle
        elif self.contains_canvas_point(canvas_x, canvas_y):
            self._active_mode = "move"
        else:
            self._active_mode = None
            return False

        self._cancel_scheduled_render()
        self._start_style = replace(self.style)
        self._start_bounds_video = self._overlay_bounds_video
        self._start_bounds_local = self._overlay_bounds_local
        self._proxy_bounds_local = self._overlay_bounds_local
        self._start_pointer_video = self._canvas_to_video(canvas_x, canvas_y)
        return True

    def drag_to(self, canvas_x: int, canvas_y: int) -> bool:
        if self._active_mode is None:
            return False

        video_x, video_y = self._canvas_to_video(canvas_x, canvas_y)
        start_x, start_y = self._start_pointer_video
        delta_x = video_x - start_x
        delta_y = video_y - start_y
        video_width, video_height = self._video_size

        if self._active_mode == "move":
            center_x = self._start_bounds_video.center_x + delta_x
            center_y = self._start_bounds_video.center_y + delta_y
            self.style.position_x = max(0.0, min(1.0, center_x / video_width))
            self.style.position_y = max(0.0, min(1.0, center_y / video_height))
            self._apply_geometry_only()
            return True

        left = float(self._start_bounds_video.left)
        right = float(self._start_bounds_video.right)
        top = float(self._start_bounds_video.top)
        bottom = float(self._start_bounds_video.bottom)
        min_width = max(120.0, video_width * self.MIN_BOX_RATIO)
        min_height = 64.0

        if self._active_mode in {"e", "ne", "se"}:
            right = max(left + min_width, min(video_width, video_x))
        if self._active_mode in {"w", "nw", "sw"}:
            left = min(right - min_width, max(0.0, video_x))
        if self._active_mode in {"nw", "ne"}:
            top = min(bottom - min_height, max(0.0, video_y))
        if self._active_mode in {"sw", "se"}:
            bottom = max(top + min_height, min(video_height, video_y))

        target_width = max(min_width, right - left)
        target_center_x = left + target_width / 2.0
        self.style.box_width_ratio = max(self.MIN_BOX_RATIO, min(self.MAX_BOX_RATIO, target_width / video_width))
        self.style.position_x = max(0.0, min(1.0, target_center_x / video_width))

        if self._active_mode in {"nw", "ne", "sw", "se"}:
            target_height = max(min_height, bottom - top)
            scale_factor = target_height / max(1.0, self._start_bounds_video.height)
            self.style.font_size = max(
                self.MIN_FONT_SIZE,
                min(self.MAX_FONT_SIZE, int(round(self._start_style.font_size * scale_factor))),
            )
            self.style.position_y = max(0.0, min(1.0, ((top + bottom) / 2.0) / video_height))

        self._proxy_bounds_local = self._video_bounds_to_local(
            OverlayBounds(int(round(left)), int(round(top)), int(round(right)), int(round(bottom)))
        )
        self._update_selection_items(self._proxy_bounds_local)
        self._schedule_render()
        return True

    def finish_interaction(self) -> None:
        if self._active_mode is not None:
            self._cancel_scheduled_render()
            self._render(force=True)
            self.on_change(replace(self.style))
        self._active_mode = None

    def lift(self) -> None:
        if self._image_item is not None:
            self.canvas.tag_raise(self._image_item)
        if self._selection_item is not None:
            self.canvas.tag_raise(self._selection_item)
        for item in self._handle_items.values():
            self.canvas.tag_raise(item)

    def _schedule_render(self) -> None:
        self._cancel_scheduled_render()
        self._debounce_after_id = self.canvas.after(self.RESIZE_DEBOUNCE_MS, lambda: self._render(force=True))

    def _cancel_scheduled_render(self) -> None:
        if self._debounce_after_id is not None:
            self.canvas.after_cancel(self._debounce_after_id)
            self._debounce_after_id = None

    def _render(self, force: bool) -> None:
        self._debounce_after_id = None
        viewport_x, viewport_y, viewport_width, viewport_height = self._viewport
        if viewport_width <= 1 or viewport_height <= 1:
            return

        image_signature = (
            viewport_width,
            viewport_height,
            self.preview_text,
            self.style.text_color,
            self.style.background_color,
            self.style.background_opacity,
            self.style.shadow_strength,
            self.style.font_size,
            self.style.font_name,
            self.style.box_width_ratio,
            self.style.line_spacing,
            self.style.padding_x,
            self.style.padding_y,
            self.style.corner_radius,
            self.style.text_align,
        )

        if not self.has_overlay():
            self._overlay_bounds_video = OverlayBounds.empty()
            self._overlay_bounds_local = OverlayBounds.empty()
            self._proxy_bounds_local = OverlayBounds.empty()
            self._hide_items()
            self._last_image_signature = image_signature
            return

        if force or image_signature != self._last_image_signature or self._display_photo is None:
            renderer = TextOverlayRenderer(
                OverlayLayout(width=viewport_width, height=viewport_height),
                replace(self.style, preview_text=self.preview_text),
                self.preview_text,
            )
            self._overlay_bounds_local = renderer.bounds
            self._proxy_bounds_local = renderer.bounds
            self._overlay_bounds_video = self._local_bounds_to_video(renderer.bounds)

            crop_box = (
                renderer.bounds.left,
                renderer.bounds.top,
                max(renderer.bounds.left + 1, renderer.bounds.right),
                max(renderer.bounds.top + 1, renderer.bounds.bottom),
            )
            self._preview_crop = renderer.overlay_image.crop(crop_box)
            self._display_photo = ImageTk.PhotoImage(self._preview_crop)
            self._last_image_signature = image_signature

            global_bounds = self._local_to_canvas(renderer.bounds)
            if self._image_item is None:
                self._image_item = self.canvas.create_image(
                    global_bounds.left,
                    global_bounds.top,
                    anchor="nw",
                    image=self._display_photo,
                )
            else:
                self.canvas.itemconfigure(self._image_item, image=self._display_photo, state="normal")
                self.canvas.coords(self._image_item, global_bounds.left, global_bounds.top)
        else:
            self._apply_geometry_only()

        self._ensure_selection_items()
        self._update_selection_items(self._overlay_bounds_local)
        self.lift()

    def _apply_geometry_only(self) -> None:
        if self._display_photo is None or self._image_item is None:
            return

        viewport_width = max(1, self._viewport[2])
        viewport_height = max(1, self._viewport[3])
        width = self._overlay_bounds_local.width
        height = self._overlay_bounds_local.height
        center_x = max(width / 2, min(viewport_width - width / 2, viewport_width * self.style.position_x))
        center_y = max(height / 2, min(viewport_height - height / 2, viewport_height * self.style.position_y))

        local_bounds = OverlayBounds(
            left=int(round(center_x - width / 2)),
            top=int(round(center_y - height / 2)),
            right=int(round(center_x + width / 2)),
            bottom=int(round(center_y + height / 2)),
        )
        self._overlay_bounds_local = local_bounds
        self._proxy_bounds_local = local_bounds
        self._overlay_bounds_video = self._local_bounds_to_video(local_bounds)

        global_bounds = self._local_to_canvas(local_bounds)
        self.canvas.itemconfigure(self._image_item, state="normal")
        self.canvas.coords(self._image_item, global_bounds.left, global_bounds.top)
        self._update_selection_items(local_bounds)

    def _hide_items(self) -> None:
        for item in [self._image_item, self._selection_item, *self._handle_items.values()]:
            if item is not None:
                self.canvas.itemconfigure(item, state="hidden")

    def _ensure_selection_items(self) -> None:
        if self._selection_item is None:
            self._selection_item = self.canvas.create_rectangle(
                0,
                0,
                1,
                1,
                outline="#60a5fa",
                width=2,
                dash=(6, 3),
            )
        self.canvas.itemconfigure(self._selection_item, state="normal")

        if self._handle_items:
            for item in self._handle_items.values():
                self.canvas.itemconfigure(item, state="normal")
            return

        for handle_name in ("nw", "ne", "sw", "se", "w", "e"):
            self._handle_items[handle_name] = self.canvas.create_oval(
                0,
                0,
                1,
                1,
                fill="#f8fafc",
                outline="#2563eb",
                width=2,
            )

    def _current_canvas_bounds(self) -> OverlayBounds:
        return self._local_to_canvas(self._proxy_bounds_local if self._active_mode else self._overlay_bounds_local)

    def _update_selection_items(self, local_bounds: OverlayBounds) -> None:
        if self._selection_item is None:
            return

        bounds = self._local_to_canvas(local_bounds)
        self.canvas.itemconfigure(self._selection_item, state="normal")
        self.canvas.coords(self._selection_item, bounds.left, bounds.top, bounds.right, bounds.bottom)

        half = self.HANDLE_SIZE / 2
        positions = {
            "nw": (bounds.left, bounds.top),
            "ne": (bounds.right, bounds.top),
            "sw": (bounds.left, bounds.bottom),
            "se": (bounds.right, bounds.bottom),
            "w": (bounds.left, bounds.center_y),
            "e": (bounds.right, bounds.center_y),
        }
        for handle_name, item in self._handle_items.items():
            center_x, center_y = positions[handle_name]
            self.canvas.itemconfigure(item, state="normal")
            self.canvas.coords(item, center_x - half, center_y - half, center_x + half, center_y + half)

    def _handle_hit_test(self, canvas_x: int, canvas_y: int) -> str | None:
        bounds = self._current_canvas_bounds()
        radius = self.HANDLE_SIZE
        positions = {
            "nw": (bounds.left, bounds.top),
            "ne": (bounds.right, bounds.top),
            "sw": (bounds.left, bounds.bottom),
            "se": (bounds.right, bounds.bottom),
            "w": (bounds.left, bounds.center_y),
            "e": (bounds.right, bounds.center_y),
        }
        for handle_name, (center_x, center_y) in positions.items():
            if abs(canvas_x - center_x) <= radius and abs(canvas_y - center_y) <= radius:
                return handle_name
        return None

    def _local_to_canvas(self, bounds: OverlayBounds) -> OverlayBounds:
        viewport_x, viewport_y, _, _ = self._viewport
        return OverlayBounds(
            left=viewport_x + bounds.left,
            top=viewport_y + bounds.top,
            right=viewport_x + bounds.right,
            bottom=viewport_y + bounds.bottom,
        )

    def _local_bounds_to_video(self, bounds: OverlayBounds) -> OverlayBounds:
        viewport_width = max(1, self._viewport[2])
        viewport_height = max(1, self._viewport[3])
        return OverlayBounds(
            left=int(round(bounds.left / viewport_width * TARGET_WIDTH)),
            top=int(round(bounds.top / viewport_height * TARGET_HEIGHT)),
            right=int(round(bounds.right / viewport_width * TARGET_WIDTH)),
            bottom=int(round(bounds.bottom / viewport_height * TARGET_HEIGHT)),
        )

    def _video_bounds_to_local(self, bounds: OverlayBounds) -> OverlayBounds:
        viewport_width = max(1, self._viewport[2])
        viewport_height = max(1, self._viewport[3])
        return OverlayBounds(
            left=int(round(bounds.left / TARGET_WIDTH * viewport_width)),
            top=int(round(bounds.top / TARGET_HEIGHT * viewport_height)),
            right=int(round(bounds.right / TARGET_WIDTH * viewport_width)),
            bottom=int(round(bounds.bottom / TARGET_HEIGHT * viewport_height)),
        )

    def _canvas_to_video(self, canvas_x: int, canvas_y: int) -> tuple[float, float]:
        viewport_x, viewport_y, viewport_width, viewport_height = self._viewport
        video_width, video_height = self._video_size
        x_ratio = (canvas_x - viewport_x) / max(1, viewport_width)
        y_ratio = (canvas_y - viewport_y) / max(1, viewport_height)
        x_ratio = max(0.0, min(1.0, x_ratio))
        y_ratio = max(0.0, min(1.0, y_ratio))
        return x_ratio * video_width, y_ratio * video_height
