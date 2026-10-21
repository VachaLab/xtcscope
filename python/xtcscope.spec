# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the xtcscope bundle: `uv run pyinstaller xtcscope.spec`.
# Produces dist/xtcscope/ (onedir): the `xtcscope` executable and `_internal/`.
from PyInstaller.utils.hooks import copy_metadata

# readchar (a qq dependency) reads its own version from package metadata.
datas = copy_metadata("readchar")

a = Analysis(
    ["src/xtcscope/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="xtcscope",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="xtcscope",
)
