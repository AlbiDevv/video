from __future__ import annotations

import time

import customtkinter as ctk

from video_unicalizator.state import GenerationProgressEvent


class GenerationConsole(ctk.CTkFrame):
    """Компактная read-only консоль статуса и логов генерации."""

    def __init__(
        self,
        master,
        title: str = "Статус генерации",
        compact: bool = False,
        start_collapsed: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(
            master,
            corner_radius=20,
            fg_color="#0c1424",
            border_width=1,
            border_color="#16253c",
            **kwargs,
        )
        self._compact = compact
        self._expanded = not start_collapsed

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=14, pady=(12, 8), sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        header.grid_columnconfigure(3, weight=1)

        self.title_label = ctk.CTkLabel(
            header,
            text=title,
            font=ctk.CTkFont(family="Bahnschrift", size=18 if compact else 22, weight="bold"),
            text_color="#f8fafc",
        )
        self.title_label.grid(row=0, column=0, sticky="w")

        self.stage_badge = ctk.CTkLabel(
            header,
            text="Ожидание",
            corner_radius=999,
            fg_color="#1e293b",
            text_color="#cbd5e1",
            padx=12,
            pady=4,
        )
        self.stage_badge.grid(row=0, column=1, padx=(12, 0), sticky="w")

        self.percent_label = ctk.CTkLabel(
            header,
            text="0%",
            text_color="#93c5fd",
            font=ctk.CTkFont(family="Segoe UI", size=12 if compact else 13, weight="bold"),
        )
        self.percent_label.grid(row=0, column=2, padx=(12, 0), sticky="w")

        self.toggle_button = ctk.CTkButton(
            header,
            text="Развернуть" if start_collapsed else "Свернуть",
            width=100,
            height=30,
            corner_radius=12,
            fg_color="#16253c",
            hover_color="#1d3557",
            command=self.toggle,
        )
        self.toggle_button.grid(row=0, column=4, sticky="e")

        self.status_label = ctk.CTkLabel(
            self,
            text="Готово к запуску.",
            text_color="#cbd5e1",
            justify="left",
            anchor="w",
            wraplength=1200,
            font=ctk.CTkFont(family="Segoe UI", size=12 if compact else 13),
        )
        self.status_label.grid(row=1, column=0, padx=14, pady=(0, 8), sticky="ew")

        self.progress = ctk.CTkProgressBar(self, height=10, progress_color="#f97316", fg_color="#172033")
        self.progress.grid(row=2, column=0, padx=14, pady=(0, 10), sticky="ew")
        self.progress.set(0.0)

        self.log_box = ctk.CTkTextbox(
            self,
            corner_radius=16,
            fg_color="#09111f",
            border_width=1,
            border_color="#16253c",
            text_color="#dbe4f0",
            font=ctk.CTkFont(family="Consolas", size=11 if compact else 12),
            height=180 if compact else 300,
            activate_scrollbars=True,
        )
        self.log_box.grid(row=3, column=0, padx=14, pady=(0, 14), sticky="nsew")
        self.log_box.configure(state="disabled")

        self._last_event_key: tuple | None = None
        self._last_event_time = 0.0

        self._apply_expanded_state()

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._apply_expanded_state()

    def _apply_expanded_state(self) -> None:
        self.toggle_button.configure(text="Свернуть" if self._expanded else "Развернуть")
        if self._expanded:
            self.log_box.grid()
        else:
            self.log_box.grid_remove()

    def clear(self) -> None:
        self._append_text("", replace=True)
        self.progress.set(0.0)
        self.percent_label.configure(text="0%")
        self.status_label.configure(text="Готово к запуску.")
        self._set_stage("Ожидание", level="info")
        self._last_event_key = None
        self._last_event_time = 0.0

    def push_event(self, event: GenerationProgressEvent) -> None:
        if self._should_skip_event(event):
            return

        self._set_stage(event.stage, event.level)
        progress_percent = max(0.0, min(100.0, event.progress * 100.0))
        self.percent_label.configure(text=f"{progress_percent:0.0f}%")

        stats_parts: list[str] = []
        if event.current_file:
            stats_parts.append(event.current_file)
        if event.rendered_seconds is not None and event.total_seconds is not None:
            stats_parts.append(f"{event.rendered_seconds:0.1f} / {event.total_seconds:0.1f} c")
        elif event.rendered_seconds is not None:
            stats_parts.append(f"{event.rendered_seconds:0.1f} c")
        elif event.total_seconds is not None:
            stats_parts.append(f"{event.total_seconds:0.1f} c")
        if event.fps is not None:
            stats_parts.append(f"{event.fps:0.1f} fps")

        detail = " | ".join(stats_parts)
        status_text = event.message if not detail else f"{event.message} | {detail}"
        self.status_label.configure(text=status_text)
        self.progress.set(max(0.0, min(1.0, event.progress)))
        self._append_text(f"[{event.timestamp}] {event.stage}: {status_text}\n")
        self._last_event_key = (
            event.stage,
            event.level,
            event.current_file,
            event.message,
            round(event.progress, 3),
            round(event.rendered_seconds or -1.0, 1),
            round(event.total_seconds or -1.0, 1),
            round(event.fps or -1.0, 1),
        )
        self._last_event_time = time.monotonic()

    def push_log(self, line: str) -> None:
        self._append_text(f"{line}\n")

    def set_status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def set_progress(self, value: float) -> None:
        bounded = max(0.0, min(1.0, value))
        self.progress.set(bounded)
        self.percent_label.configure(text=f"{bounded * 100:0.0f}%")

    def _append_text(self, text: str, replace: bool = False) -> None:
        self.log_box.configure(state="normal")
        if replace:
            self.log_box.delete("1.0", "end")
        if text:
            self.log_box.insert("end", text)
            self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _set_stage(self, stage: str, level: str) -> None:
        palette = {
            "info": ("#1d4ed8", "#dbeafe"),
            "warning": ("#b45309", "#ffedd5"),
            "error": ("#b91c1c", "#fee2e2"),
            "success": ("#166534", "#dcfce7"),
        }
        fg_color, text_color = palette.get(level, palette["info"])
        self.stage_badge.configure(text=stage, fg_color=fg_color, text_color=text_color)

    def _should_skip_event(self, event: GenerationProgressEvent) -> bool:
        current_key = (
            event.stage,
            event.level,
            event.current_file,
            event.message,
            round(event.progress, 3),
            round(event.rendered_seconds or -1.0, 1),
            round(event.total_seconds or -1.0, 1),
            round(event.fps or -1.0, 1),
        )
        now = time.monotonic()
        if current_key == self._last_event_key and now - self._last_event_time < 1.0:
            return True

        if event.stage in {"Рендер", "Проверка качества", "Экспорт расписания"} and self._last_event_key is not None:
            same_stage = event.stage == self._last_event_key[0]
            same_file = event.current_file == self._last_event_key[2]
            if same_stage and same_file and now - self._last_event_time < 0.25:
                previous_progress = float(self._last_event_key[4])
                if abs(event.progress - previous_progress) < 0.01 and event.progress < 1.0:
                    return True
        return False
