"""Embedded Qt/FFmpeg playback; all player operations run on the GUI thread."""
import logging
import time

from PySide6.QtCore import QObject, QTimer, Signal, Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

LOG = logging.getLogger('doorbell')


class VideoPopup(QWidget):
    closed = Signal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle('门铃实时视频')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.video = QVideoWidget()
        self.message = QLabel('正在连接视频…')
        self.message.setStyleSheet('padding:6px; color:white; background:#202020')
        layout.addWidget(self.video, 1)
        layout.addWidget(self.message)

    def closeEvent(self, event):
        self.closed.emit()
        event.accept()


class PopupEngine(QObject):
    status = Signal(str)

    def __init__(self):
        super().__init__()
        self.config = None
        self.state = 'idle'
        self.deadline = self.wait_until = self.next_attempt = 0
        self.player_started = self.last_frame = 0
        self.player = None
        self.popup = VideoPopup()
        self.popup.closed.connect(self.stop)
        self.audio = QAudioOutput(self)
        self.popup.video.videoSink().videoFrameChanged.connect(self.on_frame)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(200)

    def say(self, text):
        self.status.emit(text)
        self.popup.message.setText(text)
        LOG.info(text)  # Never log URLs or backend exception strings.

    def release_player(self):
        player, self.player = self.player, None
        if player is not None:
            player.stop()
            player.setVideoOutput(None)
            player.setAudioOutput(None)
            player.setSource(QUrl())
            player.deleteLater()

    def stop(self):
        self.state = 'idle'
        self.release_player()
        self.popup.hide()
        self.deadline = 0
        self.say('弹窗已停止')
        return True

    def trigger(self, config):
        now = time.monotonic()
        if self.state != 'idle':
            if self.deadline:
                self.deadline = max(self.deadline, now + self.config['seconds'])
            else:
                self.wait_until = max(self.wait_until, now + self.config['wait_seconds'])
            self.say('再次触发：已延长弹窗或等待时间')
            return
        self.config = config.copy()
        self.deadline = 0
        self.wait_until = now + config['wait_seconds']
        self.next_attempt = now
        self.state = 'waiting'
        self.popup.setGeometry(config['x'], config['y'], config['width'], config['height'])
        self.popup.show()
        self.popup.raise_()
        self.say('正在连接内嵌视频…')
        self.tick()

    def launch_player(self, now):
        self.release_player()
        player = QMediaPlayer(self)
        self.player = player
        player.setAudioOutput(self.audio)
        self.audio.setMuted(self.config.get('muted', False))
        player.setVideoOutput(self.popup.video)
        player.errorOccurred.connect(lambda *_: self.failed(player))
        player.mediaStatusChanged.connect(lambda status: self.media_status(player, status))
        self.player_started = self.last_frame = now
        self.state = 'connecting'
        player.setSource(QUrl(self.config['rtsp']))
        player.play()

    def failed(self, player):
        if self.player is player and self.state in ('connecting', 'playing'):
            # Defer cleanup; never destroy a backend inside its error callback.
            self.state = 'retry'

    def media_status(self, player, status):
        if status in (QMediaPlayer.MediaStatus.EndOfMedia, QMediaPlayer.MediaStatus.InvalidMedia):
            self.failed(player)

    def on_frame(self, frame):
        if self.state not in ('connecting', 'playing') or not frame.isValid():
            return
        now = time.monotonic()
        self.last_frame = now
        if self.state == 'connecting':
            self.state = 'playing'
            if not self.deadline:
                self.deadline = now + self.config['seconds']
            self.say('视频播放中；再次触发将延长时间')

    def retry(self, now):
        self.state = 'waiting'
        self.release_player()
        self.next_attempt = now + self.config['retry_seconds']
        self.say('视频暂未就绪，稍后自动重连…')

    def tick(self):
        if self.state == 'idle':
            return
        try:
            self._tick(time.monotonic())
        except Exception:
            self.stop()
            self.say('视频播放失败，请检查视频地址与网络。')

    def _tick(self, now):
        if self.deadline and now >= self.deadline:
            self.stop()
            return
        if not self.deadline and now >= self.wait_until:
            self.stop()
            self.say('等待视频超时；下次门铃触发会重新尝试')
            return
        if self.state == 'waiting' and now >= self.next_attempt:
            self.launch_player(now)
        elif self.state == 'retry':
            self.retry(now)
        elif self.state in ('connecting', 'playing'):
            timeout = self.config['probe_seconds']
            interval = self.config['restart_seconds']
            if now - self.last_frame >= timeout or (interval and now - self.player_started >= interval):
                self.retry(now)
