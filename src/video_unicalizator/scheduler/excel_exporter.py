from __future__ import annotations

from pathlib import Path

import pandas as pd

from video_unicalizator.state import ScheduleEntry


class ExcelExporter:
    """Экспортирует расписание в Excel."""

    def export(self, entries: list[ScheduleEntry], output_file: Path) -> Path:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        dataframe = pd.DataFrame(
            [
                {
                    "Файл": entry.file_name,
                    "Рекомендуемое время публикации": entry.publish_time,
                }
                for entry in entries
            ]
        )
        dataframe.to_excel(output_file, index=False)
        return output_file

