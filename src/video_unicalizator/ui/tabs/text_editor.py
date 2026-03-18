from __future__ import annotations

import tkinter as tk
from dataclasses import replace
from pathlib import Path

import customtkinter as ctk

from video_unicalizator.config import DEFAULT_VARIATIONS, MAX_VARIATIONS, MIN_VARIATIONS
from video_unicalizator.state import GenerationProgressEvent, TextStyle
from video_unicalizator.ui.widgets.color_picker import ColorPickerRow
from video_unicalizator.ui.widgets.generation_console import GenerationConsole
from video_unicalizator.ui.widgets.video_preview import VideoPreviewWidget


class TextEditorTab(ctk.CTkFrame):
    """Главный экран редактора цитаты и ресурсов."""

    def __init__(
        self,
        master,
        fonts: list[str],
        on_load_originals_files,
        on_load_originals_folder,
        on_load_music_files,
        on_load_music_folder,
        on_load_quotes_files,
        on_load_quotes_folder,
        on_choose_output_folder,
        on_apply_style,
        on_generate,
        on_video_selected,
        on_style_changed,
        on_overlay_changed,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._fonts = fonts
        self._on_apply_style = on_apply_style
        self._on_generate = on_generate
        self._on_video_selected = on_video_selected
        self._on_style_changed = on_style_changed
        self._on_overlay_changed = on_overlay_changed
        self._position = (0.5, 0.2)
        self._suspend_callbacks = False
        self._original_paths: list[Path] = []

        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0)

        self.left_panel = ctk.CTkScrollableFrame(
            self,
            width=320,
            corner_radius=18,
            fg_color="#0b1320",
            border_width=1,
            border_color="#16253c",
        )
        self.left_panel.grid(row=0, column=0, padx=(12, 8), pady=(10, 8), sticky="ns")
        self.left_panel.grid_columnconfigure(0, weight=1)

        self.preview = VideoPreviewWidget(self, on_overlay_change=self._handle_overlay_change)
        self.preview.grid(row=0, column=1, padx=8, pady=(10, 8), sticky="nsew")

        self.right_panel = ctk.CTkScrollableFrame(
            self,
            width=280,
            corner_radius=18,
            fg_color="#0b1320",
            border_width=1,
            border_color="#16253c",
        )
        self.right_panel.grid(row=0, column=2, padx=(8, 12), pady=(10, 8), sticky="ns")
        self.right_panel.grid_columnconfigure(0, weight=1)

        self.generation_console = GenerationConsole(
            self,
            title="Статус генерации",
            compact=True,
            start_collapsed=True,
        )
        self.generation_console.grid(row=1, column=0, columnspan=3, padx=12, pady=(0, 12), sticky="ew")

        self._build_left_panel(
            on_load_originals_files,
            on_load_originals_folder,
            on_load_music_files,
            on_load_music_folder,
            on_load_quotes_files,
            on_load_quotes_folder,
            on_choose_output_folder,
        )
        self._build_right_panel()
        self.load_style(TextStyle())

    def _section_title(self, parent, row: int, title: str, subtitle: str | None = None) -> int:
        label = ctk.CTkLabel(
            parent,
            text=title,
            font=ctk.CTkFont(family="Bahnschrift", size=17, weight="bold"),
            text_color="#f8fafc",
        )
        label.grid(row=row, column=0, padx=14, pady=(14, 4), sticky="w")
        row += 1
        if subtitle:
            hint = ctk.CTkLabel(
                parent,
                text=subtitle,
                text_color="#8ea2c0",
                wraplength=285,
                justify="left",
            )
            hint.grid(row=row, column=0, padx=14, pady=(0, 8), sticky="w")
            row += 1
        return row

    def _resource_row(
        self,
        parent,
        row: int,
        title: str,
        on_pick_files,
        on_pick_folder,
        files_text: str,
        folder_text: str,
        accent_color: str,
    ) -> int:
        row_frame = ctk.CTkFrame(parent, fg_color="#0f1b31", corner_radius=14)
        row_frame.grid(row=row, column=0, padx=14, pady=(0, 8), sticky="ew")
        row_frame.grid_columnconfigure(0, weight=1)
        row_frame.grid_columnconfigure(1, weight=1)

        title_label = ctk.CTkLabel(
            row_frame,
            text=title,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color="#f8fafc",
        )
        title_label.grid(row=0, column=0, columnspan=2, padx=10, pady=(8, 6), sticky="w")

        files_button = ctk.CTkButton(
            row_frame,
            text=files_text,
            command=on_pick_files,
            height=34,
            corner_radius=12,
            fg_color=accent_color,
            hover_color=accent_color,
        )
        files_button.grid(row=1, column=0, padx=(10, 5), pady=(0, 10), sticky="ew")

        folder_button = ctk.CTkButton(
            row_frame,
            text=folder_text,
            command=on_pick_folder,
            height=34,
            corner_radius=12,
            fg_color="#1f2937",
            hover_color="#334155",
        )
        folder_button.grid(row=1, column=1, padx=(5, 10), pady=(0, 10), sticky="ew")

        if title == "Оригиналы":
            self.originals_files_button = files_button
            self.originals_folder_button = folder_button
        elif title == "Музыка":
            self.music_files_button = files_button
            self.music_folder_button = folder_button
        else:
            self.quotes_files_button = files_button
            self.quotes_folder_button = folder_button
        return row + 1

    def _build_left_panel(
        self,
        on_load_originals_files,
        on_load_originals_folder,
        on_load_music_files,
        on_load_music_folder,
        on_load_quotes_files,
        on_load_quotes_folder,
        on_choose_output_folder,
    ) -> None:
        row = 0
        row = self._section_title(
            self.left_panel,
            row,
            "Ресурсы",
            "Можно загружать по файлам или целыми папками. txt с цитатами необязателен.",
        )

        row = self._resource_row(
            self.left_panel,
            row,
            "Оригиналы",
            on_load_originals_files,
            on_load_originals_folder,
            "Выбрать mp4",
            "Папка",
            "#2563eb",
        )
        row = self._resource_row(
            self.left_panel,
            row,
            "Музыка",
            on_load_music_files,
            on_load_music_folder,
            "Выбрать mp3",
            "Папка",
            "#0f766e",
        )
        row = self._resource_row(
            self.left_panel,
            row,
            "Цитаты",
            on_load_quotes_files,
            on_load_quotes_folder,
            "Выбрать txt",
            "Папка",
            "#7c3aed",
        )

        self.output_button = ctk.CTkButton(
            self.left_panel,
            text="Папка вывода",
            command=on_choose_output_folder,
            height=36,
            corner_radius=12,
            fg_color="#16253c",
            hover_color="#1d3557",
        )
        self.output_button.grid(row=row, column=0, padx=14, pady=(4, 4), sticky="ew")
        row += 1

        self.output_label = ctk.CTkLabel(
            self.left_panel,
            text="output\\variations",
            text_color="#cbd5e1",
            justify="left",
            wraplength=285,
        )
        self.output_label.grid(row=row, column=0, padx=14, pady=(0, 10), sticky="w")
        row += 1

        row = self._section_title(
            self.left_panel,
            row,
            "Цитата для макета",
            "Если txt не выбран, эта цитата пойдёт в генерацию. Если поле пустое, ролики будут без текста.",
        )
        self.sample_quote_box = ctk.CTkTextbox(
            self.left_panel,
            height=90,
            corner_radius=14,
            fg_color="#09111f",
            border_width=1,
            border_color="#16253c",
            wrap="word",
            font=ctk.CTkFont(family="Segoe UI", size=13),
        )
        self.sample_quote_box.grid(row=row, column=0, padx=14, pady=(0, 10), sticky="ew")
        self.sample_quote_box.bind("<KeyRelease>", lambda _event: self._emit_style_change())
        row += 1

        self.font_combo = ctk.CTkComboBox(
            self.left_panel,
            values=self._fonts,
            height=34,
            corner_radius=12,
            command=lambda _value: self._emit_style_change(),
        )
        self.font_combo.grid(row=row, column=0, padx=14, pady=(0, 10), sticky="ew")
        row += 1

        self.font_size_label = ctk.CTkLabel(self.left_panel, text="Размер: 64 px", text_color="#dbe4f0")
        self.font_size_label.grid(row=row, column=0, padx=14, pady=(0, 4), sticky="w")
        row += 1
        self.font_size_slider = ctk.CTkSlider(
            self.left_panel,
            from_=28,
            to=128,
            number_of_steps=100,
            command=self._on_font_size_changed,
            progress_color="#f97316",
        )
        self.font_size_slider.grid(row=row, column=0, padx=14, pady=(0, 8), sticky="ew")
        row += 1

        self.box_width_label = ctk.CTkLabel(self.left_panel, text="Ширина блока: 72%", text_color="#dbe4f0")
        self.box_width_label.grid(row=row, column=0, padx=14, pady=(0, 4), sticky="w")
        row += 1
        self.box_width_slider = ctk.CTkSlider(
            self.left_panel,
            from_=0.30,
            to=0.90,
            number_of_steps=60,
            command=self._on_box_width_changed,
            progress_color="#38bdf8",
        )
        self.box_width_slider.grid(row=row, column=0, padx=14, pady=(0, 8), sticky="ew")
        row += 1

        self.text_color_picker = ColorPickerRow(
            self.left_panel,
            title="Цвет текста",
            initial_color="#FFFFFF",
            on_change=lambda _value: self._emit_style_change(),
        )
        self.text_color_picker.grid(row=row, column=0, padx=14, pady=(0, 4), sticky="ew")
        row += 1

        self.bg_color_picker = ColorPickerRow(
            self.left_panel,
            title="Фон цитаты",
            initial_color="#101010",
            on_change=lambda _value: self._emit_style_change(),
        )
        self.bg_color_picker.grid(row=row, column=0, padx=14, pady=(0, 4), sticky="ew")
        row += 1

        self.bg_opacity_label = ctk.CTkLabel(self.left_panel, text="Прозрачность: 45%", text_color="#dbe4f0")
        self.bg_opacity_label.grid(row=row, column=0, padx=14, pady=(0, 4), sticky="w")
        row += 1
        self.bg_opacity_slider = ctk.CTkSlider(
            self.left_panel,
            from_=0.0,
            to=1.0,
            number_of_steps=100,
            command=self._on_bg_opacity_changed,
            progress_color="#06b6d4",
        )
        self.bg_opacity_slider.grid(row=row, column=0, padx=14, pady=(0, 8), sticky="ew")
        row += 1

        self.corner_radius_label = ctk.CTkLabel(self.left_panel, text="Скругление: 36 px", text_color="#dbe4f0")
        self.corner_radius_label.grid(row=row, column=0, padx=14, pady=(0, 4), sticky="w")
        row += 1
        self.corner_radius_slider = ctk.CTkSlider(
            self.left_panel,
            from_=8,
            to=92,
            number_of_steps=84,
            command=self._on_corner_radius_changed,
            progress_color="#a78bfa",
        )
        self.corner_radius_slider.grid(row=row, column=0, padx=14, pady=(0, 8), sticky="ew")
        row += 1

        self.shadow_label = ctk.CTkLabel(self.left_panel, text="Тень: 45%", text_color="#dbe4f0")
        self.shadow_label.grid(row=row, column=0, padx=14, pady=(0, 4), sticky="w")
        row += 1
        self.shadow_slider = ctk.CTkSlider(
            self.left_panel,
            from_=0.0,
            to=1.0,
            number_of_steps=100,
            command=self._on_shadow_changed,
            progress_color="#f59e0b",
        )
        self.shadow_slider.grid(row=row, column=0, padx=14, pady=(0, 8), sticky="ew")
        row += 1

        self.variation_label = ctk.CTkLabel(
            self.left_panel,
            text=f"Вариаций на оригинал: {DEFAULT_VARIATIONS}",
            text_color="#dbe4f0",
        )
        self.variation_label.grid(row=row, column=0, padx=14, pady=(0, 4), sticky="w")
        row += 1
        self.variation_slider = ctk.CTkSlider(
            self.left_panel,
            from_=MIN_VARIATIONS,
            to=MAX_VARIATIONS,
            number_of_steps=MAX_VARIATIONS - MIN_VARIATIONS,
            command=self._on_variation_changed,
            progress_color="#ec4899",
        )
        self.variation_slider.grid(row=row, column=0, padx=14, pady=(0, 12), sticky="ew")
        row += 1

        buttons = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        buttons.grid(row=row, column=0, padx=14, pady=(0, 14), sticky="ew")
        buttons.grid_columnconfigure((0, 1), weight=1)

        self.apply_button = ctk.CTkButton(
            buttons,
            text="Применить ко всем",
            command=self._on_apply_style,
            height=38,
            corner_radius=12,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
        )
        self.apply_button.grid(row=0, column=0, padx=(0, 5), sticky="ew")

        self.generate_button = ctk.CTkButton(
            buttons,
            text="Начать генерацию",
            command=self._on_generate,
            height=38,
            corner_radius=12,
            fg_color="#f97316",
            hover_color="#ea580c",
        )
        self.generate_button.grid(row=0, column=1, padx=(5, 0), sticky="ew")

    def _build_right_panel(self) -> None:
        row = 0
        row = self._section_title(
            self.right_panel,
            row,
            "Состояние проекта",
            "Справа только служебная информация и подсказка по txt.",
        )

        self.ffmpeg_label = ctk.CTkLabel(
            self.right_panel,
            text="FFmpeg: проверка...",
            text_color="#f8fafc",
            wraplength=235,
            justify="left",
        )
        self.ffmpeg_label.grid(row=row, column=0, padx=14, pady=(0, 8), sticky="ew")
        row += 1

        self.media_summary = ctk.CTkLabel(
            self.right_panel,
            text="Оригиналы: 0\nМузыка: 0\nЦитаты: 0",
            justify="left",
            anchor="w",
            text_color="#cbd5e1",
        )
        self.media_summary.grid(row=row, column=0, padx=14, pady=(0, 12), sticky="ew")
        row += 1

        helper_card = ctk.CTkFrame(
            self.right_panel,
            corner_radius=14,
            fg_color="#0f1b31",
            border_width=1,
            border_color="#16253c",
        )
        helper_card.grid(row=row, column=0, padx=14, pady=(0, 12), sticky="ew")
        helper_card.grid_columnconfigure(0, weight=1)

        helper_title = ctk.CTkLabel(
            helper_card,
            text="Как писать txt",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color="#f8fafc",
        )
        helper_title.grid(row=0, column=0, padx=12, pady=(10, 6), sticky="w")

        helper_text = ctk.CTkLabel(
            helper_card,
            text=(
                "txt опционален.\n\n"
                "Если txt загружен:\n"
                "одна цитата = один блок текста,\n"
                "блоки разделяются пустой строкой.\n\n"
                "Если txt не загружен:\n"
                "будет использован текст из макета.\n\n"
                "Пустой макет = генерация без текста."
            ),
            justify="left",
            anchor="w",
            text_color="#cbd5e1",
            wraplength=225,
        )
        helper_text.grid(row=1, column=0, padx=12, pady=(0, 10), sticky="ew")
        row += 1

        self.list_title = ctk.CTkLabel(
            self.right_panel,
            text="Оригиналы для превью",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color="#f8fafc",
        )
        self.list_title.grid(row=row, column=0, padx=14, pady=(0, 6), sticky="w")
        row += 1

        self.listbox = tk.Listbox(
            self.right_panel,
            bg="#09111f",
            fg="#e2e8f0",
            selectbackground="#2563eb",
            activestyle="none",
            borderwidth=0,
            highlightthickness=0,
            font=("Segoe UI", 11),
            height=12,
        )
        self.listbox.grid(row=row, column=0, padx=14, pady=(0, 12), sticky="ew")
        self.listbox.bind("<<ListboxSelect>>", self._handle_video_selected)

    def _on_font_size_changed(self, value: float) -> None:
        self.font_size_label.configure(text=f"Размер: {int(round(value))} px")
        self._emit_style_change()

    def _on_box_width_changed(self, value: float) -> None:
        self.box_width_label.configure(text=f"Ширина блока: {int(round(value * 100))}%")
        self._emit_style_change()

    def _on_bg_opacity_changed(self, value: float) -> None:
        self.bg_opacity_label.configure(text=f"Прозрачность: {int(round(value * 100))}%")
        self._emit_style_change()

    def _on_corner_radius_changed(self, value: float) -> None:
        self.corner_radius_label.configure(text=f"Скругление: {int(round(value))} px")
        self._emit_style_change()

    def _on_shadow_changed(self, value: float) -> None:
        self.shadow_label.configure(text=f"Тень: {int(round(value * 100))}%")
        self._emit_style_change()

    def _on_variation_changed(self, value: float) -> None:
        self.variation_label.configure(text=f"Вариаций на оригинал: {int(round(value))}")
        self._emit_style_change()

    def _handle_video_selected(self, _event=None) -> None:
        selection = self.listbox.curselection()
        if not selection:
            return
        self._on_video_selected(self._original_paths[selection[0]])

    def _handle_overlay_change(self, style: TextStyle) -> None:
        self._position = (style.position_x, style.position_y)
        self._sync_controls_from_overlay(style)
        self._on_overlay_changed(style)

    def _sync_controls_from_overlay(self, style: TextStyle) -> None:
        self._suspend_callbacks = True
        self.font_size_slider.set(style.font_size)
        self.box_width_slider.set(style.box_width_ratio)
        self.corner_radius_slider.set(style.corner_radius)
        self._on_font_size_changed(style.font_size)
        self._on_box_width_changed(style.box_width_ratio)
        self._on_corner_radius_changed(style.corner_radius)
        self._suspend_callbacks = False

    def _emit_style_change(self) -> None:
        if self._suspend_callbacks:
            return
        self._on_style_changed(self.read_text_style(), self.read_variation_count())

    def load_style(self, style: TextStyle) -> None:
        self._suspend_callbacks = True
        self._position = (style.position_x, style.position_y)
        self.sample_quote_box.delete("1.0", "end")
        self.sample_quote_box.insert("1.0", style.preview_text)
        self.font_combo.set(style.font_name if style.font_name in self._fonts else self._fonts[0])
        self.font_size_slider.set(style.font_size)
        self.box_width_slider.set(style.box_width_ratio)
        self.bg_opacity_slider.set(style.background_opacity)
        self.corner_radius_slider.set(style.corner_radius)
        self.shadow_slider.set(style.shadow_strength)
        self.variation_slider.set(DEFAULT_VARIATIONS)
        self.text_color_picker.set_value(style.text_color)
        self.bg_color_picker.set_value(style.background_color)
        self._on_font_size_changed(style.font_size)
        self._on_box_width_changed(style.box_width_ratio)
        self._on_bg_opacity_changed(style.background_opacity)
        self._on_corner_radius_changed(style.corner_radius)
        self._on_shadow_changed(style.shadow_strength)
        self._on_variation_changed(DEFAULT_VARIATIONS)
        self.preview.update_style(style)
        self.preview.update_preview_text(style.preview_text)
        self._suspend_callbacks = False

    def _sample_quote(self) -> str:
        return self.sample_quote_box.get("1.0", "end-1c").strip()

    def read_text_style(self) -> TextStyle:
        font_size = int(round(self.font_size_slider.get()))
        return TextStyle(
            text_color=self.text_color_picker.get_value(),
            background_color=self.bg_color_picker.get_value(),
            background_opacity=float(self.bg_opacity_slider.get()),
            shadow_strength=float(self.shadow_slider.get()),
            font_size=font_size,
            font_name=self.font_combo.get(),
            preview_text=self._sample_quote(),
            position_x=self._position[0],
            position_y=self._position[1],
            box_width_ratio=float(self.box_width_slider.get()),
            line_spacing=1.18,
            padding_x=max(18, int(round(font_size * 0.55))),
            padding_y=max(12, int(round(font_size * 0.35))),
            corner_radius=int(round(self.corner_radius_slider.get())),
            text_align="center",
        )

    def read_variation_count(self) -> int:
        return int(round(self.variation_slider.get()))

    def update_preview_style(self, style: TextStyle) -> None:
        style = replace(style, preview_text=self._sample_quote())
        self.preview.update_style(style)
        self.preview.update_preview_text(style.preview_text)

    def set_quote_sample(self, quote: str) -> None:
        self._suspend_callbacks = True
        self.sample_quote_box.delete("1.0", "end")
        self.sample_quote_box.insert("1.0", quote)
        self._suspend_callbacks = False
        self._emit_style_change()

    def set_originals(self, paths: list[Path]) -> None:
        self._original_paths = list(paths)
        self.listbox.delete(0, "end")
        for path in paths:
            self.listbox.insert("end", path.name)
        if paths:
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(0)
            self.listbox.activate(0)

    def set_media_summary(self, originals_count: int, music_count: int, quotes_count: int) -> None:
        self.media_summary.configure(
            text=f"Оригиналы: {originals_count}\nМузыка: {music_count}\nЦитаты: {quotes_count}"
        )

    def set_ffmpeg_status(self, status_text: str, available: bool) -> None:
        color = "#22c55e" if available else "#f97316"
        self.ffmpeg_label.configure(text=f"FFmpeg: {status_text}", text_color=color)

    def set_output_directory(self, path: Path) -> None:
        self.output_label.configure(text=str(path))

    def clear_generation_console(self) -> None:
        self.generation_console.clear()

    def set_generation_console_expanded(self, expanded: bool) -> None:
        self.generation_console.set_expanded(expanded)

    def push_generation_event(self, event: GenerationProgressEvent) -> None:
        if event.stage not in {"Ожидание"}:
            self.generation_console.set_expanded(True)
        self.generation_console.push_event(event)
        if event.stage in {"Рендер", "Проверка качества", "Экспорт расписания"}:
            self.preview.set_runtime_status(event.message)
        elif event.stage in {"Готово", "Ошибка", "Ожидание"}:
            self.preview.set_runtime_status(None)

    def set_generation_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in (
            self.originals_files_button,
            self.originals_folder_button,
            self.music_files_button,
            self.music_folder_button,
            self.quotes_files_button,
            self.quotes_folder_button,
            self.output_button,
            self.apply_button,
            self.generate_button,
            self.font_combo,
            self.sample_quote_box,
            self.font_size_slider,
            self.box_width_slider,
            self.bg_opacity_slider,
            self.corner_radius_slider,
            self.shadow_slider,
            self.variation_slider,
        ):
            widget.configure(state=state)
        self.text_color_picker.set_enabled(enabled)
        self.bg_color_picker.set_enabled(enabled)
        self.preview.set_interaction_enabled(enabled)
