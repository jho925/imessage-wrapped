# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['imessage_wrapped.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['flask', 'jinja2', 'jinja2.ext'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='iMessageWrapped',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
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
    upx=True,
    upx_exclude=[],
    name='iMessageWrapped',
)

app = BUNDLE(
    coll,
    name='iMessageWrapped.app',
    icon=None,
    bundle_identifier='com.imessagewrapped.app',
)
