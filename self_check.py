"""Offline packaged-runtime check; does not connect MQTT or change startup settings."""
import json
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg

from settings import DEFAULTS, Store, app_dir


def run():
    results = {}
    try:
        with tempfile.TemporaryDirectory(dir=app_dir(), prefix='.self-check-') as directory:
            store = Store(directory)
            expected = DEFAULTS | dict(password='check-password', rtsp='rtsp://check:test@localhost/live')
            store.save(expected)
            results['sqlite_dpapi_roundtrip'] = store.load() == expected
            results['secrets_not_plaintext'] = b'check-password' not in store.path.read_bytes()
        process = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-loglevel', 'quiet',
            '-f', 'lavfi', '-i', 'color=black:s=16x16', '-frames:v', '1', '-vf', 'scale=1:1',
            '-pix_fmt', 'gray', '-f', 'rawvideo', 'pipe:1'], stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        results['bundled_ffmpeg_decodes_frame'] = process.returncode == 0 and len(process.stdout) == 1
        from app import Window
        with tempfile.TemporaryDirectory(dir=app_dir(), prefix='.self-check-') as directory:
            window = Window(Store(directory), DEFAULTS.copy())
            results['gui_constructs'] = window.values()['seconds'] == 60
            window.engine.timer.stop()
            window.tray.hide()
            window.deleteLater()
    except Exception:
        results['runtime_error'] = True
    success = bool(results) and all(results.values()) and 'runtime_error' not in results
    results['passed'] = success
    Path(app_dir(), 'self-check.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    return 0 if success else 1
