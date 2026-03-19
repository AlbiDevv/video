from __future__ import annotations

import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import uuid4


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def project_temp_root(subdir: str | None = None) -> Path:
    root = project_root() / ".tmp"
    if subdir:
        root = root / subdir
    root.mkdir(parents=True, exist_ok=True)
    return root


@contextmanager
def project_temporary_directory(
    *,
    prefix: str = "video_unicalizator_",
    subdir: str = "runtime",
) -> Iterator[Path]:
    base_dir = project_temp_root(subdir)
    temp_dir = base_dir / f"{prefix}{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
