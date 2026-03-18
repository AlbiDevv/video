from __future__ import annotations

import copy
import logging
import threading
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox

from video_unicalizator.utils.tk_runtime import ensure_tcl_tk_environment

ensure_tcl_tk_environment()

import customtkinter as ctk

from video_unicalizator.core.variation_generator import GenerationRunSummary, VariationGenerator
from video_unicalizator.services.export_service import ExportService
from video_unicalizator.services.file_loader import (
    load_music_tracks,
    load_music_tracks_from_folder,
    load_original_videos,
    load_original_videos_from_folder,
    load_quote_files,
    load_quote_files_from_folder,
    merge_media_library,
)
from video_unicalizator.services.quote_loader import load_quotes_from_files
from video_unicalizator.state import AppState, GenerationProgressEvent, ScheduleEntry, TextStyle
from video_unicalizator.ui.tabs.batch_runner import BatchRunnerTab
from video_unicalizator.ui.tabs.scheduler import SchedulerTab
from video_unicalizator.ui.tabs.text_editor import TextEditorTab
from video_unicalizator.utils.ffmpeg_tools import ffmpeg_available, ffmpeg_status_message
from video_unicalizator.utils.validation import ValidationError, validate_variation_count


class VideoUnicalizatorApp(ctk.CTk):
    """Главное окно приложения."""

    def __init__(self) -> None:
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.app_state = AppState()
        self.generator = VariationGenerator()
        self.export_service = ExportService()
        self._worker_thread: threading.Thread | None = None

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Video Unicalizator")
        self.geometry("1540x980")
        self.minsize(1320, 820)
        self.configure(fg_color="#050914")
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_header()
        self._build_views()
        self._refresh_ffmpeg_status()
        self._sync_ui_with_state()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, height=50, corner_radius=0, fg_color="#07101d")
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        title = ctk.CTkLabel(
            header,
            text="Video Unicalizator",
            font=ctk.CTkFont(family="Bahnschrift", size=20, weight="bold"),
            text_color="#f8fafc",
        )
        title.grid(row=0, column=0, padx=14, pady=10, sticky="w")

        self.navbar = ctk.CTkSegmentedButton(
            header,
            values=["Редактор", "История", "Расписание"],
            command=self._show_view,
            selected_color="#f97316",
            selected_hover_color="#ea580c",
            unselected_color="#111827",
            unselected_hover_color="#1f2937",
        )
        self.navbar.grid(row=0, column=2, padx=14, pady=8, sticky="e")
        self.navbar.set("Редактор")

    def _build_views(self) -> None:
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        available_fonts = sorted(set(tkfont.families()))
        preferred = ["Bahnschrift", "Segoe UI", "Arial", "Calibri"]
        fonts = [font for font in preferred if font in available_fonts] + [
            font for font in available_fonts if font not in preferred
        ]
        if not fonts:
            fonts = ["Arial"]

        self.editor_view = TextEditorTab(
            self.content,
            fonts=fonts,
            on_load_originals_files=self._load_originals_files,
            on_load_originals_folder=self._load_originals_folder,
            on_load_music_files=self._load_music_files,
            on_load_music_folder=self._load_music_folder,
            on_load_quotes_files=self._load_quotes_files,
            on_load_quotes_folder=self._load_quotes_folder,
            on_choose_output_folder=self._choose_output_folder,
            on_apply_style=self._apply_text_settings,
            on_generate=self._start_generation,
            on_video_selected=self._select_video,
            on_style_changed=self._handle_style_change,
            on_overlay_changed=self._handle_overlay_change,
        )

        self.batch_view = BatchRunnerTab(self.content)
        self.scheduler_view = SchedulerTab(self.content)

        self.views = {
            "Редактор": self.editor_view,
            "История": self.batch_view,
            "Расписание": self.scheduler_view,
        }
        self._show_view("Редактор")

    def _show_view(self, name: str) -> None:
        for frame in self.views.values():
            frame.grid_remove()
        self.views[name].grid(row=0, column=0, sticky="nsew")
        self.navbar.set(name)

    def _refresh_ffmpeg_status(self) -> None:
        self.app_state.ffmpeg_available = ffmpeg_available()
        self.editor_view.set_ffmpeg_status(ffmpeg_status_message(), self.app_state.ffmpeg_available)

    def _sync_ui_with_state(self) -> None:
        self.editor_view.load_style(self.app_state.text_style)
        self._refresh_media_views()
        self.editor_view.set_output_directory(self.app_state.variations_output_dir)
        self.editor_view.preview.load_video(self.app_state.selected_video)

    def _show_error(self, text: str) -> None:
        self.logger.error(text)
        messagebox.showerror("Ошибка", text)

    def _refresh_media_views(self) -> None:
        self.editor_view.set_media_summary(
            originals_count=len(self.app_state.media.original_videos),
            music_count=len(self.app_state.media.music_tracks),
            quotes_count=len(self.app_state.media.quotes),
        )
        self.editor_view.set_originals(self.app_state.media.original_videos)

    def _log_note(self, message: str) -> None:
        self.batch_view.push_log(message)
        self.editor_view.generation_console.push_log(message)

    def _push_event(self, event: GenerationProgressEvent) -> None:
        self.batch_view.push_event(event)
        self.editor_view.push_generation_event(event)

    def _set_originals(self, originals: list[Path]) -> None:
        self.app_state.media = merge_media_library(self.app_state.media, originals=originals)
        self.app_state.selected_video = originals[0] if originals else None
        self._refresh_media_views()
        if self.app_state.selected_video:
            self.editor_view.preview.load_video(self.app_state.selected_video)
        self._log_note(f"Загружено оригиналов: {len(originals)}")

    def _set_music(self, music: list[Path]) -> None:
        self.app_state.media = merge_media_library(self.app_state.media, music=music)
        self._refresh_media_views()
        self._log_note(f"Загружено треков: {len(music)}")

    def _set_quotes(self, quote_files: list[Path], quotes: list[str]) -> None:
        self.app_state.media = merge_media_library(
            self.app_state.media,
            quote_files=quote_files,
            quotes=quotes,
        )
        if quotes:
            self.app_state.text_style.preview_text = quotes[0]
            self.editor_view.set_quote_sample(quotes[0])
        self._refresh_media_views()
        self._log_note(f"Загружено txt-файлов: {len(quote_files)}")
        self._log_note(f"Загружено цитат: {len(quotes)}")

    def _load_originals_files(self) -> None:
        try:
            paths = filedialog.askopenfilenames(title="Выберите до 5 mp4", filetypes=[("MP4 files", "*.mp4")])
            if not paths:
                return
            self._set_originals(load_original_videos(list(paths)))
        except ValidationError as error:
            self._show_error(str(error))

    def _load_originals_folder(self) -> None:
        try:
            folder = filedialog.askdirectory(title="Выберите папку с mp4")
            if not folder:
                return
            self._set_originals(load_original_videos_from_folder(folder))
        except ValidationError as error:
            self._show_error(str(error))

    def _load_music_files(self) -> None:
        try:
            paths = filedialog.askopenfilenames(title="Выберите mp3 для фоновой музыки", filetypes=[("MP3 files", "*.mp3")])
            if not paths:
                return
            self._set_music(load_music_tracks(list(paths)))
        except ValidationError as error:
            self._show_error(str(error))

    def _load_music_folder(self) -> None:
        try:
            folder = filedialog.askdirectory(title="Выберите папку с mp3")
            if not folder:
                return
            self._set_music(load_music_tracks_from_folder(folder))
        except ValidationError as error:
            self._show_error(str(error))

    def _load_quotes_files(self) -> None:
        try:
            file_paths = filedialog.askopenfilenames(title="Выберите txt-файлы с цитатами", filetypes=[("Text files", "*.txt")])
            if not file_paths:
                return
            quote_files = load_quote_files(list(file_paths))
            self._set_quotes(quote_files, load_quotes_from_files(quote_files))
        except ValidationError as error:
            self._show_error(str(error))

    def _load_quotes_folder(self) -> None:
        try:
            folder = filedialog.askdirectory(title="Выберите папку с txt-файлами")
            if not folder:
                return
            quote_files = load_quote_files_from_folder(folder)
            self._set_quotes(quote_files, load_quotes_from_files(quote_files))
        except ValidationError as error:
            self._show_error(str(error))

    def _choose_output_folder(self) -> None:
        folder = filedialog.askdirectory(title="Выберите папку для результатов")
        if not folder:
            return
        root = Path(folder)
        self.app_state.variations_output_dir = root / "variations"
        self.app_state.schedules_output_dir = root / "schedules"
        self.app_state.variations_output_dir.mkdir(parents=True, exist_ok=True)
        self.app_state.schedules_output_dir.mkdir(parents=True, exist_ok=True)
        self.editor_view.set_output_directory(self.app_state.variations_output_dir)
        self._log_note(f"Папка вывода: {root}")

    def _select_video(self, path: Path) -> None:
        self.app_state.selected_video = path
        self.editor_view.preview.load_video(path)

    def _handle_style_change(self, text_style: TextStyle, variation_count: int) -> None:
        self.app_state.text_style = text_style
        self.app_state.generation.variation_count = validate_variation_count(variation_count)
        self.editor_view.update_preview_style(self.app_state.text_style)

    def _handle_overlay_change(self, style: TextStyle) -> None:
        self.app_state.text_style = self.editor_view.read_text_style()
        self.app_state.text_style.position_x = style.position_x
        self.app_state.text_style.position_y = style.position_y
        self.app_state.text_style.box_width_ratio = style.box_width_ratio
        self.app_state.text_style.font_size = style.font_size
        self.app_state.text_style.corner_radius = style.corner_radius

    def _apply_text_settings(self) -> None:
        self.app_state.text_style = self.editor_view.read_text_style()
        self.app_state.generation.variation_count = validate_variation_count(self.editor_view.read_variation_count())
        self.editor_view.update_preview_style(self.app_state.text_style)
        self._log_note("Настройки цитаты сохранены и будут применены ко всем вариациям.")

    def _start_generation(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return

        try:
            self._apply_text_settings()
        except ValidationError as error:
            self._show_error(str(error))
            return

        self._show_view("Редактор")
        self.batch_view.clear()
        self.editor_view.clear_generation_console()
        self.editor_view.set_generation_console_expanded(True)
        self._push_event(
            GenerationProgressEvent(
                stage="Подготовка",
                message="Запуск генерации. Подготавливаю задачу и блокирую редактор.",
                progress=0.0,
            )
        )
        self.editor_view.set_generation_enabled(False)

        state_snapshot = copy.deepcopy(self.app_state)
        self._worker_thread = threading.Thread(target=self._run_generation_worker, args=(state_snapshot,), daemon=True)
        self._worker_thread.start()

    def _threadsafe_progress(self, event: GenerationProgressEvent) -> None:
        self.after(0, lambda: self._push_event(event))

    def _run_generation_worker(self, state_snapshot: AppState) -> None:
        try:
            generated = self.generator.generate(state_snapshot, callback=self._threadsafe_progress)
            if generated:
                entries, schedule_file = self.export_service.export_schedule(
                    generated,
                    state_snapshot.schedules_output_dir,
                    callback=self._threadsafe_progress,
                )
            else:
                entries, schedule_file = [], None
            summary = self.generator.last_summary
            self.after(0, lambda: self._finish_generation(generated, entries, schedule_file, summary))
        except Exception as error:  # noqa: BLE001
            self.logger.exception("Сбой фоновой генерации")
            self.after(0, lambda: self._handle_generation_error(str(error)))

    def _build_generation_summary_text(
        self,
        generated_count: int,
        summary: GenerationRunSummary,
        schedule_file: Path | None,
    ) -> str:
        lines = [
            f"Успешно: {generated_count}",
            f"Пропущено: {summary.failed_count}",
        ]
        if summary.soft_accepted_count:
            lines.append(f"Soft-accept: {summary.soft_accepted_count}")
        if summary.warning_count:
            lines.append(f"С предупреждениями: {summary.warning_count}")
        if schedule_file is not None:
            lines.append(f"Расписание: {schedule_file.name}")
        return ". ".join(lines)

    def _finish_generation(
        self,
        generated,
        entries: list[ScheduleEntry],
        schedule_file: Path | None,
        summary: GenerationRunSummary,
    ) -> None:
        self.app_state.generated_variations = generated
        self.app_state.schedule_entries = entries
        self.app_state.schedule_file = schedule_file
        self._worker_thread = None
        summary_text = self._build_generation_summary_text(len(generated), summary, schedule_file)
        self._push_event(
            GenerationProgressEvent(
                stage="Готово",
                message=summary_text,
                progress=1.0,
                level="success" if generated else "warning",
            )
        )
        self.scheduler_view.update_entries(entries, schedule_file)
        self.editor_view.set_generation_enabled(True)
        messagebox.showinfo("Готово", summary_text)

    def _handle_generation_error(self, message: str) -> None:
        self._worker_thread = None
        self._push_event(
            GenerationProgressEvent(
                stage="Ошибка",
                message=message,
                progress=0.0,
                level="error",
            )
        )
        self.editor_view.set_generation_enabled(True)
        self._show_error(message)
