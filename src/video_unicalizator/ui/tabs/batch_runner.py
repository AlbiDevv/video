from __future__ import annotations

import customtkinter as ctk

from video_unicalizator.state import GenerationProgressEvent
from video_unicalizator.ui.widgets.generation_console import GenerationConsole


class BatchRunnerTab(ctk.CTkFrame):
    """Экран истории пакетной генерации."""

    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.title_label = ctk.CTkLabel(
            self,
            text="История генерации",
            font=ctk.CTkFont(family="Bahnschrift", size=24, weight="bold"),
            text_color="#f8fafc",
        )
        self.title_label.grid(row=0, column=0, padx=16, pady=(14, 8), sticky="w")

        self.console = GenerationConsole(self, title="Журнал рендера", compact=False, start_collapsed=False)
        self.console.grid(row=1, column=0, padx=16, pady=(0, 16), sticky="nsew")

    def clear(self) -> None:
        self.console.clear()

    def push_event(self, event: GenerationProgressEvent) -> None:
        self.console.push_event(event)

    def push_log(self, line: str) -> None:
        self.console.push_log(line)

    def set_status(self, text: str) -> None:
        self.console.set_status(text)

    def set_progress(self, value: float) -> None:
        self.console.set_progress(value)
