# -*- mode: python ; coding: utf-8 -*-
"""
法律文书脱敏工具 - PyInstaller打包配置
生成单文件夹形式的exe（包含OCR模型）
"""

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# 收集 rapidocr_onnxruntime 的模型文件和依赖
rapidocr_datas = collect_data_files('rapidocr_onnxruntime')
rapidocr_imports = collect_submodules('rapidocr_onnxruntime')

# 收集 onnxruntime 数据
onnxruntime_datas = collect_data_files('onnxruntime')
onnxruntime_imports = collect_submodules('onnxruntime')

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        # 模板文件
        ('templates', 'templates'),
        ('static', 'static'),
        # desensitizer模块
        ('desensitizer', 'desensitizer'),
    ] + rapidocr_datas + onnxruntime_datas,
    hiddenimports=[
        'flask',
        'werkzeug',
        'werkzeug.serving',
        'werkzeug.debug',
        'jinja2',
        'markupsafe',
        'click',
        'itsdangerous',
        'blinker',
        'fitz',
        'pymupdf',
        'PIL',
        'PIL.Image',
        'docx',
        'chardet',
        'numpy',
        'cv2',
        'onnxruntime',
        'rapidocr_onnxruntime',
        'pyclipper',
        'shapely',
        'six',
        'yaml',
    ] + rapidocr_imports + onnxruntime_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'pandas',
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
        'setuptools',
        'pip',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='法律文书脱敏工具',
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
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='法律文书脱敏工具',
)
