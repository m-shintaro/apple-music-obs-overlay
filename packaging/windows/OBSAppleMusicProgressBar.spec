# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all


project_root = Path(SPECPATH).parents[1]

winsdk_datas, winsdk_binaries, winsdk_hiddenimports = collect_all("winsdk")

datas = [
    (str(project_root / "overlay.html"), "."),
    (str(project_root / "README.md"), "."),
    (str(project_root / "README.ja.md"), "."),
    (str(project_root / "LICENSE"), "."),
]

hiddenimports = [
    "winsdk.windows.media.control",
    "winsdk.windows.storage.streams",
]

a = Analysis(
    [str(project_root / "nowplaying.py")],
    pathex=[str(project_root), str(project_root / "src")],
    binaries=winsdk_binaries,
    datas=datas + winsdk_datas,
    hiddenimports=hiddenimports + winsdk_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OBSAppleMusicProgressBar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="OBSAppleMusicProgressBar",
)

