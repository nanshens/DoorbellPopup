"""Offline packaged runtime verification, including real video decoding."""
import json
import sys
import tempfile
from pathlib import Path
from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
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
        player = QMediaPlayer()
        sink = QVideoSink()
        player.setVideoSink(sink)
        loop = QEventLoop()
        results['embedded_video_decodes_frame'] = False
        def received(frame):
            if frame.isValid():
                results['embedded_video_decodes_frame'] = True
                loop.quit()
        sink.videoFrameChanged.connect(received)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        media = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'playback-check.mp4'
        player.setSource(QUrl.fromLocalFile(str(media)))
        player.play()
        timer.start(15000)
        loop.exec()
        timer.stop()
        player.stop()
        from app import Window
        with tempfile.TemporaryDirectory(dir=app_dir(), prefix='.self-check-') as directory:
            window = Window(Store(directory), DEFAULTS.copy())
            results['gui_constructs'] = window.values()['seconds'] == 60
            results['no_external_player_setting'] = 'player' not in window.values()
            window.engine.timer.stop()
            window.engine.stop()
            window.engine.popup.deleteLater()
            window.tray.hide()
            window.deleteLater()
    except Exception:
        results['runtime_error'] = True
    success = bool(results) and all(results.values()) and 'runtime_error' not in results
    results['passed'] = success
    Path(app_dir(), 'self-check.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    return 0 if success else 1
