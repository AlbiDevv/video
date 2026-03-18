from __future__ import annotations

import copy
import logging
import threading
import tkinter.font as tkfont
from dataclasses import replace
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
from video_unicalizator.state import (
    AppState,
    GenerationCancelToken,
    GenerationProgressEvent,
    ScheduleEntry,
    TextStyle,
    VideoEditProfile,
)
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
        self._cancel_token: GenerationCancelToken | None = None

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

        ctk.CTkLabel(
            header,
            text="Video Unicalizator",
            font=ctk.CTkFont(family="Bahnschrift", size=20, weight="bold"),
            text_color="#f8fafc",
        ).grid(row=0, column=0, padx=14, pady=10, sticky="w")

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
            on_load_quotes_a_files=self._load_quotes_a_files,
            on_load_quotes_a_folder=self._load_quotes_a_folder,
            on_load_quotes_b_files=self._load_quotes_b_files,
            on_load_quotes_b_folder=self._load_quotes_b_folder,
            on_choose_output_folder=self._choose_output_folder,
            on_apply_style=self._apply_profile_to_all,
            on_generate=self._start_generation,
            on_stop_generation=self._stop_generation,
            on_remove_original=self._remove_selected_original,
            on_video_selected=self._select_video,
            on_profile_changed=self._handle_profile_change,
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

    def _current_profile(self) -> VideoEditProfile:
        if self.app_state.selected_video is not None:
            return self.app_state.ensure_video_profile(self.app_state.selected_video)
        return self.app_state.build_default_profile()

    def _sync_ui_with_state(self) -> None:
        self.editor_view.load_profile(self._current_profile())
        self._refresh_media_views()
        self.editor_view.set_output_directory(self.app_state.output_dir)
        self.editor_view.preview.load_video(self.app_state.selected_video)

    def _show_error(self, text: str) -> None:
        self.logger.error(text)
        messagebox.showerror("Ошибка", text)

    def _refresh_media_views(self) -> None:
        self.editor_view.set_media_summary(
            originals_count=len(self.app_state.media.original_videos),
            music_count=len(self.app_state.media.music_tracks),
            quotes_count_a=len(self.app_state.media.quotes_a),
            quotes_count_b=len(self.app_state.media.quotes_b),
            max_warning_variations=self.app_state.generation.max_warning_variations,
        )
        self.editor_view.set_originals(self.app_state.media.original_videos, self.app_state.selected_video)
        if self.app_state.selected_video is not None:
            self.editor_view.load_profile(self.app_state.ensure_video_profile(self.app_state.selected_video))
        else:
            self.editor_view.load_profile(self._current_profile())
            self.editor_view.preview.load_video(None)

    def _log_note(self, message: str) -> None:
        self.batch_view.push_log(message)
        self.editor_view.generation_console.push_log(message)

    def _push_event(self, event: GenerationProgressEvent) -> None:
        self.batch_view.push_event(event)
        self.editor_view.push_generation_event(event)

    def _sync_selected_profile_from_editor(self) -> None:
        profile = self.editor_view.read_video_profile()
        self.app_state.set_default_layer_sample("A", profile.layer_a.preview_text)
        self.app_state.set_default_layer_sample("B", profile.layer_b.preview_text)
        if self.app_state.selected_video is None:
            return
        self.app_state.video_profiles[str(self.app_state.selected_video)] = profile
        self.app_state.text_style = replace(profile.layer_a)

    def _ensure_profiles_for_originals(self, originals: list[Path]) -> None:
        current = {str(path): self.app_state.ensure_video_profile(path) for path in originals}
        self.app_state.video_profiles = {key: value.copy() for key, value in current.items()}

    def _prime_profiles_from_quotes(self, layer: str, quote: str) -> None:
        if not quote:
            return
        self.app_state.set_default_layer_sample(layer, quote)
        for video_path in self.app_state.media.original_videos:
            profile = self.app_state.ensure_video_profile(video_path)
            layer_style = profile.layer_a if layer == "A" else profile.layer_b
            layer_style.preview_text = quote
            layer_style.enabled = True

    def _set_originals(self, originals: list[Path], selected_video: Path | None = None) -> None:
        self.app_state.media = merge_media_library(self.app_state.media, originals=originals)
        self._ensure_profiles_for_originals(originals)
        if selected_video in originals:
            self.app_state.selected_video = selected_video
        else:
            self.app_state.selected_video = originals[0] if originals else None
        self._refresh_media_views()
        if self.app_state.selected_video:
            self.editor_view.preview.load_video(self.app_state.selected_video)
            self.editor_view.load_profile(self.app_state.ensure_video_profile(self.app_state.selected_video))
        else:
            self.editor_view.preview.load_video(None)
            self.editor_view.load_profile(self._current_profile())
        self._log_note(f"Загружено оригиналов: {len(originals)}")

    def _set_music(self, music: list[Path]) -> None:
        self.app_state.media = merge_media_library(self.app_state.media, music=music)
        self._refresh_media_views()
        self._log_note(f"Загружено треков: {len(music)}")

    def _set_quotes_a(self, quote_files: list[Path], quotes: list[str]) -> None:
        self.app_state.media = merge_media_library(
            self.app_state.media,
            quote_files_a=quote_files,
            quotes_a=quotes,
        )
        if quotes:
            self._prime_profiles_from_quotes("A", quotes[0])
            self.editor_view.set_quote_sample("A", quotes[0])
        self._refresh_media_views()
        self._log_note(f"Загружено txt A: {len(quote_files)}")
        self._log_note(f"Загружено цитат A: {len(quotes)}")

    def _set_quotes_b(self, quote_files: list[Path], quotes: list[str]) -> None:
        self.app_state.media = merge_media_library(
            self.app_state.media,
            quote_files_b=quote_files,
            quotes_b=quotes,
        )
        if quotes:
            self._prime_profiles_from_quotes("B", quotes[0])
            self.editor_view.set_quote_sample("B", quotes[0])
        self._refresh_media_views()
        self._log_note(f"Загружено txt B: {len(quote_files)}")
        self._log_note(f"Загружено цитат B: {len(quotes)}")

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
            paths = filedialog.askopenfilenames(title="Выберите mp3", filetypes=[("MP3 files", "*.mp3")])
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

    def _load_quotes_a_files(self) -> None:
        try:
            file_paths = filedialog.askopenfilenames(title="Выберите txt для слоя A", filetypes=[("Text files", "*.txt")])
            if not file_paths:
                return
            quote_files = load_quote_files(list(file_paths))
            self._set_quotes_a(quote_files, load_quotes_from_files(quote_files))
        except ValidationError as error:
            self._show_error(str(error))

    def _load_quotes_a_folder(self) -> None:
        try:
            folder = filedialog.askdirectory(title="Выберите папку с txt для слоя A")
            if not folder:
                return
            quote_files = load_quote_files_from_folder(folder)
            self._set_quotes_a(quote_files, load_quotes_from_files(quote_files))
        except ValidationError as error:
            self._show_error(str(error))

    def _load_quotes_b_files(self) -> None:
        try:
            file_paths = filedialog.askopenfilenames(title="Выберите txt для слоя B", filetypes=[("Text files", "*.txt")])
            if not file_paths:
                return
            quote_files = load_quote_files(list(file_paths))
            self._set_quotes_b(quote_files, load_quotes_from_files(quote_files))
        except ValidationError as error:
            self._show_error(str(error))

    def _load_quotes_b_folder(self) -> None:
        try:
            folder = filedialog.askdirectory(title="Выберите папку с txt для слоя B")
            if not folder:
                return
            quote_files = load_quote_files_from_folder(folder)
            self._set_quotes_b(quote_files, load_quotes_from_files(quote_files))
        except ValidationError as error:
            self._show_error(str(error))

    def _choose_output_folder(self) -> None:
        folder = filedialog.askdirectory(title="Выберите папку для результатов")
        if not folder:
            return
        root = Path(folder)
        root.mkdir(parents=True, exist_ok=True)
        self.app_state.output_dir = root
        self.editor_view.set_output_directory(self.app_state.output_dir)
        self._log_note(f"Папка вывода: {root}")

    def _select_video(self, path: Path) -> None:
        self._sync_selected_profile_from_editor()
        self.app_state.selected_video = path
        self.editor_view.preview.load_video(path)
        self.editor_view.load_profile(self.app_state.ensure_video_profile(path))

    def _remove_selected_original(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return
        if self.app_state.selected_video is None:
            return

        removed_video = self.app_state.selected_video
        self._sync_selected_profile_from_editor()
        new_selected = self.app_state.remove_original(removed_video)
        self._refresh_media_views()

        if new_selected is not None:
            self.editor_view.preview.load_video(new_selected)
            self.editor_view.load_profile(self.app_state.ensure_video_profile(new_selected))
        else:
            self.editor_view.preview.load_video(None)
            self.editor_view.load_profile(self._current_profile())
        self._log_note(f"Исходник удалён из проекта: {removed_video.name}")

    def _handle_profile_change(self, profile: VideoEditProfile, variation_count: int, enhance_sharpness: bool) -> None:
        self.app_state.generation.variation_count = validate_variation_count(variation_count)
        self.app_state.generation.enhance_sharpness = enhance_sharpness
        self.app_state.set_default_layer_sample("A", profile.layer_a.preview_text)
        self.app_state.set_default_layer_sample("B", profile.layer_b.preview_text)
        if self.app_state.selected_video is not None:
            self.app_state.video_profiles[str(self.app_state.selected_video)] = profile.copy()
            self.app_state.text_style = replace(profile.layer_a)

    def _handle_overlay_change(self, layer: str, style: TextStyle) -> None:
        self.app_state.set_default_layer_sample(layer, style.preview_text)
        if self.app_state.selected_video is None:
            return
        profile = self.app_state.ensure_video_profile(self.app_state.selected_video)
        if layer == "A":
            profile.layer_a = replace(style)
            self.app_state.text_style = replace(style)
        else:
            profile.layer_b = replace(style)

    def _apply_profile_to_all(self) -> None:
        self._sync_selected_profile_from_editor()
        if self.app_state.selected_video is None:
            return
        source_profile = self.app_state.ensure_video_profile(self.app_state.selected_video).copy()
        for path in self.app_state.media.original_videos:
            self.app_state.video_profiles[str(path)] = source_profile.copy()
        self.editor_view.load_profile(source_profile)
        self._log_note("Текущий макет A/B скопирован на все исходники.")

    def _start_generation(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return

        try:
            self._sync_selected_profile_from_editor()
            self.app_state.generation.variation_count = validate_variation_count(self.editor_view.read_variation_count())
            self.app_state.generation.enhance_sharpness = self.editor_view.read_enhance_sharpness()
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
        self._cancel_token = GenerationCancelToken()
        self.editor_view.set_stop_button_state(is_running=True, stop_requested=False)

        state_snapshot = copy.deepcopy(self.app_state)
        self._worker_thread = threading.Thread(
            target=self._run_generation_worker,
            args=(state_snapshot, self._cancel_token),
            daemon=True,
        )
        self._worker_thread.start()

    def _stop_generation(self) -> None:
        if self._cancel_token is None or self._worker_thread is None or not self._worker_thread.is_alive():
            return
        if not self._cancel_token.cancel():
            return
        self.editor_view.set_stop_button_state(is_running=True, stop_requested=True)
        self._push_event(
            GenerationProgressEvent(
                stage="Остановка",
                message="Остановка запрошена. Прерываю текущую операцию и сохраняю уже готовые ролики.",
                progress=0.0,
                level="warning",
            )
        )

    def _threadsafe_progress(self, event: GenerationProgressEvent) -> None:
        self.after(0, lambda: self._push_event(event))

    def _run_generation_worker(self, state_snapshot: AppState, cancel_token: GenerationCancelToken) -> None:
        try:
            generated = self.generator.generate(
                state_snapshot,
                callback=self._threadsafe_progress,
                cancel_token=cancel_token,
            )
            if generated:
                entries, schedule_file = self.export_service.export_schedule(
                    generated,
                    state_snapshot.output_dir,
                    callback=self._threadsafe_progress,
                    cancel_token=cancel_token,
                )
            else:
                entries, schedule_file = [], None
            summary = self.generator.last_summary
            if cancel_token.is_cancelled():
                summary.cancelled = True
                if not summary.cancelled_message:
                    summary.cancelled_message = "Генерация остановлена по запросу пользователя."
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
        lines = [f"Успешно: {generated_count}", f"Пропущено: {summary.failed_count}"]
        if summary.cancelled:
            lines.insert(0, "Остановлено пользователем")
        if summary.soft_accepted_count:
            lines.append(f"Soft-accept: {summary.soft_accepted_count}")
        if summary.warning_count:
            if summary.warning_count == 1:
                lines.append("1 ролик сохранён с предупреждением")
            else:
                lines.append(f"С предупреждениями: {summary.warning_count}")
        if schedule_file is not None:
            lines.append(f"Расписание: {schedule_file.name}")
        if schedule_file is None and generated_count:
            lines.append("Расписание не сохранено")
        return ". ".join(lines)

    def _build_generation_summary_text(
        self,
        generated_count: int,
        summary: GenerationRunSummary,
        schedule_file: Path | None,
    ) -> str:
        lines = [f"Успешно: {generated_count}", f"Пропущено: {summary.failed_count}"]
        if summary.cancelled:
            lines.insert(0, "Остановлено пользователем")
        if summary.skipped_uniqueness_count:
            lines.append(f"Исчерпана уникальность: {summary.skipped_uniqueness_count}")
        if summary.failed_quality_count:
            lines.append(f"Quality-check: {summary.failed_quality_count}")
        if summary.failed_render_count:
            lines.append(f"Render failure: {summary.failed_render_count}")
        if summary.warning_count:
            if summary.warning_count == 1:
                lines.append("1 ролик сохранён с предупреждением")
            else:
                lines.append(f"С предупреждениями: {summary.warning_count}")
        if schedule_file is not None:
            lines.append(f"Расписание: {schedule_file.name}")
        if schedule_file is None and generated_count:
            lines.append("Расписание не сохранено")
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
        self._cancel_token = None
        summary_text = self._build_generation_summary_text(len(generated), summary, schedule_file)
        self._push_event(
            GenerationProgressEvent(
                stage="Остановлено" if summary.cancelled else "Готово",
                message=summary_text,
                progress=1.0,
                level="warning" if summary.cancelled else ("success" if generated else "warning"),
            )
        )
        self.scheduler_view.update_entries(entries, schedule_file)
        self.editor_view.set_generation_enabled(True)
        self.editor_view.set_stop_button_state(is_running=False, stop_requested=False)
        messagebox.showinfo("Остановлено" if summary.cancelled else "Готово", summary_text)

    def _handle_generation_error(self, message: str) -> None:
        self._worker_thread = None
        self._cancel_token = None
        self._push_event(
            GenerationProgressEvent(
                stage="Ошибка",
                message=message,
                progress=0.0,
                level="error",
            )
        )
        self.editor_view.set_generation_enabled(True)
        self.editor_view.set_stop_button_state(is_running=False, stop_requested=False)
        self._show_error(message)
