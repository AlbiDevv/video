from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_unicalizator.state import GenerationProgressEvent
from video_unicalizator.ui.widgets.generation_console import GenerationConsole
from video_unicalizator.utils.tk_runtime import ensure_tcl_tk_environment

ensure_tcl_tk_environment()
import customtkinter as ctk


class GenerationConsoleIntegrationTestCase(unittest.TestCase):
    def test_log_box_stays_read_only_after_updates(self) -> None:
        app = ctk.CTk()
        self.addCleanup(app.destroy)

        console = GenerationConsole(app)
        console.pack()
        console.push_event(
            GenerationProgressEvent(
                stage="Рендер",
                message="Тест прогресса",
                progress=0.5,
                rendered_seconds=1.2,
                total_seconds=2.4,
                fps=30.0,
            )
        )
        console.push_log("Дополнительная строка")

        self.assertEqual(console.log_box._textbox.cget("state"), "disabled")

    def test_duplicate_events_do_not_spam_log(self) -> None:
        app = ctk.CTk()
        self.addCleanup(app.destroy)

        console = GenerationConsole(app)
        console.pack()
        event = GenerationProgressEvent(
            stage="Рендер",
            message="Вариация 1",
            progress=0.5,
            current_file="source.mp4",
            rendered_seconds=1.2,
            total_seconds=2.4,
            fps=30.0,
        )
        console.push_event(event)
        console.push_event(event)

        text = console.log_box._textbox.get("1.0", "end")
        self.assertEqual(text.count("Вариация 1"), 1)


if __name__ == "__main__":
    unittest.main()
