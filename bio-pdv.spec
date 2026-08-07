# PyInstaller spec do bio-pdv.
#
#   pyinstaller bio-pdv.spec --noconfirm
#
# Gera dist/bio-pdv/bio-pdv.exe (modo onedir: abre mais rapido que onefile e
# nao extrai nada em %TEMP% a cada execucao -- importante num PDV).

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'win32crypt',        # DPAPI: cifra as senhas do cofre
        'win32timezone',     # pywin32 exige em runtime empacotado
        'pynput.keyboard._win32',
        'pynput.mouse._win32',
        'serial.tools.list_ports_windows',
    ],
    hookspath=[],
    runtime_hooks=[],
    # PySide6 traz muita coisa que nao usamos; cortar derruba ~150 MB
    excludes=[
        'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuick3D',
        'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
        'PySide6.QtMultimedia', 'PySide6.QtCharts', 'PySide6.Qt3DCore',
        'PySide6.QtDataVisualization', 'PySide6.QtOpenGL',
        'tkinter', 'matplotlib', 'numpy', 'PIL',
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='bio-pdv',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # sem janela preta de console
    icon='assets/bio-pdv.ico' if __import__('os').path.exists('assets/bio-pdv.ico') else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='bio-pdv',
)
