from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import customtkinter as ctk

from video_unicalizator.config import DEFAULT_VARIATIONS, MAX_VARIATIONS, MIN_VARIATIONS
from video_unicalizator.state import GenerationProgressEvent, TextStyle, VideoEditProfile
from video_unicalizator.ui.widgets.color_picker import ColorPickerRow
from video_unicalizator.ui.widgets.generation_console import GenerationConsole
from video_unicalizator.ui.widgets.video_preview import VideoPreviewWidget

LayerKey = Literal["A", "B"]


@dataclass(slots=True)
class LayerSectionControls:
    key: LayerKey
    frame: ctk.CTkFrame
    title_label: ctk.CTkLabel
    enabled_switch: ctk.CTkSwitch
    sample_quote_box: ctk.CTkTextbox
    font_combo: ctk.CTkComboBox
    font_size_label: ctk.CTkLabel
    font_size_slider: ctk.CTkSlider
    box_width_label: ctk.CTkLabel
    box_width_slider: ctk.CTkSlider
    text_color_picker: ColorPickerRow
    bg_color_picker: ColorPickerRow
    bg_opacity_label: ctk.CTkLabel
    bg_opacity_slider: ctk.CTkSlider
    corner_radius_label: ctk.CTkLabel
    corner_radius_slider: ctk.CTkSlider
    shadow_label: ctk.CTkLabel
    shadow_slider: ctk.CTkSlider


class TextEditorTab(ctk.CTkFrame):
    """Главный экран редактора ресурсов, двух цитат и per-video макетов."""

    def __init__(
        self,
        master,
        fonts: list[str],
        on_load_originals_files,
        on_load_originals_folder,
        on_load_music_files,
        on_load_music_folder,
        on_load_quotes_a_files,
        on_load_quotes_a_folder,
        on_load_quotes_b_files,
        on_load_quotes_b_folder,
        on_choose_output_folder,
        on_apply_style,
        on_generate,
        on_video_selected,
        on_profile_changed,
        on_overlay_changed,
        on_stop_generation=None,
        on_remove_original=None,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._fonts = fonts or ["Arial"]
        self._on_apply_style = on_apply_style
        self._on_generate = on_generate
        self._on_stop_generation = on_stop_generation or (lambda: None)
        self._on_remove_original = on_remove_original or (lambda: None)
        self._on_video_selected = on_video_selected
        self._on_profile_changed = on_profile_changed
        self._on_overlay_changed = on_overlay_changed
        self._suspend_callbacks = False
        self._focused_layer: LayerKey = "A"
        self._current_profile = VideoEditProfile()
        self._original_paths: list[Path] = []
        self._selected_video_index = 0

        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0)

        self.left_panel = ctk.CTkScrollableFrame(
            self,
            width=356,
            corner_radius=18,
            fg_color="#0b1320",
            border_width=1,
            border_color="#16253c",
        )
        self.left_panel.grid(row=0, column=0, padx=(12, 8), pady=(10, 8), sticky="ns")
        self.left_panel.grid_columnconfigure(0, weight=1)

        self.preview = VideoPreviewWidget(
            self,
            on_overlay_change=self._handle_overlay_change,
            on_overlay_focus=self._handle_overlay_focus,
        )
        self.preview.grid(row=0, column=1, padx=8, pady=(10, 8), sticky="nsew")

        self.right_panel = ctk.CTkScrollableFrame(
            self,
            width=290,
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
            on_load_quotes_a_files,
            on_load_quotes_a_folder,
            on_load_quotes_b_files,
            on_load_quotes_b_folder,
            on_choose_output_folder,
        )
        self._build_right_panel()
        self.load_profile(VideoEditProfile())
        self._refresh_original_actions()

    def _section_title(self, parent, row: int, title: str, subtitle: str | None = None) -> int:
        ctk.CTkLabel(
            parent,
            text=title,
            font=ctk.CTkFont(family="Bahnschrift", size=17, weight="bold"),
            text_color="#f8fafc",
        ).grid(row=row, column=0, padx=14, pady=(14, 4), sticky="w")
        row += 1
        if subtitle:
            ctk.CTkLabel(
                parent,
                text=subtitle,
                text_color="#8ea2c0",
                wraplength=318,
                justify="left",
            ).grid(row=row, column=0, padx=14, pady=(0, 8), sticky="w")
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
    ) -> tuple[int, ctk.CTkButton, ctk.CTkButton]:
        row_frame = ctk.CTkFrame(parent, fg_color="#0f1b31", corner_radius=14)
        row_frame.grid(row=row, column=0, padx=14, pady=(0, 8), sticky="ew")
        row_frame.grid_columnconfigure(0, weight=1)
        row_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            row_frame,
            text=title,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color="#f8fafc",
        ).grid(row=0, column=0, columnspan=2, padx=10, pady=(8, 6), sticky="w")

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
        return row + 1, files_button, folder_button

    def _build_left_panel(
        self,
        on_load_originals_files,
        on_load_originals_folder,
        on_load_music_files,
        on_load_music_folder,
        on_load_quotes_a_files,
        on_load_quotes_a_folder,
        on_load_quotes_b_files,
        on_load_quotes_b_folder,
        on_choose_output_folder,
    ) -> None:
        row = 0
        row = self._section_title(
            self.left_panel,
            row,
            "Ресурсы",
            "Можно загружать по файлам или целыми папками. Для каждого видео хранится свой макет двух независимых слоёв A/B.",
        )

        row, self.originals_files_button, self.originals_folder_button = self._resource_row(
            self.left_panel,
            row,
            "Оригиналы",
            on_load_originals_files,
            on_load_originals_folder,
            "Выбрать mp4",
            "Папка",
            "#2563eb",
        )
        row, self.music_files_button, self.music_folder_button = self._resource_row(
            self.left_panel,
            row,
            "Музыка",
            on_load_music_files,
            on_load_music_folder,
            "Выбрать mp3",
            "Папка",
            "#0f766e",
        )
        row, self.quotes_a_files_button, self.quotes_a_folder_button = self._resource_row(
            self.left_panel,
            row,
            "Цитаты A",
            on_load_quotes_a_files,
            on_load_quotes_a_folder,
            "txt для A",
            "Папка",
            "#7c3aed",
        )
        row, self.quotes_b_files_button, self.quotes_b_folder_button = self._resource_row(
            self.left_panel,
            row,
            "Цитаты B",
            on_load_quotes_b_files,
            on_load_quotes_b_folder,
            "txt для B",
            "Папка",
            "#ec4899",
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
            text="output",
            text_color="#cbd5e1",
            justify="left",
            wraplength=318,
        )
        self.output_label.grid(row=row, column=0, padx=14, pady=(0, 10), sticky="w")
        row += 1

        row = self._section_title(
            self.left_panel,
            row,
            "Цитаты поверх кадра",
            "Оба блока видны одновременно. Клик по цитате в превью подсвечивает её блок настроек слева.",
        )
        row, self.layer_sections = self._build_layer_sections(row)

        row = self._section_title(self.left_panel, row, "Генерация", "Эти параметры общие для всего запуска.")

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
        self.variation_slider.grid(row=row, column=0, padx=14, pady=(0, 8), sticky="ew")
        row += 1

        self.enhance_sharpness_switch = ctk.CTkSwitch(
            self.left_panel,
            text="Повысить чёткость при рендере",
            command=self._emit_profile_change,
            progress_color="#22c55e",
        )
        self.enhance_sharpness_switch.grid(row=row, column=0, padx=14, pady=(0, 12), sticky="w")
        row += 1

        buttons = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        buttons.grid(row=row, column=0, padx=14, pady=(0, 14), sticky="ew")
        buttons.grid_columnconfigure(0, weight=1)

        self.apply_button = ctk.CTkButton(
            buttons,
            text="Применить ко всем",
            command=self._on_apply_style,
            height=38,
            corner_radius=12,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
        )
        self.apply_button.grid(row=0, column=0, sticky="ew")

        self.generate_button = ctk.CTkButton(
            buttons,
            text="Начать генерацию",
            command=self._on_generate,
            height=38,
            corner_radius=12,
            fg_color="#f97316",
            hover_color="#ea580c",
        )
        self.generate_button.grid(row=1, column=0, pady=(8, 0), sticky="ew")

        self.stop_generation_button = ctk.CTkButton(
            buttons,
            text="Остановить",
            command=self._on_stop_generation,
            height=38,
            corner_radius=12,
            fg_color="#991b1b",
            hover_color="#b91c1c",
            state="disabled",
        )
        self.stop_generation_button.grid(row=2, column=0, pady=(8, 0), sticky="ew")

    def _build_layer_sections(self, row: int) -> tuple[int, dict[LayerKey, LayerSectionControls]]:
        sections: dict[LayerKey, LayerSectionControls] = {}
        row, sections["A"] = self._build_layer_section(
            self.left_panel,
            row,
            key="A",
            title="Цитата A",
            accent="#2563eb",
            subtitle="Если txt-пул A не загружен, в генерацию пойдёт этот sample-текст. Пустой текст выключает слой.",
        )
        row, sections["B"] = self._build_layer_section(
            self.left_panel,
            row,
            key="B",
            title="Цитата B",
            accent="#ec4899",
            subtitle="Второй независимый слой. Можно использовать второй txt-пул или свой fallback sample.",
        )
        return row, sections

    def _build_layer_section(
        self,
        parent,
        row: int,
        *,
        key: LayerKey,
        title: str,
        accent: str,
        subtitle: str,
    ) -> tuple[int, LayerSectionControls]:
        frame = ctk.CTkFrame(
            parent,
            fg_color="#0f1b31",
            corner_radius=16,
            border_width=1,
            border_color="#16253c",
        )
        frame.grid(row=row, column=0, padx=14, pady=(0, 12), sticky="ew")
        frame.grid_columnconfigure(0, weight=1)
        row += 1

        title_label = ctk.CTkLabel(
            frame,
            text=title,
            font=ctk.CTkFont(family="Bahnschrift", size=16, weight="bold"),
            text_color="#f8fafc",
        )
        title_label.grid(row=0, column=0, padx=12, pady=(12, 2), sticky="w")

        ctk.CTkLabel(
            frame,
            text=subtitle,
            text_color="#8ea2c0",
            wraplength=294,
            justify="left",
        ).grid(row=1, column=0, padx=12, pady=(0, 8), sticky="w")

        enabled_switch = ctk.CTkSwitch(
            frame,
            text="Слой включён",
            command=lambda layer=key: self._handle_section_change(layer),
            progress_color=accent,
        )
        enabled_switch.grid(row=2, column=0, padx=12, pady=(0, 8), sticky="w")

        sample_quote_box = ctk.CTkTextbox(
            frame,
            height=92,
            corner_radius=14,
            fg_color="#09111f",
            border_width=1,
            border_color="#16253c",
            wrap="word",
            font=ctk.CTkFont(family="Segoe UI", size=13),
        )
        sample_quote_box.grid(row=3, column=0, padx=12, pady=(0, 10), sticky="ew")
        sample_quote_box.bind("<KeyRelease>", lambda _event, layer=key: self._handle_section_change(layer))

        font_combo = ctk.CTkComboBox(
            frame,
            values=self._fonts,
            height=34,
            corner_radius=12,
            command=lambda _value, layer=key: self._handle_section_change(layer),
        )
        font_combo.grid(row=4, column=0, padx=12, pady=(0, 10), sticky="ew")

        font_size_label = ctk.CTkLabel(frame, text="Размер: 64 px", text_color="#dbe4f0")
        font_size_label.grid(row=5, column=0, padx=12, pady=(0, 4), sticky="w")
        font_size_slider = ctk.CTkSlider(
            frame,
            from_=28,
            to=128,
            number_of_steps=100,
            command=lambda value, layer=key: self._on_font_size_changed(layer, value),
            progress_color="#f97316",
        )
        font_size_slider.grid(row=6, column=0, padx=12, pady=(0, 8), sticky="ew")

        box_width_label = ctk.CTkLabel(frame, text="Ширина блока: 72%", text_color="#dbe4f0")
        box_width_label.grid(row=7, column=0, padx=12, pady=(0, 4), sticky="w")
        box_width_slider = ctk.CTkSlider(
            frame,
            from_=0.30,
            to=0.90,
            number_of_steps=60,
            command=lambda value, layer=key: self._on_box_width_changed(layer, value),
            progress_color="#38bdf8",
        )
        box_width_slider.grid(row=8, column=0, padx=12, pady=(0, 8), sticky="ew")

        text_color_picker = ColorPickerRow(
            frame,
            title="Цвет текста",
            initial_color="#FFFFFF",
            on_change=lambda _value, layer=key: self._handle_section_change(layer),
        )
        text_color_picker.grid(row=9, column=0, padx=12, pady=(0, 4), sticky="ew")

        bg_color_picker = ColorPickerRow(
            frame,
            title="Фон цитаты",
            initial_color="#101010",
            on_change=lambda _value, layer=key: self._handle_section_change(layer),
        )
        bg_color_picker.grid(row=10, column=0, padx=12, pady=(0, 4), sticky="ew")

        bg_opacity_label = ctk.CTkLabel(frame, text="Прозрачность: 45%", text_color="#dbe4f0")
        bg_opacity_label.grid(row=11, column=0, padx=12, pady=(0, 4), sticky="w")
        bg_opacity_slider = ctk.CTkSlider(
            frame,
            from_=0.0,
            to=1.0,
            number_of_steps=100,
            command=lambda value, layer=key: self._on_bg_opacity_changed(layer, value),
            progress_color="#06b6d4",
        )
        bg_opacity_slider.grid(row=12, column=0, padx=12, pady=(0, 8), sticky="ew")

        corner_radius_label = ctk.CTkLabel(frame, text="Скругление: 36 px", text_color="#dbe4f0")
        corner_radius_label.grid(row=13, column=0, padx=12, pady=(0, 4), sticky="w")
        corner_radius_slider = ctk.CTkSlider(
            frame,
            from_=8,
            to=92,
            number_of_steps=84,
            command=lambda value, layer=key: self._on_corner_radius_changed(layer, value),
            progress_color="#a78bfa",
        )
        corner_radius_slider.grid(row=14, column=0, padx=12, pady=(0, 8), sticky="ew")

        shadow_label = ctk.CTkLabel(frame, text="Тень: 45%", text_color="#dbe4f0")
        shadow_label.grid(row=15, column=0, padx=12, pady=(0, 4), sticky="w")
        shadow_slider = ctk.CTkSlider(
            frame,
            from_=0.0,
            to=1.0,
            number_of_steps=100,
            command=lambda value, layer=key: self._on_shadow_changed(layer, value),
            progress_color="#f59e0b",
        )
        shadow_slider.grid(row=16, column=0, padx=12, pady=(0, 12), sticky="ew")

        return row, LayerSectionControls(
            key=key,
            frame=frame,
            title_label=title_label,
            enabled_switch=enabled_switch,
            sample_quote_box=sample_quote_box,
            font_combo=font_combo,
            font_size_label=font_size_label,
            font_size_slider=font_size_slider,
            box_width_label=box_width_label,
            box_width_slider=box_width_slider,
            text_color_picker=text_color_picker,
            bg_color_picker=bg_color_picker,
            bg_opacity_label=bg_opacity_label,
            bg_opacity_slider=bg_opacity_slider,
            corner_radius_label=corner_radius_label,
            corner_radius_slider=corner_radius_slider,
            shadow_label=shadow_label,
            shadow_slider=shadow_slider,
        )

    def _build_right_panel(self) -> None:
        row = 0
        row = self._section_title(
            self.right_panel,
            row,
            "Video Inspector",
            "Быстрая навигация по исходникам, состоянию слоёв и текущей папке результата.",
        )

        nav_frame = ctk.CTkFrame(self.right_panel, fg_color="#0f1b31", corner_radius=14)
        nav_frame.grid(row=row, column=0, padx=14, pady=(0, 10), sticky="ew")
        nav_frame.grid_columnconfigure(1, weight=1)
        self.prev_video_button = ctk.CTkButton(nav_frame, text="Prev", width=60, command=self._select_prev_video)
        self.prev_video_button.grid(row=0, column=0, padx=(10, 6), pady=10)
        self.current_video_label = ctk.CTkLabel(nav_frame, text="Видео не выбрано", text_color="#f8fafc")
        self.current_video_label.grid(row=0, column=1, padx=6, pady=10, sticky="w")
        self.next_video_button = ctk.CTkButton(nav_frame, text="Next", width=60, command=self._select_next_video)
        self.next_video_button.grid(row=0, column=2, padx=(6, 10), pady=10)
        row += 1

        self.inspector_summary = ctk.CTkLabel(
            self.right_panel,
            text="Оригиналы: 0\nМузыка: 0\nЦитаты A: 0\nЦитаты B: 0",
            justify="left",
            anchor="w",
            text_color="#cbd5e1",
        )
        self.inspector_summary.grid(row=row, column=0, padx=14, pady=(0, 10), sticky="ew")
        row += 1

        self.layer_status = ctk.CTkLabel(
            self.right_panel,
            text="Слои:\nA: выкл\nB: выкл",
            justify="left",
            anchor="w",
            text_color="#cbd5e1",
        )
        self.layer_status.grid(row=row, column=0, padx=14, pady=(0, 12), sticky="ew")
        row += 1

        self.output_status = ctk.CTkLabel(
            self.right_panel,
            text="Вывод: output",
            justify="left",
            anchor="w",
            text_color="#cbd5e1",
            wraplength=240,
        )
        self.output_status.grid(row=row, column=0, padx=14, pady=(0, 12), sticky="ew")
        row += 1

        self.list_title = ctk.CTkLabel(
            self.right_panel,
            text="Исходники",
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
            height=13,
        )
        self.listbox.grid(row=row, column=0, padx=14, pady=(0, 12), sticky="ew")
        self.listbox.bind("<<ListboxSelect>>", self._handle_video_selected)
        self.listbox.bind("<Delete>", self._handle_delete_pressed)
        row += 1

        self.remove_original_button = ctk.CTkButton(
            self.right_panel,
            text="Удалить из проекта",
            command=self._on_remove_original,
            height=36,
            corner_radius=12,
            fg_color="#7f1d1d",
            hover_color="#991b1b",
            state="disabled",
        )
        self.remove_original_button.grid(row=row, column=0, padx=14, pady=(0, 12), sticky="ew")

    def _get_layer_style(self, layer: LayerKey) -> TextStyle:
        return self._current_profile.layer_a if layer == "A" else self._current_profile.layer_b

    def _set_layer_style(self, layer: LayerKey, style: TextStyle) -> None:
        if layer == "A":
            self._current_profile.layer_a = replace(style)
        else:
            self._current_profile.layer_b = replace(style)

    def _read_section_style(self, layer: LayerKey) -> TextStyle:
        section = self.layer_sections[layer]
        current_style = self._get_layer_style(layer)
        font_size = int(round(section.font_size_slider.get()))
        text_value = section.sample_quote_box.get("1.0", "end-1c")
        return replace(
            current_style,
            text_color=section.text_color_picker.get_value(),
            background_color=section.bg_color_picker.get_value(),
            background_opacity=float(section.bg_opacity_slider.get()),
            shadow_strength=float(section.shadow_slider.get()),
            font_size=font_size,
            font_name=section.font_combo.get(),
            preview_text=text_value,
            box_width_ratio=float(section.box_width_slider.get()),
            padding_x=max(18, int(round(font_size * 0.55))),
            padding_y=max(12, int(round(font_size * 0.35))),
            corner_radius=int(round(section.corner_radius_slider.get())),
            text_align="center",
            line_spacing=1.18,
            enabled=bool(section.enabled_switch.get()),
        )

    def _load_layer_into_section(self, layer: LayerKey, style: TextStyle) -> None:
        section = self.layer_sections[layer]
        self._suspend_callbacks = True
        if style.enabled:
            section.enabled_switch.select()
        else:
            section.enabled_switch.deselect()
        section.sample_quote_box.delete("1.0", "end")
        section.sample_quote_box.insert("1.0", style.preview_text)
        section.font_combo.set(style.font_name if style.font_name in self._fonts else self._fonts[0])
        section.font_size_slider.set(style.font_size)
        section.box_width_slider.set(style.box_width_ratio)
        section.bg_opacity_slider.set(style.background_opacity)
        section.corner_radius_slider.set(style.corner_radius)
        section.shadow_slider.set(style.shadow_strength)
        section.text_color_picker.set_value(style.text_color)
        section.bg_color_picker.set_value(style.background_color)
        self._update_section_labels(layer, style)
        self._suspend_callbacks = False

    def _update_section_labels(self, layer: LayerKey, style: TextStyle | None = None) -> None:
        section = self.layer_sections[layer]
        current = style or self._read_section_style(layer)
        section.font_size_label.configure(text=f"Размер: {int(round(current.font_size))} px")
        section.box_width_label.configure(text=f"Ширина блока: {int(round(current.box_width_ratio * 100))}%")
        section.bg_opacity_label.configure(text=f"Прозрачность: {int(round(current.background_opacity * 100))}%")
        section.corner_radius_label.configure(text=f"Скругление: {int(round(current.corner_radius))} px")
        section.shadow_label.configure(text=f"Тень: {int(round(current.shadow_strength * 100))}%")

    def _sync_layer_from_section(self, layer: LayerKey, *, update_preview: bool = True) -> TextStyle:
        style = self._read_section_style(layer)
        self._set_layer_style(layer, style)
        if update_preview:
            self.preview.update_layer(layer, style)
        return style

    def _sync_all_sections_to_profile(self) -> None:
        if self._suspend_callbacks:
            return
        for layer in ("A", "B"):
            self._sync_layer_from_section(layer, update_preview=False)

    def _handle_section_change(self, layer: LayerKey) -> None:
        if self._suspend_callbacks:
            return
        self._focus_layer(layer)
        style = self._sync_layer_from_section(layer)
        self._update_section_labels(layer, style)
        self._emit_profile_change()

    def _emit_profile_change(self) -> None:
        if self._suspend_callbacks:
            return
        self._sync_all_sections_to_profile()
        self.preview.load_profile(self._current_profile)
        self.preview.set_active_layer(self._focused_layer)
        self._on_profile_changed(self._current_profile.copy(), self.read_variation_count(), self.read_enhance_sharpness())
        self._refresh_inspector()

    def _focus_layer(self, layer: LayerKey) -> None:
        self._focused_layer = layer
        self.preview.set_active_layer(layer)
        for section_layer, section in self.layer_sections.items():
            is_active = section_layer == layer
            border_color = "#2563eb" if section_layer == "A" else "#ec4899"
            section.frame.configure(
                border_color=border_color if is_active else "#16253c",
                fg_color="#12233d" if is_active else "#0f1b31",
            )

    def _handle_overlay_focus(self, layer: LayerKey) -> None:
        self._focus_layer(layer)

    def _on_font_size_changed(self, layer: LayerKey, value: float) -> None:
        section = self.layer_sections[layer]
        section.font_size_label.configure(text=f"Размер: {int(round(value))} px")
        self._handle_section_change(layer)

    def _on_box_width_changed(self, layer: LayerKey, value: float) -> None:
        section = self.layer_sections[layer]
        section.box_width_label.configure(text=f"Ширина блока: {int(round(value * 100))}%")
        self._handle_section_change(layer)

    def _on_bg_opacity_changed(self, layer: LayerKey, value: float) -> None:
        section = self.layer_sections[layer]
        section.bg_opacity_label.configure(text=f"Прозрачность: {int(round(value * 100))}%")
        self._handle_section_change(layer)

    def _on_corner_radius_changed(self, layer: LayerKey, value: float) -> None:
        section = self.layer_sections[layer]
        section.corner_radius_label.configure(text=f"Скругление: {int(round(value))} px")
        self._handle_section_change(layer)

    def _on_shadow_changed(self, layer: LayerKey, value: float) -> None:
        section = self.layer_sections[layer]
        section.shadow_label.configure(text=f"Тень: {int(round(value * 100))}%")
        self._handle_section_change(layer)

    def _on_variation_changed(self, value: float) -> None:
        self.variation_label.configure(text=f"Вариаций на оригинал: {int(round(value))}")
        self._emit_profile_change()

    def _handle_video_selected(self, _event=None) -> None:
        selection = self.listbox.curselection()
        if not selection:
            return
        self._selected_video_index = selection[0]
        self._on_video_selected(self._original_paths[self._selected_video_index])

    def _handle_delete_pressed(self, _event=None) -> str:
        if self._original_paths:
            self._on_remove_original()
        return "break"

    def _select_prev_video(self) -> None:
        if not self._original_paths:
            return
        self._selected_video_index = (self._selected_video_index - 1) % len(self._original_paths)
        self._select_video_from_index()

    def _select_next_video(self) -> None:
        if not self._original_paths:
            return
        self._selected_video_index = (self._selected_video_index + 1) % len(self._original_paths)
        self._select_video_from_index()

    def _select_video_from_index(self) -> None:
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(self._selected_video_index)
        self.listbox.activate(self._selected_video_index)
        self._on_video_selected(self._original_paths[self._selected_video_index])

    def _refresh_original_actions(self) -> None:
        has_originals = bool(self._original_paths)
        button_state = "normal" if has_originals else "disabled"
        self.prev_video_button.configure(state=button_state)
        self.next_video_button.configure(state=button_state)
        self.remove_original_button.configure(state=button_state)

    def _handle_overlay_change(self, layer: LayerKey, style: TextStyle) -> None:
        self._set_layer_style(layer, style)
        self._focus_layer(layer)
        self._load_layer_into_section(layer, style)
        self._on_overlay_changed(layer, style)
        self._refresh_inspector()

    def load_profile(self, profile: VideoEditProfile) -> None:
        self._current_profile = profile.copy()
        self.preview.load_profile(self._current_profile)
        self._load_layer_into_section("A", self._current_profile.layer_a)
        self._load_layer_into_section("B", self._current_profile.layer_b)
        self._focus_layer(self._focused_layer)
        self._refresh_inspector()

    def read_video_profile(self) -> VideoEditProfile:
        self._sync_all_sections_to_profile()
        return self._current_profile.copy()

    def read_variation_count(self) -> int:
        return int(round(self.variation_slider.get()))

    def read_enhance_sharpness(self) -> bool:
        return bool(self.enhance_sharpness_switch.get())

    def set_quote_sample(self, layer: LayerKey, quote: str) -> None:
        style = self._get_layer_style(layer)
        style.preview_text = quote
        if quote.strip():
            style.enabled = True
        self._load_layer_into_section(layer, style)
        self._focus_layer(layer)
        self.preview.update_layer(layer, style)
        self._refresh_inspector()

    def set_originals(self, paths: list[Path], selected_path: Path | None = None) -> None:
        self._original_paths = list(paths)
        self.listbox.delete(0, "end")
        for path in paths:
            self.listbox.insert("end", path.name)
        if not paths:
            self._selected_video_index = 0
            self.listbox.selection_clear(0, "end")
            self.current_video_label.configure(text="Видео не выбрано")
            self._refresh_original_actions()
            return
        if selected_path and selected_path in paths:
            self._selected_video_index = paths.index(selected_path)
        else:
            self._selected_video_index = 0
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(self._selected_video_index)
        self.listbox.activate(self._selected_video_index)
        self.current_video_label.configure(text=paths[self._selected_video_index].name)
        self._refresh_original_actions()

    def set_media_summary(
        self,
        *,
        originals_count: int,
        music_count: int,
        quotes_count_a: int,
        quotes_count_b: int,
        max_warning_variations: int,
    ) -> None:
        self.inspector_summary.configure(
            text=(
                f"Оригиналы: {originals_count}\n"
                f"Музыка: {music_count}\n"
                f"Цитаты A: {quotes_count_a}\n"
                f"Цитаты B: {quotes_count_b}\n"
                f"Warning budget: {max_warning_variations}"
            )
        )

    def set_output_directory(self, path: Path) -> None:
        path_text = str(path)
        self.output_label.configure(text=path_text)
        self.output_status.configure(text=f"Вывод: {path_text}")

    def set_ffmpeg_status(self, status_text: str, available: bool) -> None:
        color = "#22c55e" if available else "#f97316"
        self.current_video_label.configure(text_color=color if not self._original_paths else "#f8fafc")
        if not self._original_paths:
            self.current_video_label.configure(text=status_text)

    def clear_generation_console(self) -> None:
        self.generation_console.clear()

    def set_generation_console_expanded(self, expanded: bool) -> None:
        self.generation_console.set_expanded(expanded)

    def set_stop_button_state(self, *, is_running: bool, stop_requested: bool) -> None:
        if is_running:
            self.stop_generation_button.configure(
                state="disabled" if stop_requested else "normal",
                text="Останавливаю..." if stop_requested else "Остановить",
            )
        else:
            self.stop_generation_button.configure(state="disabled", text="Остановить")

    def push_generation_event(self, event: GenerationProgressEvent) -> None:
        if event.stage not in {"Ожидание"}:
            self.generation_console.set_expanded(True)
        self.generation_console.push_event(event)
        if event.stage in {"Рендер", "Проверка качества", "Экспорт расписания"}:
            self.preview.set_runtime_status(event.message)
        elif event.stage in {"Готово", "Ошибка", "Ожидание", "Остановлено", "Остановка"}:
            self.preview.set_runtime_status(None)

    def set_generation_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in (
            self.originals_files_button,
            self.originals_folder_button,
            self.music_files_button,
            self.music_folder_button,
            self.quotes_a_files_button,
            self.quotes_a_folder_button,
            self.quotes_b_files_button,
            self.quotes_b_folder_button,
            self.output_button,
            self.apply_button,
            self.generate_button,
            self.remove_original_button,
            self.variation_slider,
            self.prev_video_button,
            self.next_video_button,
        ):
            widget.configure(state=state)

        self.listbox.configure(state=state)
        self.enhance_sharpness_switch.configure(state=state)

        for section in self.layer_sections.values():
            for widget in (
                section.enabled_switch,
                section.sample_quote_box,
                section.font_combo,
                section.font_size_slider,
                section.box_width_slider,
                section.bg_opacity_slider,
                section.corner_radius_slider,
                section.shadow_slider,
            ):
                widget.configure(state=state)
            section.text_color_picker.set_enabled(enabled)
            section.bg_color_picker.set_enabled(enabled)

        self.preview.set_interaction_enabled(enabled)
        if enabled:
            self._refresh_original_actions()

    def _refresh_inspector(self) -> None:
        a = self._current_profile.layer_a
        b = self._current_profile.layer_b
        self.layer_status.configure(
            text=(
                f"Слои:\n"
                f"A: {'вкл' if a.enabled else 'выкл'} | текст: {len(a.preview_text.strip())} симв.\n"
                f"B: {'вкл' if b.enabled else 'выкл'} | текст: {len(b.preview_text.strip())} симв."
            )
        )
