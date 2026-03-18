from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from video_unicalizator.config import MIN_SHARPNESS_SCORE
from video_unicalizator.core.quality_checker import QualityChecker, QualityReference, QualityReport
from video_unicalizator.core.recipe_planner import (
    PlannedRecipeCandidate,
    SourceUniquenessLedger,
    VariationRecipePlanner,
)
from video_unicalizator.core.video_processor import VariationProfile, VideoProcessor
from video_unicalizator.services.music_loader import MusicChoice, MusicRotation
from video_unicalizator.state import (
    AppState,
    GeneratedVariation,
    GenerationCancelToken,
    GenerationCancelledError,
    GenerationProgressEvent,
    GenerationSettings,
    VideoEditProfile,
)
from video_unicalizator.utils.ffmpeg_tools import ffmpeg_available
from video_unicalizator.utils.validation import ValidationError

ProgressCallback = Callable[[GenerationProgressEvent], None]


class UniquenessExhaustedError(RuntimeError):
    pass


class QualityGateFailure(RuntimeError):
    pass


class RenderFailure(RuntimeError):
    pass


@dataclass(slots=True)
class RenderAttempt:
    output_video: Path
    profile: VariationProfile
    report: QualityReport
    primary_quote: str
    secondary_quote: str
    music_track: Path | None
    snapshot: QualityReference | None
    soft_accepted: bool = False


@dataclass(slots=True)
class FailedVariation:
    source_video: Path
    variation_index: int
    reason: str
    reason_code: str = "other"


@dataclass(slots=True)
class GenerationRunSummary:
    requested_count: int = 0
    success_count: int = 0
    warning_count: int = 0
    soft_accepted_count: int = 0
    skipped_uniqueness_count: int = 0
    failed_quality_count: int = 0
    failed_render_count: int = 0
    cancelled: bool = False
    cancelled_message: str = ""
    failed_variations: list[FailedVariation] = field(default_factory=list)

    @property
    def failed_count(self) -> int:
        return len(self.failed_variations)


class VariationGenerator:
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

    def _validate_state(self, state: AppState) -> None:
        if not ffmpeg_available():
            raise ValidationError("FFmpeg не найден в PATH. Обработка видео недоступна.")
        if not state.media.original_videos:
            raise ValidationError("Сначала загрузите оригинальные mp4.")

    def _check_cancel(self, cancel_token: GenerationCancelToken | None) -> None:
        if cancel_token is not None:
            cancel_token.throw_if_cancelled()

    def _mark_cancelled(
        self,
        callback: ProgressCallback | None,
        progress: float,
        message: str = "Генерация остановлена по запросу пользователя.",
    ) -> None:
        self.last_summary.cancelled = True
        self.last_summary.cancelled_message = message
        self._notify(callback, "Остановлено", message, progress, level="warning")

    def _finalize_output(self, attempt_output: Path, final_output: Path) -> Path:
        if final_output.exists():
            final_output.unlink()
        if attempt_output != final_output:
            attempt_output.replace(final_output)
        return final_output

    def _video_profile_for(self, state: AppState, source_video: Path) -> VideoEditProfile:
        return state.ensure_video_profile(source_video)

    def _resolve_quote_pool(self, quotes: list[str], fallback_text: str, enabled: bool) -> list[str]:
        if not enabled:
            return []
        if quotes:
            return list(quotes)
        fallback = fallback_text.strip()
        return [fallback] if fallback else []

    def _resolve_quote_pools(self, state: AppState, profile: VideoEditProfile) -> tuple[list[str], list[str]]:
        return (
            self._resolve_quote_pool(state.media.quotes_a, profile.layer_a.preview_text, profile.layer_a.enabled),
            self._resolve_quote_pool(state.media.quotes_b, profile.layer_b.preview_text, profile.layer_b.enabled),
        )

    def _warning_reason_codes(self, warnings: list[str]) -> list[str]:
        codes: list[str] = []
        for warning in warnings:
            lowered = warning.lower()
            if "формат" in lowered:
                codes.append("format")
            elif "резкость" in lowered:
                codes.append("sharpness")
            elif "длительность" in lowered:
                codes.append("duration")
            elif "визуальная" in lowered:
                codes.append("visual_difference")
            else:
                codes.append("other")
        return codes

    def _pick_quote(self, pool: list[str], rng: random.Random) -> str:
        if not pool:
            return ""
        return rng.choice(pool)

    def _recipe_message(self, candidate: PlannedRecipeCandidate) -> str:
        nearest = candidate.distance.nearest_recipe_key
        if not nearest:
            return f"Ищу новый recipe: {candidate.recipe.short_label()}"
        factors = ", ".join(candidate.distance.nearest_factors[:3]) or "visual_signature"
        return f"Ищу новый recipe: {candidate.recipe.short_label()} | далеко от {nearest} по {factors}"

    def _build_profile_from_candidate(
        self,
        *,
        candidate: PlannedRecipeCandidate,
        state: AppState,
        source_duration: float,
    ) -> VariationProfile:
        recipe = candidate.recipe
        return self.video_processor.create_profile(
            filter_preset=recipe.filter_preset,
            speed_factor=recipe.speed_factor,
            trim_start=recipe.trim_start,
            trim_end=recipe.trim_end,
            source_duration=source_duration,
            color_grade=state.color_grade,
            music_cycle_index=recipe.music_cycle_index,
            brightness_variant=recipe.brightness_variant,
            contrast_variant=recipe.contrast_variant,
            saturation_variant=recipe.saturation_variant,
            accent_strength_variant=recipe.accent_strength_variant,
            crop_family=recipe.crop_family,
            crop_anchor=recipe.crop_anchor,
            sharpen_enabled=recipe.sharpen_enabled,
            recipe_key=recipe.recipe_key,
        )

    def _render_with_quality_gate(
        self,
        *,
        source_video: Path,
        variation_index: int,
        state: AppState,
        reference_snapshots: list[QualityReference],
        callback: ProgressCallback | None,
        progress_start: float,
        progress_step: float,
        source_duration: float,
        profile: VideoEditProfile,
        primary_pool: list[str],
        secondary_pool: list[str],
        planner: VariationRecipePlanner,
        ledger: SourceUniquenessLedger,
        quote_rng: random.Random,
        cancel_token: GenerationCancelToken | None,
    ) -> RenderAttempt:
        self._check_cancel(cancel_token)
        quality_mode = self._quality_gate_mode(state.generation)
        render_attempt_limit = 1 if quality_mode == "off" else max(1, state.generation.render_retry_attempts)
        final_output = self._build_output_path(source_video, variation_index, state.output_dir)

        last_render_error: Exception | None = None
        last_quality_report: QualityReport | None = None

        for attempt_number in range(1, render_attempt_limit + 1):
            self._check_cancel(cancel_token)
            music_choice: MusicChoice = self.music_rotation.preview_for_accept_index(
                state.media.music_tracks,
                self.last_summary.success_count,
            )
            candidate = planner.next_recipe(ledger, music_choice)
            if candidate is None:
                raise UniquenessExhaustedError(
                    f"Вариация {variation_index}: уникальные комбинации исчерпаны."
                )

            variation_profile = self._build_profile_from_candidate(
                candidate=candidate,
                state=state,
                source_duration=source_duration,
            )
            primary_quote = self._pick_quote(primary_pool, quote_rng)
            secondary_quote = self._pick_quote(secondary_pool, quote_rng)

            attempt_output = self._build_output_path(
                source_video,
                variation_index,
                state.output_dir,
                attempt_number=attempt_number,
            )

            self._notify(
                callback,
                "Подбор recipe",
                self._recipe_message(candidate),
                progress_start,
                current_file=source_video.name,
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

                self._check_cancel(cancel_token)
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
                if is_zero_event and emitted_zero:
                    return
                if is_zero_event:
                    emitted_zero = True

                last_emit_time = now
                last_emit_progress = progress_ratio
                total_progress = progress_start + progress_step * 0.84 * progress_ratio
                self._notify(
                    callback,
                    "Рендер",
                    f"Вариация {variation_index}: {variation_profile.filter_preset}, попытка {attempt_number}",
                    total_progress,
                    current_file=source_video.name,
                    rendered_seconds=rendered_seconds,
                    total_seconds=total_seconds,
                    fps=fps,
                )

            try:
                self.video_processor.render_variation(
                    source_video=source_video,
                    output_video=attempt_output,
                    quote_layers=[
                        (replace(profile.layer_a, preview_text=primary_quote), primary_quote),
                        (replace(profile.layer_b, preview_text=secondary_quote), secondary_quote),
                    ],
                    profile=variation_profile,
                    music_track=music_choice.track,
                    music_volume=state.generation.music_volume,
                    progress_callback=on_render_progress,
                    enhance_sharpness=state.generation.enhance_sharpness,
                    cancel_token=cancel_token,
                )
            except GenerationCancelledError:
                attempt_output.unlink(missing_ok=True)
                raise
            except Exception as error:  # noqa: BLE001
                last_render_error = error
                attempt_output.unlink(missing_ok=True)
                self._notify(
                    callback,
                    "Ошибка",
                    f"Вариация {variation_index}: сбой рендера для recipe {candidate.recipe.recipe_key}. Ищу новый кандидат.",
                    min(0.99, progress_start + progress_step * 0.88),
                    level="warning",
                    current_file=source_video.name,
                )
                continue

            if quality_mode == "off":
                final_path = self._finalize_output(attempt_output, final_output)
                ledger.record_accepted(candidate.recipe)
                return RenderAttempt(
                    output_video=final_path,
                    profile=variation_profile,
                    report=QualityReport(
                        sharpness_score=0.0,
                        visual_difference_score=100.0,
                        format_ok=True,
                        duration_seconds=variation_profile.output_duration,
                        duration_unique=True,
                        warnings=[],
                    ),
                    primary_quote=primary_quote,
                    secondary_quote=secondary_quote,
                    music_track=music_choice.track,
                    snapshot=None,
                )

            def on_quality_progress(message: str, progress_ratio: float) -> None:
                self._check_cancel(cancel_token)
                total_progress = progress_start + progress_step * (0.84 + 0.14 * progress_ratio)
                self._notify(
                    callback,
                    "Проверка качества",
                    f"Вариация {variation_index}: {message}",
                    total_progress,
                    current_file=attempt_output.name,
                )

            try:
                report, snapshot = self.quality_checker.evaluate(
                    attempt_output,
                    reference_snapshots,
                    callback=on_quality_progress,
                    duration_uniqueness_precision=state.generation.duration_uniqueness_precision,
                )
            except GenerationCancelledError:
                attempt_output.unlink(missing_ok=True)
                raise

            if report.passed:
                final_path = self._finalize_output(attempt_output, final_output)
                if snapshot is not None:
                    snapshot.video_path = final_path
                ledger.record_accepted(candidate.recipe)
                return RenderAttempt(
                    output_video=final_path,
                    profile=variation_profile,
                    report=report,
                    primary_quote=primary_quote,
                    secondary_quote=secondary_quote,
                    music_track=music_choice.track,
                    snapshot=snapshot,
                )

            attempt_output.unlink(missing_ok=True)
            ledger.record_rejected(candidate.recipe)
            last_quality_report = report
            nearest_name = report.nearest_reference_video.name if report.nearest_reference_video is not None else "нет"
            close_factors = ", ".join(candidate.distance.nearest_factors[:4]) or "visual_signature"
            warning_text = "; ".join(report.warnings) or "Кандидат не прошёл quality gate."
            self._notify(
                callback,
                "Проверка качества",
                (
                    f"Вариация {variation_index}: recipe отклонён. "
                    f"Ближайший референс: {nearest_name}. "
                    f"Слишком близко по {close_factors}. {warning_text}"
                ),
                min(0.99, progress_start + progress_step * 0.98),
                level="warning",
                current_file=source_video.name,
            )

        final_output.unlink(missing_ok=True)
        if last_quality_report is not None:
            nearest_name = (
                last_quality_report.nearest_reference_video.name
                if last_quality_report.nearest_reference_video is not None
                else "нет"
            )
            raise QualityGateFailure(
                f"Вариация {variation_index}: не удалось собрать достаточно отличающийся ролик. "
                f"Ближайший референс: {nearest_name}."
            )
        if last_render_error is not None:
            raise RenderFailure(f"Вариация {variation_index}: {last_render_error}") from last_render_error
        raise UniquenessExhaustedError(f"Вариация {variation_index}: уникальные комбинации исчерпаны.")

    def generate(
        self,
        state: AppState,
        callback: ProgressCallback | None = None,
        cancel_token: GenerationCancelToken | None = None,
    ) -> list[GeneratedVariation]:
        self._validate_state(state)
        self.music_rotation.reset()
        if cancel_token is not None and cancel_token.is_cancelled():
            self.last_summary = GenerationRunSummary(
                requested_count=0,
                cancelled=True,
                cancelled_message="Генерация остановлена по запросу пользователя.",
            )
            return []

        total_jobs = len(state.media.original_videos) * state.generation.variation_count
        self.last_summary = GenerationRunSummary(requested_count=total_jobs)
        generated: list[GeneratedVariation] = []

        self._notify(callback, "Подготовка", "Проверка ресурсов и параметров генерации.", 0.0)
        self._notify(
            callback,
            "Чтение файлов",
            (
                f"Оригиналов: {len(state.media.original_videos)}, "
                f"цитат A: {len(state.media.quotes_a)}, "
                f"цитат B: {len(state.media.quotes_b)}, "
                f"музыки: {len(state.media.music_tracks)}"
            ),
            0.01,
        )

        completed_jobs = 0
        for source_video in state.media.original_videos:
            if cancel_token is not None and cancel_token.is_cancelled():
                self._mark_cancelled(callback, completed_jobs / total_jobs if total_jobs else 1.0)
                return generated

            width, height, source_duration = self.quality_checker.inspect_video(source_video)
            if width != 1080 or height != 1920:
                self.logger.warning("Оригинал %s будет приведён к 1080x1920 при экспорте.", source_video.name)

            profile = self._video_profile_for(state, source_video)
            primary_pool, secondary_pool = self._resolve_quote_pools(state, profile)
            reference_snapshots: list[QualityReference] = []
            ledger = SourceUniquenessLedger()
            planner = VariationRecipePlanner(
                source_video=source_video,
                source_duration=source_duration,
                settings=state.generation,
                color_grade=state.color_grade,
            )
            quote_rng = random.Random(f"{source_video}|{len(primary_pool)}|{len(secondary_pool)}")
            source_exhausted = False

            for variation_number in range(1, state.generation.variation_count + 1):
                if source_exhausted:
                    break
                if cancel_token is not None and cancel_token.is_cancelled():
                    self._mark_cancelled(callback, completed_jobs / total_jobs if total_jobs else 1.0)
                    return generated

                progress_start = completed_jobs / total_jobs if total_jobs else 0.0
                progress_step = 1.0 / max(1, total_jobs)

                try:
                    attempt = self._render_with_quality_gate(
                        source_video=source_video,
                        variation_index=variation_number,
                        state=state,
                        reference_snapshots=reference_snapshots,
                        callback=callback,
                        progress_start=progress_start,
                        progress_step=progress_step,
                        source_duration=source_duration,
                        profile=profile,
                        primary_pool=primary_pool,
                        secondary_pool=secondary_pool,
                        planner=planner,
                        ledger=ledger,
                        quote_rng=quote_rng,
                        cancel_token=cancel_token,
                    )
                except GenerationCancelledError as error:
                    self._mark_cancelled(callback, progress_start, str(error))
                    return generated
                except UniquenessExhaustedError as error:
                    remaining_slots = state.generation.variation_count - variation_number + 1
                    self.last_summary.skipped_uniqueness_count += remaining_slots
                    self.last_summary.failed_variations.extend(
                        FailedVariation(
                            source_video=source_video,
                            variation_index=index,
                            reason="Уникальные комбинации исчерпаны.",
                            reason_code="uniqueness_exhausted",
                        )
                        for index in range(variation_number, state.generation.variation_count + 1)
                    )
                    completed_jobs += remaining_slots
                    source_exhausted = True
                    self._notify(
                        callback,
                        "Подбор recipe",
                        (
                            f"{source_video.name}: уникальные комбинации исчерпаны, "
                            f"пропускаю ещё {remaining_slots} вариаций."
                        ),
                        min(1.0, completed_jobs / total_jobs if total_jobs else 1.0),
                        level="warning",
                        current_file=source_video.name,
                    )
                    break
                except QualityGateFailure as error:
                    self.last_summary.failed_quality_count += 1
                    self.last_summary.failed_variations.append(
                        FailedVariation(
                            source_video=source_video,
                            variation_index=variation_number,
                            reason=str(error),
                            reason_code="quality_gate",
                        )
                    )
                    self._notify(
                        callback,
                        "Ошибка",
                        f"Вариация {variation_number} пропущена: {error}",
                        min(1.0, progress_start + progress_step),
                        level="warning",
                        current_file=source_video.name,
                    )
                    completed_jobs += 1
                    if state.generation.continue_on_variation_error:
                        continue
                    raise
                except RenderFailure as error:
                    self.last_summary.failed_render_count += 1
                    self.last_summary.failed_variations.append(
                        FailedVariation(
                            source_video=source_video,
                            variation_index=variation_number,
                            reason=str(error),
                            reason_code="render_failure",
                        )
                    )
                    self._notify(
                        callback,
                        "Ошибка",
                        f"Вариация {variation_number} пропущена: {error}",
                        min(1.0, progress_start + progress_step),
                        level="error",
                        current_file=source_video.name,
                    )
                    completed_jobs += 1
                    if state.generation.continue_on_variation_error:
                        continue
                    raise
                except Exception as error:  # noqa: BLE001
                    self.last_summary.failed_render_count += 1
                    self.last_summary.failed_variations.append(
                        FailedVariation(
                            source_video=source_video,
                            variation_index=variation_number,
                            reason=str(error),
                            reason_code="other",
                        )
                    )
                    self._notify(
                        callback,
                        "Ошибка",
                        f"Вариация {variation_number} пропущена: {error}",
                        min(1.0, progress_start + progress_step),
                        level="error",
                        current_file=source_video.name,
                    )
                    completed_jobs += 1
                    if state.generation.continue_on_variation_error:
                        continue
                    raise

                if attempt.snapshot is not None:
                    reference_snapshots.append(attempt.snapshot)

                generated.append(
                    GeneratedVariation(
                        source_video=source_video,
                        output_video=attempt.output_video,
                        quote=attempt.primary_quote or attempt.secondary_quote,
                        music_track=attempt.music_track,
                        speed_factor=attempt.profile.speed_factor,
                        sharpness_score=attempt.report.sharpness_score,
                        visual_difference_score=attempt.report.visual_difference_score,
                        quality_warnings=list(attempt.report.warnings),
                        accepted_after_soft_gate=False,
                        primary_quote=attempt.primary_quote,
                        secondary_quote=attempt.secondary_quote,
                        music_cycle_index=attempt.profile.music_cycle_index,
                        filter_preset=attempt.profile.filter_preset,
                        trim_start=attempt.profile.trim_start,
                        trim_end=attempt.profile.trim_end,
                        output_duration=attempt.profile.output_duration,
                        warning_reason_codes=self._warning_reason_codes(attempt.report.warnings),
                        recipe_key=attempt.profile.recipe_key,
                        nearest_reference_video=attempt.report.nearest_reference_video,
                        nearest_distance_score=attempt.report.nearest_distance_score,
                    )
                )
                self.last_summary.success_count += 1
                if attempt.report.warnings:
                    self.last_summary.warning_count += 1

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
