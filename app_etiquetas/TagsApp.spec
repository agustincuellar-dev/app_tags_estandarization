# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app_tags.py'],
    pathex=[],
    binaries=[],
    datas=[('logo_app_tags.ico', '.'), ('logo_header.png', '.'), ('logo_balcanes.png', '.'), ('schema.sql', '.'), ('tags_ingenio.db', '.')],
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
    a.binaries,
    a.datas,
    [],
    name='TagsApp',
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
    icon=['logo_app_tags.ico'],
)
