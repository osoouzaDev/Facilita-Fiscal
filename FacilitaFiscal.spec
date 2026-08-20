# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ["facilita_fiscal.py"],
    pathex=[],
    binaries=[],
    datas=[("assets/facilita_fiscal_icon.ico", "assets")],
    hiddenimports=[
        "pypdf",
        "tkinter",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "tkinter.ttk",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=2,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="FacilitaFiscal",
    icon="assets/facilita_fiscal_icon.ico",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version="version_info_facilita_fiscal.txt",
)
