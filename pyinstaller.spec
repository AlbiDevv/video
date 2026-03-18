# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

project_root = Path.cwd()
base_prefix = Path(sys.base_prefix)
tcl_root = base_prefix / "tcl"
tcl_library = tcl_root / "tcl8.6"
tk_library = tcl_root / "tk8.6"

block_cipher = None

if (tcl_library / "init.tcl").exists():
    os.environ["TCL_LIBRARY"] = str(tcl_library)
if (tk_library / "tk.tcl").exists():
    os.environ["TK_LIBRARY"] = str(tk_library)

datas = []
assets_root = project_root / "assets"
if assets_root.exists():
    for file_path in assets_root.rglob("*"):
        if not file_path.is_file():
            continue
        relative_dir = file_path.parent.relative_to(project_root)
        datas.append((str(file_path), relative_dir.as_posix()))

if tcl_library.exists():
    for file_path in tcl_library.rglob("*"):
        if file_path.is_file():
            relative_dir = file_path.parent.relative_to(tcl_library)
            target_dir = "tcl/tcl8.6"
            if str(relative_dir) != ".":
                target_dir = f"{target_dir}/{relative_dir.as_posix()}"
            datas.append((str(file_path), target_dir))
if tk_library.exists():
    for file_path in tk_library.rglob("*"):
        if file_path.is_file():
            relative_dir = file_path.parent.relative_to(tk_library)
            target_dir = "tcl/tk8.6"
            if str(relative_dir) != ".":
                target_dir = f"{target_dir}/{relative_dir.as_posix()}"
            datas.append((str(file_path), target_dir))

for package_name in (
    "imageio",
    "imageio-ffmpeg",
    "moviepy",
    "numpy",
    "pandas",
    "openpyxl",
    "customtkinter",
    "pillow",
    "ffmpeg-python",
):
    datas += copy_metadata(package_name)

analysis = Analysis(
    ["src/video_unicalizator/app.py"],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "_tkinter",
        "customtkinter",
        "PIL",
        "cv2",
        "moviepy",
        "pandas",
        "openpyxl",
        "tkinter",
        "tkinter.colorchooser",
        "tkinter.constants",
        "tkinter.filedialog",
        "tkinter.font",
        "tkinter.ttk",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(analysis.pure, analysis.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    [],
    name="VideoUnicalizator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
