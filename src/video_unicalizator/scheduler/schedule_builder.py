from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

from video_unicalizator.config import SCHEDULE_INTERVAL_MAX_HOURS, SCHEDULE_INTERVAL_MIN_HOURS
from video_unicalizator.state import GeneratedVariation, ScheduleEntry


class ScheduleBuilder:
    """Создаёт перемешанное расписание публикаций."""

    def build(self, variations: list[GeneratedVariation], start_at: datetime | None = None) -> list[ScheduleEntry]:
        if not variations:
            return []

        shuffled = list(variations)
        random.shuffle(shuffled)
        current_time = start_at or datetime.now().replace(minute=0, second=0, microsecond=0)

        entries: list[ScheduleEntry] = []
        for variation in shuffled:
            entries.append(
                ScheduleEntry(
                    file_name=Path(variation.output_video).name,
                    publish_time=current_time.strftime("%Y-%m-%d %H:%M"),
                )
            )
            hours = random.uniform(SCHEDULE_INTERVAL_MIN_HOURS, SCHEDULE_INTERVAL_MAX_HOURS)
            current_time += timedelta(hours=hours)
        return entries

