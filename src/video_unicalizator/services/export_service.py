from __future__ import annotations

from pathlib import Path
from typing import Callable

from video_unicalizator.scheduler.excel_exporter import ExcelExporter
from video_unicalizator.scheduler.schedule_builder import ScheduleBuilder
from video_unicalizator.state import GeneratedVariation, GenerationProgressEvent, ScheduleEntry

ProgressCallback = Callable[[GenerationProgressEvent], None]


class ExportService:
    """Связывает генерацию расписания и экспорт в Excel."""

    def __init__(self) -> None:
        self.schedule_builder = ScheduleBuilder()
        self.excel_exporter = ExcelExporter()

    def export_schedule(
        self,
        variations: list[GeneratedVariation],
        output_dir: Path,
        callback: ProgressCallback | None = None,
    ) -> tuple[list[ScheduleEntry], Path]:
        if callback:
            callback(
                GenerationProgressEvent(
                    stage="Экспорт расписания",
                    message="Формирование случайного порядка публикаций.",
                    progress=0.97,
                )
            )

        entries = self.schedule_builder.build(variations)
        if callback:
            callback(
                GenerationProgressEvent(
                    stage="Экспорт расписания",
                    message=f"Подготовлено строк: {len(entries)}",
                    progress=0.985,
                )
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "Расписание_выкладки.xlsx"
        self.excel_exporter.export(entries, output_file)

        if callback:
            callback(
                GenerationProgressEvent(
                    stage="Экспорт расписания",
                    message=f"Excel сохранён: {output_file.name}",
                    progress=1.0,
                    level="success",
                )
            )
        return entries, output_file
