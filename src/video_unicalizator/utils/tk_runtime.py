from __future__ import annotations

import os
import sys
from pathlib import Path


def ensure_tcl_tk_environment() -> None:
    """Подставляет TCL/TK пути для Windows-виртуальных окружений, где tkinter не нашёл init.tcl."""

    base_prefix = Path(sys.base_prefix)
    tcl_root = base_prefix / "tcl"
    tcl_library = tcl_root / "tcl8.6"
    tk_library = tcl_root / "tk8.6"

    if "TCL_LIBRARY" not in os.environ and (tcl_library / "init.tcl").exists():
        os.environ["TCL_LIBRARY"] = str(tcl_library)
    if "TK_LIBRARY" not in os.environ and (tk_library / "tk.tcl").exists():
        os.environ["TK_LIBRARY"] = str(tk_library)
