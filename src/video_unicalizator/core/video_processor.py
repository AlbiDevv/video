from __future__ import annotations

import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Sequence

from PIL import Image

from video_unicalizator.config import (
    DEFAULT_AUDIO_CODEC,
    DEFAULT_CRF,
    DEFAULT_FPS,
    DEFAULT_OUTPUT_CODEC,
    DEFAULT_PRESET,
    TARGET_HEIGHT,
    TARGET_WIDTH,
    TIMELINE_FADE_SECONDS,
)
from video_unicalizator.core.text_overlay import OverlayLayout, TextOverlayRenderer
from video_unicalizator.state import (
    ColorGradeProfile,
    GenerationCancelToken,
    GenerationCancelledError,
    RenderedMusicAssignment,
    RenderedQuoteAssignment,
    TextStyle,
)
from video_unicalizator.utils.ffmpeg_tools import ensure_ffmpeg_environment, parse_ffmpeg_progress_time, probe_media
from video_unicalizator.utils.temp_paths import project_temporary_directory

RenderProgressCallback = Callable[[float, float | None, float | None, float | None], None]


FILTER_PRESETS: dict[str, dict[str, float | tuple[int, int, int]]] = {
    "warm": {
        "brightness": 0.035,
        "contrast": 0.08,
        "saturation": 0.11,
        "tint_strength": 0.055,
        "tint_color": (247, 180, 94),
    },
    "cool": {
        "brightness": 0.010,
        "contrast": 0.06,
        "saturation": 0.06,
        "tint_strength": 0.050,
        "tint_color": (96, 164, 245),
    },
    "neutral_contrast": {
        "brightness": 0.0,
        "contrast": 0.12,
        "saturation": 0.05,
        "tint_strength": 0.0,
        "tint_color": (255, 255, 255),
    },
    "sunset": {
        "brightness": 0.030,
        "contrast": 0.10,
        "saturation": 0.14,
        "tint_strength": 0.070,
        "tint_color": (255, 122, 80),
    },
    "clean_cinematic": {
        "brightness": -0.005,
        "contrast": 0.15,
        "saturation": -0.02,
        "tint_strength": 0.040,
        "tint_color": (176, 208, 255),
    },
}

CROP_FAMILY_ZOOM: dict[str, float] = {
    "neutral": 1.00,
    "punch_in": 1.08,
    "tight_crop": 1.14,
}


@dataclass(slots=True)
class VariationProfile:
    speed_factor: float
    brightness_shift: float
    contrast_shift: float
    saturation_shift: float
    filter_preset: str
    trim_start: float
    trim_end: float
    output_duration: float
    target_duration: float
    music_cycle_index: int = 0
    accent_color: tuple[int, int, int] = (255, 255, 255)
    accent_strength: float = 0.0
    crop_family: str = "neutral"
    crop_anchor: str = "center"
    brightness_variant: int = 0
    contrast_variant: int = 0
    saturation_variant: int = 0
    accent_strength_variant: int = 0
    sharpen_enabled: bool = False
    recipe_key: str = ""


@dataclass(slots=True)
class QuoteRenderSegment:
    style: TextStyle
    assignment: RenderedQuoteAssignment


class VideoProcessor:
    """Рендерит вариации роликов локально через ffmpeg."""

    def create_profile(
        self,
        *,
        filter_preset: str,
        speed_factor: float,
        trim_start: float,
        trim_end: float,
        source_duration: float,
        color_grade: ColorGradeProfile,
        music_cycle_index: int = 0,
        brightness_variant: int = 0,
        contrast_variant: int = 0,
        saturation_variant: int = 0,
        accent_strength_variant: int = 0,
        crop_family: str = "neutral",
        crop_anchor: str = "center",
        sharpen_enabled: bool = False,
        recipe_key: str = "",
    ) -> VariationProfile:
        preset_name = filter_preset if filter_preset in FILTER_PRESETS else "neutral_contrast"
        preset = FILTER_PRESETS[preset_name]
        trimmed_duration = max(0.12, source_duration - trim_start - trim_end)
        output_duration = max(0.10, trimmed_duration / max(speed_factor, 0.01))
        brightness_shift = float(preset["brightness"]) + brightness_variant * color_grade.brightness_jitter * 0.50
        contrast_shift = float(preset["contrast"]) + contrast_variant * color_grade.contrast_jitter * 0.45
        saturation_shift = float(preset["saturation"]) + saturation_variant * color_grade.saturation_jitter * 0.45
        accent_strength = float(preset["tint_strength"]) + accent_strength_variant * color_grade.accent_jitter * 0.22
        return VariationProfile(
            speed_factor=speed_factor,
            brightness_shift=max(-0.25, min(0.25, brightness_shift)),
            contrast_shift=max(-0.35, min(0.35, contrast_shift)),
            saturation_shift=max(-0.35, min(0.40, saturation_shift)),
            filter_preset=preset_name,
            trim_start=max(0.0, trim_start),
            trim_end=max(0.0, trim_end),
            output_duration=output_duration,
            target_duration=output_duration,
            music_cycle_index=music_cycle_index,
            accent_color=tuple(int(value) for value in preset["tint_color"]),  # type: ignore[arg-type]
            accent_strength=max(0.0, min(0.18, accent_strength)),
            crop_family=crop_family if crop_family in CROP_FAMILY_ZOOM else "neutral",
            crop_anchor=crop_anchor if crop_anchor in {"center", "top", "bottom"} else "center",
            brightness_variant=brightness_variant,
            contrast_variant=contrast_variant,
            saturation_variant=saturation_variant,
            accent_strength_variant=accent_strength_variant,
            sharpen_enabled=sharpen_enabled,
            recipe_key=recipe_key,
        )

    def render_variation(
        self,
        source_video: Path,
        output_video: Path,
        quote_segments: Sequence[QuoteRenderSegment],
        music_segments: Sequence[RenderedMusicAssignment],
        profile: VariationProfile,
        music_volume: float,
        progress_callback: RenderProgressCallback | None = None,
        enhance_sharpness: bool = False,
        cancel_token: GenerationCancelToken | None = None,
    ) -> VariationProfile:
        media_info = probe_media(source_video)
        if media_info.duration <= 0:
            raise RuntimeError(f"Не удалось определить длительность видео: {source_video.name}")

        output_video.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg_path, _ = ensure_ffmpeg_environment()
        if not ffmpeg_path:
            raise RuntimeError("ffmpeg не найден.")

        with project_temporary_directory(prefix="video_unicalizator_", subdir="render") as temp_dir:
            quote_inputs = self._build_overlay_inputs(temp_dir, quote_segments)
            command = self._build_command(
                ffmpeg_path=ffmpeg_path,
                source_video=source_video,
                quote_inputs=quote_inputs,
                music_segments=music_segments,
                music_volume=music_volume,
                output_video=output_video,
                profile=profile,
                media_info=media_info,
                enhance_sharpness=enhance_sharpness,
            )
            self._run_ffmpeg(command, output_video, profile.output_duration, progress_callback, cancel_token)
        return profile

    def _build_overlay_inputs(
        self,
        temp_dir: Path,
        quote_segments: Sequence[QuoteRenderSegment],
    ) -> list[tuple[Path, RenderedQuoteAssignment]]:
        inputs: list[tuple[Path, RenderedQuoteAssignment]] = []
        for index, segment in enumerate(quote_segments):
            effective_text = segment.assignment.text.strip()
            if not segment.style.enabled or not effective_text or segment.assignment.end_sec <= segment.assignment.start_sec:
                continue
            renderer = TextOverlayRenderer(
                OverlayLayout(width=TARGET_WIDTH, height=TARGET_HEIGHT),
                replace(segment.style, preview_text=effective_text),
                effective_text,
            )
            if renderer.bounds.width <= 0 or renderer.bounds.height <= 0:
                continue
            overlay_path = temp_dir / f"quote_overlay_{index:02d}.png"
            renderer.overlay_image.save(overlay_path)
            inputs.append((overlay_path, segment.assignment))
        return inputs

    def _build_command(
        self,
        *,
        ffmpeg_path: str,
        source_video: Path,
        quote_inputs: list[tuple[Path, RenderedQuoteAssignment]],
        music_segments: Sequence[RenderedMusicAssignment],
        music_volume: float,
        output_video: Path,
        profile: VariationProfile,
        media_info,
        enhance_sharpness: bool,
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

        quote_input_refs: list[tuple[int, RenderedQuoteAssignment]] = []
        music_input_refs: list[tuple[int, RenderedMusicAssignment]] = []
        input_index = 1

        for overlay_path, assignment in quote_inputs:
            quote_input_refs.append((input_index, assignment))
            command.extend(["-loop", "1", "-i", str(overlay_path)])
            input_index += 1

        for assignment in music_segments:
            if assignment.track is None or assignment.end_sec <= assignment.start_sec:
                continue
            music_input_refs.append((input_index, assignment))
            command.extend(["-stream_loop", "-1", "-i", str(assignment.track)])
            input_index += 1

        filter_complex, audio_label = self._build_filter_complex(
            quote_inputs=quote_input_refs,
            music_inputs=music_input_refs,
            music_volume=music_volume,
            profile=profile,
            media_info=media_info,
            enhance_sharpness=enhance_sharpness,
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
                f"{profile.output_duration:.4f}",
                "-progress",
                "pipe:1",
                "-nostats",
                str(output_video),
            ]
        )
        return command

    def _build_filter_complex(
        self,
        *,
        quote_inputs: list[tuple[int, RenderedQuoteAssignment]],
        music_inputs: list[tuple[int, RenderedMusicAssignment]],
        music_volume: float,
        profile: VariationProfile,
        media_info,
        enhance_sharpness: bool,
    ) -> tuple[str, str | None]:
        filters: list[str] = []
        source_end = max(profile.trim_start + 0.12, media_info.duration - profile.trim_end)
        speed_pts = 1.0 / max(profile.speed_factor, 0.01)
        video_steps = [
            f"trim=start={profile.trim_start:.4f}:end={source_end:.4f}",
            "setpts=PTS-STARTPTS",
            f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=increase",
            f"crop={TARGET_WIDTH}:{TARGET_HEIGHT}:x=(in_w-out_w)/2:y=(in_h-out_h)/2",
            "setsar=1",
            f"setpts={speed_pts:.8f}*PTS",
            f"fps={DEFAULT_FPS}",
            (
                f"eq=brightness={profile.brightness_shift:.4f}:"
                f"contrast={1.0 + profile.contrast_shift:.4f}:"
                f"saturation={1.0 + profile.saturation_shift:.4f}"
            ),
        ]
        if enhance_sharpness and profile.sharpen_enabled:
            video_steps.append("unsharp=5:5:0.55:5:5:0.0")
        filters.append(f"[0:v]{','.join(video_steps)}[vbase]")

        video_label = "vbase"
        if profile.accent_strength > 0.0:
            accent_hex = "".join(f"{component:02x}" for component in profile.accent_color)
            filters.append(
                f"color=c=0x{accent_hex}@{profile.accent_strength:.4f}:"
                f"s={TARGET_WIDTH}x{TARGET_HEIGHT}:d={profile.output_duration:.4f},format=rgba[tint]"
            )
            filters.append("[vbase][tint]overlay=0:0:format=auto[vtinted]")
            video_label = "vtinted"

        for index, (input_index, assignment) in enumerate(quote_inputs):
            quote_label = f"qovl{index}"
            output_label = f"vq{index}"
            enable_expr = f"between(t\\,{assignment.start_sec:.3f}\\,{assignment.end_sec:.3f})"
            filters.append(f"[{input_index}:v]format=rgba[{quote_label}]")
            filters.append(
                f"[{video_label}][{quote_label}]overlay=0:0:format=auto:enable='{enable_expr}'[{output_label}]"
            )
            video_label = output_label
        filters.append(f"[{video_label}]format=yuv420p[vout]")

        audio_label: str | None = None
        if media_info.has_audio:
            filters.append(
                f"[0:a]atrim=start={profile.trim_start:.4f}:end={source_end:.4f},"
                f"asetpts=PTS-STARTPTS,"
                f"atempo={profile.speed_factor:.6f},"
                f"aresample=async=1:first_pts=0[voice]"
            )
            audio_label = "voice"

        music_labels: list[str] = []
        for index, (input_index, assignment) in enumerate(music_inputs):
            clip_duration = max(0.0, assignment.end_sec - assignment.start_sec)
            if clip_duration <= 0.0:
                continue
            volume_value = max(0.0, min(2.0, music_volume * assignment.volume))
            track_offset_sec = max(0.0, assignment.track_offset_sec)
            delay_ms = max(0, int(round(assignment.start_sec * 1000)))
            fade_duration = min(TIMELINE_FADE_SECONDS, max(0.0, clip_duration / 2 - 0.02))
            music_label = f"music{index}"
            music_steps = [
                f"volume={volume_value:.4f}",
                f"atrim=start={track_offset_sec:.4f}:duration={clip_duration:.4f}",
                "asetpts=PTS-STARTPTS",
            ]
            if fade_duration > 0.0:
                music_steps.append(f"afade=t=in:st=0:d={fade_duration:.3f}")
                music_steps.append(
                    f"afade=t=out:st={max(0.0, clip_duration - fade_duration):.4f}:d={fade_duration:.3f}"
                )
            music_steps.append(f"adelay={delay_ms}|{delay_ms}")
            music_steps.append("aresample=async=1:first_pts=0")
            filters.append(f"[{input_index}:a]{','.join(music_steps)}[{music_label}]")
            music_labels.append(music_label)

        if music_labels:
            if len(music_labels) == 1:
                filters.append(f"[{music_labels[0]}]anull[musicbus]")
            else:
                inputs = "".join(f"[{label}]" for label in music_labels)
                filters.append(f"{inputs}amix=inputs={len(music_labels)}:normalize=0:duration=longest[musicbus]")

            if audio_label is None:
                filters.append("[musicbus]anull[aout]")
            else:
                filters.append(f"[{audio_label}][musicbus]amix=inputs=2:normalize=0:duration=longest[aout]")
            audio_label = "aout"

        return ";".join(filters), audio_label

    def _run_ffmpeg(
        self,
        command: list[str],
        output_video: Path,
        output_duration: float,
        progress_callback: RenderProgressCallback | None,
        cancel_token: GenerationCancelToken | None,
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
        cancel_requested_during_render = False

        def terminate_process() -> None:
            nonlocal cancel_requested_during_render
            cancel_requested_during_render = True
            if process.poll() is not None:
                return
            try:
                process.terminate()
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
            except OSError:
                return

        if cancel_token is not None:
            cancel_token.register_callback(terminate_process)
        try:
            assert process.stdout is not None
            for raw_line in process.stdout:
                if cancel_token is not None and cancel_token.is_cancelled():
                    cancel_requested_during_render = True
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
            if cancel_token is not None:
                cancel_token.unregister_callback(terminate_process)
            stderr_output = process.stderr.read() if process.stderr is not None else ""
            return_code = process.wait()

        if cancel_requested_during_render:
            output_video.unlink(missing_ok=True)
            raise GenerationCancelledError("Рендер остановлен по запросу пользователя.")

        if return_code != 0:
            raise RuntimeError(stderr_output.strip() or "ffmpeg завершился с ошибкой.")

        if progress_callback:
            progress_callback(1.0, output_duration, output_duration, None)
