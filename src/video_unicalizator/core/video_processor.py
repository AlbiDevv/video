from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from video_unicalizator.config import (
    DEFAULT_AUDIO_CODEC,
    DEFAULT_CRF,
    DEFAULT_OUTPUT_CODEC,
    DEFAULT_PRESET,
    DEFAULT_FPS,
    TARGET_HEIGHT,
    TARGET_WIDTH,
)
from video_unicalizator.core.text_overlay import OverlayLayout, TextOverlayRenderer
from video_unicalizator.state import ColorGradeProfile, TextStyle
from video_unicalizator.utils.ffmpeg_tools import (
    ensure_ffmpeg_environment,
    parse_ffmpeg_progress_time,
    probe_media,
)

RenderProgressCallback = Callable[[float, float | None, float | None, float | None], None]


@dataclass(slots=True)
class VariationProfile:
    speed_factor: float
    brightness_shift: float
    contrast_shift: float
    saturation_shift: float
    accent_color: tuple[int, int, int]
    accent_strength: float


class VideoProcessor:
    """Рендерит одну вариацию ролика локально через ffmpeg."""

    def create_random_profile(self, color_grade: ColorGradeProfile, speed_range: tuple[float, float]) -> VariationProfile:
        import random

        return VariationProfile(
            speed_factor=random.uniform(*speed_range),
            brightness_shift=random.uniform(-color_grade.brightness_jitter, color_grade.brightness_jitter),
            contrast_shift=random.uniform(-color_grade.contrast_jitter, color_grade.contrast_jitter),
            saturation_shift=random.uniform(-color_grade.saturation_jitter, color_grade.saturation_jitter),
            accent_color=tuple(random.randint(12, 220) for _ in range(3)),
            accent_strength=random.uniform(0.03, color_grade.accent_jitter),
        )

    def render_variation(
        self,
        source_video: Path,
        output_video: Path,
        quote: str,
        text_style: TextStyle,
        color_grade: ColorGradeProfile,
        music_track: Path | None,
        music_volume: float,
        speed_range: tuple[float, float],
        progress_callback: RenderProgressCallback | None = None,
    ) -> VariationProfile:
        profile = self.create_random_profile(color_grade, speed_range)
        media_info = probe_media(source_video)
        output_duration = max(0.1, media_info.duration / max(profile.speed_factor, 0.01))

        output_video.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg_path, _ = ensure_ffmpeg_environment()
        if not ffmpeg_path:
            raise RuntimeError("ffmpeg не найден.")

        with tempfile.TemporaryDirectory(prefix="video_unicalizator_") as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            overlay_path = self._build_overlay_file(temp_dir, quote, text_style)
            command = self._build_command(
                ffmpeg_path=ffmpeg_path,
                source_video=source_video,
                overlay_path=overlay_path,
                music_track=music_track,
                music_volume=music_volume,
                output_video=output_video,
                profile=profile,
                media_info=media_info,
                output_duration=output_duration,
            )
            self._run_ffmpeg(command, output_duration, progress_callback)
        return profile

    def _build_overlay_file(self, temp_dir: Path, quote: str, text_style: TextStyle) -> Path | None:
        effective_quote = (quote or text_style.preview_text).strip()
        if not effective_quote:
            return None

        overlay_path = temp_dir / "quote_overlay.png"
        renderer = TextOverlayRenderer(
            OverlayLayout(width=TARGET_WIDTH, height=TARGET_HEIGHT),
            text_style,
            effective_quote,
        )
        renderer.overlay_image.save(overlay_path)
        return overlay_path

    def _build_command(
        self,
        ffmpeg_path: str,
        source_video: Path,
        overlay_path: Path | None,
        music_track: Path | None,
        music_volume: float,
        output_video: Path,
        profile: VariationProfile,
        media_info,
        output_duration: float,
    ) -> list[str]:
        command = [
            ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source_video),
        ]

        input_count = 1
        overlay_input_index: int | None = None
        music_input_index: int | None = None

        if overlay_path is not None:
            overlay_input_index = input_count
            command.extend(["-loop", "1", "-i", str(overlay_path)])
            input_count += 1

        if music_track is not None:
            music_input_index = input_count
            command.extend(["-stream_loop", "-1", "-i", str(music_track)])
            input_count += 1

        filter_complex, audio_label = self._build_filter_complex(
            overlay_input_index=overlay_input_index,
            music_input_index=music_input_index,
            music_volume=music_volume,
            profile=profile,
            media_info=media_info,
            output_duration=output_duration,
        )

        command.extend(["-filter_complex", filter_complex, "-map", "[vout]"])
        if audio_label:
            command.extend(["-map", f"[{audio_label}]", "-c:a", DEFAULT_AUDIO_CODEC])
        else:
            command.append("-an")

        command.extend(
            [
                "-c:v",
                DEFAULT_OUTPUT_CODEC,
                "-preset",
                DEFAULT_PRESET,
                "-crf",
                str(DEFAULT_CRF),
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-t",
                f"{output_duration:.4f}",
                "-progress",
                "pipe:1",
                "-nostats",
                str(output_video),
            ]
        )
        return command

    def _build_filter_complex(
        self,
        overlay_input_index: int | None,
        music_input_index: int | None,
        music_volume: float,
        profile: VariationProfile,
        media_info,
        output_duration: float,
    ) -> tuple[str, str | None]:
        filters: list[str] = []
        video_label = "vbase"
        speed_pts = 1.0 / max(profile.speed_factor, 0.01)
        filters.append(
            "[0:v]"
            f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_WIDTH}:{TARGET_HEIGHT},setsar=1,"
            f"setpts={speed_pts:.8f}*PTS,"
            f"fps={DEFAULT_FPS},"
            f"eq=brightness={profile.brightness_shift:.4f}:contrast={1.0 + profile.contrast_shift:.4f}:"
            f"saturation={1.0 + profile.saturation_shift:.4f}"
            f"[{video_label}]"
        )

        tint_label = video_label
        if profile.accent_strength > 0.0:
            accent_hex = "".join(f"{component:02x}" for component in profile.accent_color)
            filters.append(
                f"color=c=0x{accent_hex}@{profile.accent_strength:.4f}:"
                f"s={TARGET_WIDTH}x{TARGET_HEIGHT}:d={output_duration:.4f},format=rgba[tint]"
            )
            filters.append(f"[{video_label}][tint]overlay=0:0:format=auto[vtinted]")
            tint_label = "vtinted"

        if overlay_input_index is not None:
            filters.append(f"[{overlay_input_index}:v]format=rgba[quote_overlay]")
            filters.append(
                f"[{tint_label}][quote_overlay]overlay=0:0:format=auto:shortest=1:eof_action=pass,format=yuv420p[vout]"
            )
        else:
            filters.append(f"[{tint_label}]format=yuv420p[vout]")

        audio_label: str | None = None
        if media_info.has_audio:
            filters.append(
                f"[0:a]atempo={profile.speed_factor:.6f},"
                f"aresample=async=1:first_pts=0,"
                f"atrim=duration={output_duration:.4f}[voice]"
            )
            audio_label = "voice"

        if music_input_index is not None:
            filters.append(
                f"[{music_input_index}:a]volume={music_volume:.4f},"
                f"atrim=duration={output_duration:.4f},"
                f"aresample=async=1:first_pts=0[music]"
            )
            if audio_label is None:
                filters.append("[music]anull[aout]")
            else:
                filters.append("[voice][music]amix=inputs=2:normalize=0:duration=longest[aout]")
            audio_label = "aout"

        return ";".join(filters), audio_label

    def _run_ffmpeg(
        self,
        command: list[str],
        output_duration: float,
        progress_callback: RenderProgressCallback | None,
    ) -> None:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )

        progress_fields: dict[str, str] = {}
        try:
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                progress_fields[key] = value
                if key != "progress":
                    continue

                rendered_seconds = parse_ffmpeg_progress_time(progress_fields)
                fps_value = None
                fps_raw = progress_fields.get("fps")
                if fps_raw:
                    try:
                        fps_value = float(fps_raw)
                    except ValueError:
                        fps_value = None

                if progress_callback:
                    progress_callback(
                        min(1.0, max(0.0, rendered_seconds / max(output_duration, 0.001))),
                        rendered_seconds,
                        output_duration,
                        fps_value,
                    )
                progress_fields.clear()
        finally:
            stderr_output = process.stderr.read() if process.stderr is not None else ""
            return_code = process.wait()

        if return_code != 0:
            raise RuntimeError(stderr_output.strip() or "ffmpeg завершился с ошибкой.")

        if progress_callback:
            progress_callback(1.0, output_duration, output_duration, None)
