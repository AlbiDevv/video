from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    spec_file = project_root / "pyinstaller.spec"
    base_prefix = Path(sys.base_prefix)
    tcl_root = base_prefix / "tcl"
    env = os.environ.copy()

    tcl_library = tcl_root / "tcl8.6"
    tk_library = tcl_root / "tk8.6"
    if (tcl_library / "init.tcl").exists():
        env["TCL_LIBRARY"] = str(tcl_library)
    if (tk_library / "tk.tcl").exists():
        env["TK_LIBRARY"] = str(tk_library)

    command = [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", str(spec_file)]
    return subprocess.call(command, cwd=project_root, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
