from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from video_unicalizator.config import SPEED_MAX, SPEED_MIN
from video_unicalizator.core.quality_checker import QualityChecker, QualityReference, QualityReport
from video_unicalizator.core.video_processor import VariationProfile, VideoProcessor
from video_unicalizator.services.music_loader import MusicRotation
from video_unicalizator.state import AppState, GeneratedVariation, GenerationProgressEvent, GenerationSettings
from video_unicalizator.utils.ffmpeg_tools import ffmpeg_available
from video_unicalizator.utils.validation import ValidationError

ProgressCallback = Callable[[GenerationProgressEvent], None]


@dataclass(slots=True)
class RenderAttempt:
    output_video: Path
    profile: VariationProfile
    report: QualityReport
    quote: str
    music_track: Path | None
    snapshot: QualityReference | None
    soft_accepted: bool = False


@dataclass(slots=True)
class FailedVariation:
    source_video: Path
    variation_index: int
    reason: str


@dataclass(slots=True)
class GenerationRunSummary:
    requested_count: int = 0
    success_count: int = 0
    warning_count: int = 0
    soft_accepted_count: int = 0
    failed_variations: list[FailedVariation] = field(default_factory=list)

    @property
    def failed_count(self) -> int:
        return len(self.failed_variations)


class VariationGenerator:
    """Управляет пакетом вариаций и quality gate."""

    def __init__(self) -> None:
        self.video_processor = VideoProcessor()
        self.quality_checker = QualityChecker()
        self.music_rotation = MusicRotation()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.last_summary = GenerationRunSummary()

    def _notify(
        self,
        callback: ProgressCallback | None,
        stage: str,
        message: str,
        progress: float,
        level: str = "info",
        current_file: str | None = None,
        rendered_seconds: float | None = None,
        total_seconds: float | None = None,
        fps: float | None = None,
    ) -> None:
        self.logger.info("%s: %s", stage, message)
        if callback:
            callback(
                GenerationProgressEvent(
                    stage=stage,
                    message=message,
                    progress=progress,
                    level=level,
                    current_file=current_file,
                    rendered_seconds=rendered_seconds,
                    total_seconds=total_seconds,
                    fps=fps,
                )
            )

    def _quality_gate_mode(self, settings: GenerationSettings) -> str:
        if not settings.enforce_quality_gate:
            return "off"
        return settings.quality_gate_mode

    def _build_output_path(
        self,
        source_video: Path,
        variation_index: int,
        output_dir: Path,
        attempt_number: int | None = None,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        suffix = f"_attempt_{attempt_number}" if attempt_number is not None else ""
        return output_dir / f"{source_video.stem}_variation_{variation_index:02d}{suffix}.mp4"

    def _resolve_quotes(self, state: AppState) -> list[str]:
        if state.media.quotes:
            return list(state.media.quotes)
        fallback = state.text_style.preview_text.strip()
        if fallback:
            return [fallback]
        return []

    def _validate_state(self, state: AppState) -> None:
        if not ffmpeg_available():
            raise ValidationError("FFmpeg не найден в PATH. Обработка видео недоступна.")
        if not state.media.original_videos:
            raise ValidationError("Сначала загрузите оригинальные mp4.")

    def _finalize_output(self, attempt_output: Path, final_output: Path) -> Path:
        if final_output.exists():
            final_output.unlink()
        if attempt_output != final_output:
            attempt_output.replace(final_output)
        return final_output

    def _render_with_quality_gate(
        self,
        source_video: Path,
        variation_index: int,
        state: AppState,
        reference_snapshots: list[QualityReference],
        callback: ProgressCallback | None,
        progress_start: float,
        progress_step: float,
        quotes_pool: list[str],
    ) -> RenderAttempt:
        import random

        quality_mode = self._quality_gate_mode(state.generation)
        attempt_limit = 1 if quality_mode == "off" else max(1, state.generation.max_quality_attempts)
        final_output = self._build_output_path(source_video, variation_index, state.variations_output_dir)

        best_soft_attempt: RenderAttempt | None = None
        last_error: Exception | None = None

        for attempt_number in range(1, attempt_limit + 1):
            quote = random.choice(quotes_pool) if quotes_pool else ""
            music_track = self.music_rotation.pick(state.media.music_tracks)
            attempt_output = self._build_output_path(
                source_video,
                variation_index,
                state.variations_output_dir,
                attempt_number=attempt_number,
            )

            last_emit_time = 0.0
            last_emit_progress = -1.0
            emitted_zero = False

            def on_render_progress(
                progress_ratio: float,
                rendered_seconds: float | None,
                total_seconds: float | None,
                fps: float | None,
            ) -> None:
                nonlocal last_emit_time, last_emit_progress, emitted_zero

                now = time.monotonic()
                is_zero_event = (rendered_seconds or 0.0) <= 0.01 and (fps or 0.0) <= 0.01
                should_emit = False
                if progress_ratio >= 1.0:
                    should_emit = True
                elif progress_ratio - last_emit_progress >= 0.01:
                    should_emit = True
                elif now - last_emit_time >= 0.30:
                    should_emit = True
                elif is_zero_event and not emitted_zero:
                    should_emit = True

                if not should_emit:
                    return

                if is_zero_event:
                    if emitted_zero:
                        return
                    emitted_zero = True

                last_emit_time = now
                last_emit_progress = progress_ratio
                total_progress = progress_start + progress_step * 0.88 * progress_ratio
                self._notify(
                    callback,
                    "Рендер",
                    f"Вариация {variation_index}",
                    total_progress,
                    current_file=source_video.name,
                    rendered_seconds=rendered_seconds,
                    total_seconds=total_seconds,
                    fps=fps,
                )

            self._notify(
                callback,
                "Рендер",
                f"Вариация {variation_index}, попытка {attempt_number}",
                progress_start,
                current_file=source_video.name,
            )

            try:
                profile = self.video_processor.render_variation(
                    source_video=source_video,
                    output_video=attempt_output,
                    quote=quote,
                    text_style=state.text_style,
                    color_grade=state.color_grade,
                    music_track=music_track,
                    music_volume=state.generation.music_volume,
                    speed_range=(SPEED_MIN, SPEED_MAX),
                    progress_callback=on_render_progress,
                )
            except Exception as error:  # noqa: BLE001
                last_error = error
                attempt_output.unlink(missing_ok=True)
                if attempt_number >= attempt_limit:
                    break
                self._notify(
                    callback,
                    "Ошибка",
                    f"Вариация {variation_index}: сбой рендера, повторяю попытку. {error}",
                    min(0.99, progress_start + progress_step * 0.9),
                    level="warning",
                    current_file=source_video.name,
                )
                continue

            if quality_mode == "off":
                final_path = self._finalize_output(attempt_output, final_output)
                return RenderAttempt(
                    output_video=final_path,
                    profile=profile,
                    report=QualityReport(
                        sharpness_score=0.0,
                        visual_difference_score=100.0,
                        format_ok=True,
                        warnings=[],
                    ),
                    quote=quote,
                    music_track=music_track,
                    snapshot=None,
                )

            def on_quality_progress(message: str, progress_ratio: float) -> None:
                total_progress = progress_start + progress_step * (0.88 + 0.10 * progress_ratio)
                self._notify(
                    callback,
                    "Проверка качества",
                    f"Вариация {variation_index}: {message}",
                    total_progress,
                    current_file=attempt_output.name,
                )

            report, snapshot = self.quality_checker.evaluate(
                attempt_output,
                reference_snapshots,
                callback=on_quality_progress,
            )
            attempt = RenderAttempt(
                output_video=attempt_output,
                profile=profile,
                report=report,
                quote=quote,
                music_track=music_track,
                snapshot=snapshot,
            )

            if report.passed:
                final_path = self._finalize_output(attempt_output, final_output)
                if snapshot is not None:
                    snapshot.video_path = final_path
                attempt.output_video = final_path
                return attempt

            if quality_mode == "soft" and report.hard_checks_passed:
                if best_soft_attempt is None or report.visual_difference_score >= best_soft_attempt.report.visual_difference_score:
                    if best_soft_attempt is not None:
                        best_soft_attempt.output_video.unlink(missing_ok=True)
                    best_soft_attempt = attempt
                else:
                    attempt_output.unlink(missing_ok=True)
            else:
                attempt_output.unlink(missing_ok=True)

            warning_text = "; ".join(report.warnings) or "Кандидат не прошёл quality gate."
            if attempt_number < attempt_limit:
                self._notify(
                    callback,
                    "Проверка качества",
                    f"Вариация {variation_index}: повтор рендера. {warning_text}",
                    min(0.99, progress_start + progress_step * 0.98),
                    level="warning",
                    current_file=attempt_output.name,
                )

        if quality_mode == "soft" and best_soft_attempt is not None:
            best_soft_attempt.report.warnings.append("Принята после soft quality gate.")
            best_soft_attempt.soft_accepted = True
            final_path = self._finalize_output(best_soft_attempt.output_video, final_output)
            best_soft_attempt.output_video = final_path
            if best_soft_attempt.snapshot is not None:
                best_soft_attempt.snapshot.video_path = final_path
            self._notify(
                callback,
                "Проверка качества",
                f"Вариация {variation_index}: soft-accept после {attempt_limit} попыток",
                min(0.99, progress_start + progress_step * 0.99),
                level="warning",
                current_file=final_output.name,
            )
            return best_soft_attempt

        final_output.unlink(missing_ok=True)
        if last_error is not None:
            raise RuntimeError(f"Вариация {variation_index}: {last_error}") from last_error
        raise RuntimeError(f"Вариация {variation_index}: не прошла quality gate.")

    def generate(self, state: AppState, callback: ProgressCallback | None = None) -> list[GeneratedVariation]:
        self._validate_state(state)
        quotes_pool = self._resolve_quotes(state)

        total_jobs = len(state.media.original_videos) * state.generation.variation_count
        self.last_summary = GenerationRunSummary(requested_count=total_jobs)
        generated: list[GeneratedVariation] = []

        self._notify(callback, "Подготовка", "Проверка ресурсов и параметров генерации.", 0.0)
        self._notify(
            callback,
            "Чтение файлов",
            f"Оригиналов: {len(state.media.original_videos)}, цитат: {len(quotes_pool)}, музыки: {len(state.media.music_tracks)}",
            0.01,
        )

        completed_jobs = 0
        for source_video in state.media.original_videos:
            width, height, _ = self.quality_checker.inspect_video(source_video)
            if width != 1080 or height != 1920:
                self.logger.warning("Оригинал %s будет приведён к 1080x1920 при экспорте.", source_video.name)

            source_references: list[QualityReference] = []
            for variation_number in range(1, state.generation.variation_count + 1):
                progress_start = completed_jobs / total_jobs if total_jobs else 0.0
                progress_step = 1.0 / max(1, total_jobs)

                try:
                    attempt = self._render_with_quality_gate(
                        source_video=source_video,
                        variation_index=variation_number,
                        state=state,
                        reference_snapshots=source_references,
                        callback=callback,
                        progress_start=progress_start,
                        progress_step=progress_step,
                        quotes_pool=quotes_pool,
                    )
                except Exception as error:  # noqa: BLE001
                    reason = str(error)
                    self.last_summary.failed_variations.append(
                        FailedVariation(
                            source_video=source_video,
                            variation_index=variation_number,
                            reason=reason,
                        )
                    )
                    self._notify(
                        callback,
                        "Ошибка",
                        f"Вариация {variation_number} пропущена: {reason}",
                        min(1.0, progress_start + progress_step),
                        level="error",
                        current_file=source_video.name,
                    )
                    completed_jobs += 1
                    if state.generation.continue_on_variation_error:
                        continue
                    raise

                if attempt.snapshot is not None:
                    source_references.append(attempt.snapshot)

                generated.append(
                    GeneratedVariation(
                        source_video=source_video,
                        output_video=attempt.output_video,
                        quote=attempt.quote,
                        music_track=attempt.music_track,
                        speed_factor=attempt.profile.speed_factor,
                        sharpness_score=attempt.report.sharpness_score,
                        visual_difference_score=attempt.report.visual_difference_score,
                        quality_warnings=list(attempt.report.warnings),
                        accepted_after_soft_gate=attempt.soft_accepted,
                    )
                )
                self.last_summary.success_count += 1
                if attempt.report.warnings:
                    self.last_summary.warning_count += 1
                if attempt.soft_accepted:
                    self.last_summary.soft_accepted_count += 1

                completed_jobs += 1
                progress_end = completed_jobs / total_jobs if total_jobs else 1.0
                self._notify(
                    callback,
                    "Рендер",
                    f"Готова вариация {variation_number}",
                    progress_end,
                    level="success",
                    current_file=attempt.output_video.name,
                )

        return generated
