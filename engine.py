"""Nonblocking subprocess state machine. Only Popen-owned processes are stopped."""
import logging
import subprocess
import time

import imageio_ffmpeg
import win32con
import win32gui
import win32process
from PySide6.QtCore import QObject, QTimer, Signal

LOG = logging.getLogger('doorbell')
NO_WINDOW = subprocess.CREATE_NO_WINDOW


class PopupEngine(QObject):
    status = Signal(str)

    def __init__(self):
        super().__init__()
        self.config = None
        self.player = self.probe = None
        self.state = 'idle'
        self.deadline = self.wait_until = self.next_attempt = 0
        self.probe_started = self.player_started = 0
        self.had_window = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(200)

    def say(self, text):
        self.status.emit(text)
        LOG.info(text)  # Only fixed status strings; never URL, payload or exception text.

    @staticmethod
    def stop_process(process):
        if process is not None:
            if process.poll() is None:
                # Windows Popen retains the original process HANDLE: no name/PID-wide kill.
                process.terminate()
                process.wait(timeout=3)
            if process.stdout:
                process.stdout.close()

    def stop(self):
        for attr in ('probe', 'player'):
            process = getattr(self, attr)
            if process is not None:
                try:
                    self.stop_process(process)
                except (OSError, subprocess.TimeoutExpired):
                    self.say('无法关闭本应用的子进程；请检查播放器权限。')
                    return False
                setattr(self, attr, None)
        self.state = 'idle'
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
        self.say('触发：等待视频预检测' if self.config.get('precheck', False)
                 else '触发：直接交给 PotPlayer 播放')

    def retry(self):
        self.state = 'waiting'
        self.next_attempt = time.monotonic() + self.config['retry_seconds']
        self.say('预检测未通过（不代表 PotPlayer 无法播放），稍后重试'
                 if self.config.get('precheck', False) else '播放器已退出或未出现窗口，稍后重试')

    def launch_probe(self, now):
        args = [imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-hide_banner', '-loglevel', 'quiet',
                '-rtsp_transport', 'tcp', '-rw_timeout', str(self.config['probe_seconds'] * 1000000),
                '-i', self.config['rtsp'], '-map', '0:v:0', '-frames:v', '1',
                '-vf', 'scale=1:1', '-pix_fmt', 'gray', '-f', 'rawvideo', 'pipe:1']
        self.probe = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        self.probe_started = now
        self.state = 'probing'

    def launch_player(self, now):
        self.player = subprocess.Popen([self.config['player'], self.config['rtsp'], '/new'],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
        self.player_started = now
        self.had_window = False
        self.state = 'playing'
        self.say('正在打开独立 PotPlayer 窗口；实际画面由播放器加载')

    def windows(self):
        if self.player is None or self.player.poll() is not None:
            return []
        result = []
        def visit(hwnd, _):
            if (win32gui.IsWindowVisible(hwnd)
                    and win32process.GetWindowThreadProcessId(hwnd)[1] == self.player.pid
                    and win32gui.GetClassName(hwnd).startswith('PotPlayer')):
                result.append(hwnd)
        win32gui.EnumWindows(visit, None)
        return result

    def position(self, hwnd):
        c = self.config
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, c['x'], c['y'], c['width'], c['height'],
                              win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW)

    def tick(self):
        if self.state == 'idle':
            return
        try:
            self._tick(time.monotonic())
        except Exception:
            # Libraries sometimes include the credential-bearing URL in exceptions.
            self.stop()
            self.say('弹窗操作失败：请检查播放器路径、权限与视频配置。')

    def _tick(self, now):
        if self.deadline and now >= self.deadline:
            self.stop()
            return
        if not self.deadline and now >= self.wait_until:
            self.stop()
            self.say('等待视频超时；下次门铃触发会重新尝试')
            return
        if self.state == 'waiting' and now >= self.next_attempt:
            if self.config.get('precheck', False):
                self.launch_probe(now)
            else:
                self.launch_player(now)
        elif self.state == 'probing':
            if self.probe.poll() is not None:
                data = self.probe.stdout.read()
                ok = self.probe.returncode == 0 and len(data) == 1
                self.stop_process(self.probe)
                self.probe = None
                if ok:
                    self.launch_player(now)
                else:
                    self.retry()
            elif now - self.probe_started >= self.config['probe_seconds']:
                self.stop_process(self.probe)
                self.probe = None
                self.retry()
        elif self.state == 'playing':
            if self.player.poll() is not None:
                self.stop_process(self.player)
                self.player = None
                self.retry()
                return
            windows = self.windows()
            if windows:
                if not self.had_window:
                    self.had_window = True
                    if not self.deadline:
                        self.deadline = now + self.config['seconds']
                    self.say('弹窗显示中（置顶）；再次触发将延长时间')
                for hwnd in windows:
                    self.position(hwnd)
            elif now - self.player_started > 12:
                self.stop_process(self.player)
                self.player = None
                self.retry()
                return
            interval = self.config['restart_seconds']
            if interval and now - self.player_started >= interval:
                self.stop_process(self.player)
                self.player = None
                self.retry()
