from __future__ import annotations

import tkinter.colorchooser as colorchooser

import customtkinter as ctk


class ColorPickerRow(ctk.CTkFrame):
    """Строка выбора цвета с живым превью."""

    def __init__(self, master, title: str, initial_color: str, on_change, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._on_change = on_change
        self._value = initial_color

        self.grid_columnconfigure(1, weight=1)

        self.label = ctk.CTkLabel(self, text=title, anchor="w")
        self.label.grid(row=0, column=0, padx=(0, 12), pady=4, sticky="w")

        self.preview = ctk.CTkButton(
            self,
            text="",
            width=28,
            height=28,
            fg_color=initial_color,
            hover=False,
            corner_radius=8,
        )
        self.preview.grid(row=0, column=1, padx=(0, 8), pady=4, sticky="e")

        self.button = ctk.CTkButton(self, text="Выбрать", width=110, command=self._choose_color)
        self.button.grid(row=0, column=2, pady=4, sticky="e")

    def _choose_color(self) -> None:
        _, hex_color = colorchooser.askcolor(color=self._value)
        if hex_color:
            self.set_value(hex_color)
            self._on_change(hex_color)

    def get_value(self) -> str:
        return self._value

    def set_value(self, color: str) -> None:
        self._value = color
        self.preview.configure(fg_color=color)

    def set_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.button.configure(state=state)
