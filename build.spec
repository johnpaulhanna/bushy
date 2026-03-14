# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for Click Tracker
# Build with: cd to project dir, then run: pyinstaller build.spec

import os

block_cipher = None

# SPECPATH is set by PyInstaller to the directory containing this .spec file
script_dir = SPECPATH if 'SPECPATH' in dir() else os.path.dirname(os.path.abspath(__file__))

a = Analysis(
    ['click_tracker.py'],
    pathex=[script_dir],
    binaries=[],
    datas=[
        ('bush_spritesheet.png', '.'),
        ('fonts', 'fonts'),
    ],
    hiddenimports=['pystray._win32'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ClickTracker',
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
    # icon='icon.ico',  # uncomment when you have an .ico
)
