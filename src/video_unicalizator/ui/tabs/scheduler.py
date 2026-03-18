from __future__ import annotations

import os
import tkinter.ttk as ttk
from pathlib import Path

import customtkinter as ctk

from video_unicalizator.state import ScheduleEntry


class SchedulerTab(ctk.CTkFrame):
    """Экран таблицы публикаций."""

    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._schedule_file: Path | None = None

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=16, pady=(14, 10), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        self.title_label = ctk.CTkLabel(
            header,
            text="Расписание публикаций",
            font=ctk.CTkFont(family="Bahnschrift", size=24, weight="bold"),
            text_color="#f8fafc",
        )
        self.title_label.grid(row=0, column=0, sticky="w")

        self.subtitle_label = ctk.CTkLabel(
            header,
            text="Excel будет создан автоматически после генерации вариаций.",
            text_color="#cbd5e1",
        )
        self.subtitle_label.grid(row=1, column=0, pady=(4, 0), sticky="w")

        self.open_button = ctk.CTkButton(header, text="Открыть Excel", command=self._open_schedule_file)
        self.open_button.grid(row=0, column=1, rowspan=2, sticky="e")
        self.open_button.configure(state="disabled")

        tree_frame = ctk.CTkFrame(self, corner_radius=18, fg_color="#0b1320", border_width=1, border_color="#16253c")
        tree_frame.grid(row=1, column=0, padx=16, pady=(0, 16), sticky="nsew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "Schedule.Treeview",
            background="#0b1320",
            foreground="#e5e7eb",
            fieldbackground="#0b1320",
            borderwidth=0,
            rowheight=34,
        )
        style.configure("Schedule.Treeview.Heading", background="#16253c", foreground="#f8fafc")
        style.map("Schedule.Treeview", background=[("selected", "#2563eb")])

        self.tree = ttk.Treeview(
            tree_frame,
            columns=("file_name", "publish_time"),
            show="headings",
            style="Schedule.Treeview",
        )
        self.tree.heading("file_name", text="Файл")
        self.tree.heading("publish_time", text="Рекомендуемое время")
        self.tree.column("file_name", width=420, anchor="w")
        self.tree.column("publish_time", width=220, anchor="center")
        self.tree.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

    def update_entries(self, entries: list[ScheduleEntry], schedule_file: Path | None) -> None:
        self.tree.delete(*self.tree.get_children())
        for entry in entries:
            self.tree.insert("", "end", values=(entry.file_name, entry.publish_time))
        self._schedule_file = schedule_file
        if schedule_file is not None:
            self.subtitle_label.configure(text=f"Excel: {schedule_file.name}")
            self.open_button.configure(state="normal")
        else:
            self.subtitle_label.configure(text="Excel будет создан автоматически после генерации вариаций.")
            self.open_button.configure(state="disabled")

    def _open_schedule_file(self) -> None:
        if self._schedule_file and self._schedule_file.exists():
            os.startfile(self._schedule_file)  # type: ignore[attr-defined]
