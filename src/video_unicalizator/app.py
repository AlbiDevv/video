from __future__ import annotations

from video_unicalizator.paths import ensure_runtime_dirs
from video_unicalizator.services.logger import configure_logging
from video_unicalizator.utils.ffmpeg_tools import ensure_ffmpeg_environment


def main() -> None:
    ensure_runtime_dirs()
    ensure_ffmpeg_environment()
    configure_logging()

    from video_unicalizator.ui.main_window import VideoUnicalizatorApp

    app = VideoUnicalizatorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
