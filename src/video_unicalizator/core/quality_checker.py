from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from video_unicalizator.config import MIN_SHARPNESS_SCORE, MIN_VISUAL_DIFFERENCE
from video_unicalizator.utils.validation import is_target_vertical_resolution

QualityProgressCallback = Callable[[str, float], None]


@dataclass(slots=True)
class QualityReport:
    sharpness_score: float
    visual_difference_score: float
    format_ok: bool
    duration_seconds: float
    duration_unique: bool
    warnings: list[str] = field(default_factory=list)
    nearest_reference_video: Path | None = None
    nearest_distance_score: float | None = None

    @property
    def hard_checks_passed(self) -> bool:
        return self.format_ok and self.sharpness_score >= MIN_SHARPNESS_SCORE and self.duration_unique

    @property
    def visual_difference_passed(self) -> bool:
        return self.visual_difference_score >= MIN_VISUAL_DIFFERENCE

    @property
    def passed(self) -> bool:
        return self.hard_checks_passed and self.visual_difference_passed


@dataclass(slots=True)
class QualityReference:
    video_path: Path
    sharpness_score: float
    visual_signature: np.ndarray
    format_ok: bool
    duration_seconds: float


class QualityChecker:
    def inspect_video(self, video_path: Path) -> tuple[int, int, float]:
        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise ValueError(f"Не удалось открыть видео: {video_path}")

        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        duration = frame_count / max(fps, 1.0)
        capture.release()
        return width, height, duration

    def analyze_video(
        self,
        video_path: Path,
        sample_frames_sharpness: int = 10,
        sample_frames_signature: int = 8,
    ) -> QualityReference:
        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise ValueError(f"Не удалось открыть видео: {video_path}")

        try:
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
            fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
            duration = frame_count / max(fps, 1.0)

            sharp_positions = np.linspace(
                0,
                max(frame_count - 1, 0),
                num=min(sample_frames_sharpness, frame_count),
                dtype=int,
            )
            signature_positions = np.linspace(
                0,
                max(frame_count - 1, 0),
                num=min(sample_frames_signature, frame_count),
                dtype=int,
            )
            sharp_set = {int(value) for value in sharp_positions.tolist()}
            signature_set = {int(value) for value in signature_positions.tolist()}
            all_positions = sorted(sharp_set | signature_set)

            sharpness_scores: list[float] = []
            signature_chunks: list[np.ndarray] = []

            for position in all_positions:
                capture.set(cv2.CAP_PROP_POS_FRAMES, int(position))
                ok, frame = capture.read()
                if not ok:
                    continue

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if position in sharp_set:
                    sharpness_scores.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
                if position in signature_set:
                    thumb = cv2.resize(gray, (72, 72), interpolation=cv2.INTER_AREA)
                    signature_chunks.append(thumb.astype(np.float32).flatten())

            signature = (
                np.concatenate(signature_chunks)
                if signature_chunks
                else np.zeros(72 * 72 * max(1, sample_frames_signature), dtype=np.float32)
            )

            return QualityReference(
                video_path=video_path,
                sharpness_score=float(np.mean(sharpness_scores)) if sharpness_scores else 0.0,
                visual_signature=signature,
                format_ok=is_target_vertical_resolution(width, height),
                duration_seconds=max(0.0, duration),
            )
        finally:
            capture.release()

    def measure_visual_difference(
        self,
        candidate_signature: np.ndarray,
        references: Sequence[QualityReference],
        callback: QualityProgressCallback | None = None,
    ) -> tuple[float, Path | None]:
        if not references:
            if callback:
                callback("Сравнение не требуется", 1.0)
            return 100.0, None

        nearest_distance = float("inf")
        nearest_reference: Path | None = None
        total = len(references)

        for index, reference in enumerate(references, start=1):
            length = min(len(candidate_signature), len(reference.visual_signature))
            if length == 0:
                continue
            distance = float(
                np.mean(np.abs(candidate_signature[:length] - reference.visual_signature[:length])) / 255.0 * 100.0
            )
            if distance < nearest_distance:
                nearest_distance = distance
                nearest_reference = reference.video_path
            if callback:
                callback(f"Сравнение с {index}/{total} вариациями", index / total)

        if nearest_reference is None:
            return 0.0, None
        return nearest_distance, nearest_reference

    def evaluate(
        self,
        candidate: Path,
        references: Sequence[QualityReference],
        callback: QualityProgressCallback | None = None,
        duration_uniqueness_precision: float = 0.1,
    ) -> tuple[QualityReport, QualityReference]:
        if callback:
            callback("Анализ резкости и сигнатуры", 0.08)

        snapshot = self.analyze_video(candidate)

        if callback:
            callback("Сигнатура готова", 0.26)

        difference, nearest_reference = self.measure_visual_difference(
            snapshot.visual_signature,
            references,
            callback=(lambda message, progress: callback(message, 0.26 + progress * 0.56)) if callback else None,
        )

        rounded_duration = round(snapshot.duration_seconds / max(duration_uniqueness_precision, 0.01))
        reference_durations = {
            round(reference.duration_seconds / max(duration_uniqueness_precision, 0.01))
            for reference in references
        }
        duration_unique = rounded_duration not in reference_durations

        if callback:
            callback("Формирование отчёта", 1.0)

        warnings: list[str] = []
        if not snapshot.format_ok:
            warnings.append("Формат видео отличается от 1080x1920.")
        if snapshot.sharpness_score < MIN_SHARPNESS_SCORE:
            warnings.append("Резкость ниже рекомендуемого порога.")
        if not duration_unique:
            warnings.append("Длительность слишком похожа на уже принятую вариацию.")
        if references and difference < MIN_VISUAL_DIFFERENCE:
            warnings.append("Визуальная разница между вариациями слишком мала.")

        return (
            QualityReport(
                sharpness_score=snapshot.sharpness_score,
                visual_difference_score=difference,
                format_ok=snapshot.format_ok,
                duration_seconds=snapshot.duration_seconds,
                duration_unique=duration_unique,
                warnings=warnings,
                nearest_reference_video=nearest_reference,
                nearest_distance_score=difference if nearest_reference is not None else None,
            ),
            snapshot,
        )
