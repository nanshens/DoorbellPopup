"""DoorbellPopup — Windows 10/11, Python 3.11–3.13, current user only."""
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QSystemTrayIcon, QTabWidget, QVBoxLayout, QWidget)

from engine import PopupEngine
from mqtt_link import MqttLink
from settings import Store, app_dir, set_startup, startup_enabled, validate


def icon():
    pix = QPixmap(64, 64)
    pix.fill(QColor('#126d85'))
    painter = QPainter(pix)
    painter.setPen(QColor('white'))
    font = painter.font()
    font.setPixelSize(42)
    painter.setFont(font)
    painter.drawText(pix.rect(), 0x84, 'D')
    painter.end()
    return QIcon(pix)


class Window(QMainWindow):
    def __init__(self, store, config):
        super().__init__()
        self.store, self.config = store, config
        self.fields = {}
        self.setWindowTitle('门铃视频弹窗 · DoorbellPopup')
        self.setWindowIcon(icon())
        self.resize(700, 700)
        body = QWidget()
        outer = QVBoxLayout(body)
        title = QLabel('门铃响起，在桌面显示实时视频')
        title.setStyleSheet('font-size:20px; font-weight:600; padding:8px')
        outer.addWidget(title)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)
        video = self.page('视频与窗口')
        self.text(video, 'rtsp', 'RTSP 视频地址', secret=True)
        self.text(video, 'player', 'PotPlayer exe', browse='播放器 (*.exe)')
        for key, label, low, high in [('width', '窗口宽度（物理像素）', 160, 7680),
                ('height', '窗口高度（物理像素）', 120, 4320),
                ('x', '左上角 X（支持负数副屏）', -32768, 32767),
                ('y', '左上角 Y', -32768, 32767), ('seconds', '显示时间（秒）', 1, 3600)]:
            self.number(video, key, label, low, high)
        center = QPushButton('放到主屏幕右下角')
        center.clicked.connect(self.bottom_right)
        video.addRow('', center)
        video.addRow(QLabel('窗口尺寸包含标题栏和边框。建议关闭 PotPlayer 的全屏启动。'))
        mqtt = self.page('MQTT 连接')
        self.text(mqtt, 'host', 'Broker 主机名 / IP')
        self.number(mqtt, 'port', '端口', 1, 65535)
        self.text(mqtt, 'username', '账号（可空）')
        self.text(mqtt, 'password', '密码', secret=True)
        self.text(mqtt, 'topic', 'Topic')
        self.text(mqtt, 'payload', '触发内容（精确匹配）')
        self.check(mqtt, 'tls', '使用 TLS（通常端口 8883）')
        self.text(mqtt, 'ca', '自定义 CA（可空）', browse='证书 (*.pem *.crt);;所有文件 (*)')
        mqtt.addRow(QLabel('默认触发内容为 ring；忽略保留消息。TLS 会验证证书与主机名。'))
        recovery = self.page('重试与启动')
        for key, label, low, high in [('wait_seconds', '最长等待视频上线（秒）', 5, 300),
                ('probe_seconds', '每次解码检测超时（秒）', 2, 30),
                ('retry_seconds', '重试间隔（秒）', 1, 30),
                ('restart_seconds', '定时重新打开播放器（0 = 关闭）', 0, 300)]:
            self.number(recovery, key, label, low, high)
        self.check(recovery, 'autostart', '当前用户登录 Windows 后自动运行（保存后生效）')
        hint = QLabel('视频流未上线时反复检测，解码成功后才打开播放器。\n'
                      '定时重开可应对播放器卡住，但会中断画面；建议设为 0，必要时 20 秒。\n'
                      '点击窗口关闭按钮会缩到托盘；从托盘菜单选择“退出”才能结束。')
        hint.setWordWrap(True)
        recovery.addRow(hint)
        location = QLabel(f'配置与日志目录：{app_dir()}')
        location.setWordWrap(True)
        recovery.addRow(location)
        self.mqtt_status = QLabel('MQTT：未连接')
        self.popup_status = QLabel('弹窗：待命')
        self.popup_status.setWordWrap(True)
        outer.addWidget(self.mqtt_status)
        outer.addWidget(self.popup_status)
        buttons = QHBoxLayout()
        for text, action in [('保存并连接', self.save_connect), ('手动测试', self.test),
                             ('停止弹窗', self.stop_popup), ('缩到托盘', self.hide_to_tray)]:
            button = QPushButton(text)
            button.clicked.connect(action)
            buttons.addWidget(button)
        outer.addLayout(buttons)
        self.setCentralWidget(body)
        self.engine = PopupEngine()
        self.engine.status.connect(self.popup_status.setText)
        self.mqtt = MqttLink()
        self.mqtt.status.connect(self.on_mqtt_status)
        self.mqtt.ring.connect(self.on_ring)
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip('门铃视频弹窗')
        menu = QMenu(self)
        for text, action in [('打开设置', self.show_settings), ('测试已保存配置', self.saved_test),
                             ('停止弹窗', self.stop_popup), ('退出', self.quit_app)]:
            item = QAction(text, menu)
            item.triggered.connect(action)
            menu.addAction(item)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_settings()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show()
        self.fields['autostart'].setChecked(startup_enabled())
        if config['host']:
            QTimer.singleShot(0, self.connect_saved)

    def page(self, title):
        widget = QWidget()
        form = QFormLayout(widget)
        form.setSpacing(14)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        self.tabs.addTab(scroll, title)
        return form

    def text(self, form, key, label, secret=False, browse=None):
        field = QLineEdit(str(self.config[key]))
        self.fields[key] = field
        if secret:
            field.setEchoMode(QLineEdit.EchoMode.Password)
        row = QHBoxLayout()
        row.addWidget(field)
        if browse:
            button = QPushButton('选择…')
            def choose():
                name, _ = QFileDialog.getOpenFileName(self, label, '', browse)
                if name:
                    field.setText(name)
            button.clicked.connect(choose)
            row.addWidget(button)
        if secret:
            reveal = QCheckBox('显示')
            reveal.toggled.connect(lambda checked: field.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
            row.addWidget(reveal)
        form.addRow(label, row)

    def number(self, form, key, label, low, high):
        field = QSpinBox()
        field.setRange(low, high)
        field.setValue(self.config[key])
        self.fields[key] = field
        form.addRow(label, field)

    def check(self, form, key, label):
        field = QCheckBox(label)
        field.setChecked(self.config[key])
        self.fields[key] = field
        form.addRow(field)

    def values(self):
        return {k: v.isChecked() if isinstance(v, QCheckBox) else
                v.value() if isinstance(v, QSpinBox) else v.text()
                for k, v in self.fields.items()}

    def bottom_right(self):
        # Qt coordinates are logical; Win32 coordinates follow this process's DPI context.
        import win32api
        info = win32api.GetMonitorInfo(win32api.MonitorFromPoint((0, 0), 1))
        left, top, right, bottom = info['Work']
        self.fields['x'].setValue(max(left, right - self.fields['width'].value() - 20))
        self.fields['y'].setValue(max(top, bottom - self.fields['height'].value() - 20))

    def error(self, message):
        QMessageBox.warning(self, '请检查配置', message)

    def save_connect(self):
        c = self.values()
        try:
            validate(c, mqtt_required=True)
        except ValueError as exc:
            self.error(str(exc))
            return
        except Exception:
            self.error('配置格式无效，请检查视频地址和路径。')
            return
        try:
            self.store.save(c)
        except Exception:
            self.error('保存失败。请将程序放到当前用户可写的目录，并检查磁盘空间。')
            return
        try:
            set_startup(c['autostart'])
        except OSError:
            self.error('配置已保存，但登录自启动设置失败。请检查 Windows 策略。')
        self.config = c
        self.connect_saved()

    def connect_saved(self):
        try:
            validate(self.config, mqtt_required=True)
            self.mqtt.start(self.config)
        except Exception:
            self.mqtt.stop()
            self.on_mqtt_status('MQTT：配置无效，打开设置后保存重试')

    def on_mqtt_status(self, text):
        self.mqtt_status.setText(text)
        self.tray.setToolTip(text)
        logging.getLogger('doorbell').info(text)

    def on_ring(self):
        self.engine.trigger(self.config)

    def test_config(self, c):
        try:
            validate(c)
        except ValueError as exc:
            self.error(str(exc))
            return
        except Exception:
            self.error('配置格式无效。')
            return
        self.engine.trigger(c)

    def test(self):
        self.test_config(self.values())

    def saved_test(self):
        self.test_config(self.config)

    def stop_popup(self):
        self.engine.stop()

    def show_settings(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def hide_to_tray(self):
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.hide()
        else:
            self.error('系统托盘不可用，窗口将保持显示。')

    def closeEvent(self, event):
        event.ignore()
        self.hide_to_tray()

    def quit_app(self):
        self.mqtt.stop()
        if self.engine.stop():
            self.tray.hide()
            QApplication.quit()


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont('Microsoft YaHei UI', 10))
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName('DoorbellPopup')
    if '--self-check' in sys.argv:
        from self_check import run
        return run()
    directory = app_dir()
    # One instance per current user, even if EXEs are copied to multiple folders.
    lock = QLockFile(str(Path(tempfile.gettempdir()) / 'DoorbellPopup-current-user.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, '门铃视频弹窗', '程序已运行，请双击系统托盘里的 D 图标。')
        return 0
    try:
        with tempfile.NamedTemporaryFile(prefix='.write-check-', dir=directory):
            pass
        store = Store(directory)
        config = store.load()
        handler = RotatingFileHandler(directory / 'doorbell.log', maxBytes=1000000,
                                      backupCount=3, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logger = logging.getLogger('doorbell')
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
    except Exception:
        QMessageBox.critical(None, '无法读取或保存配置',
            '请将程序放在当前用户可写的文件夹（例如“文档\\DoorbellPopup”）。\n'
            '数据库与日志必须放在程序目录。若配置来自其他电脑或用户，原密码无法解密；\n'
            '请备份并移走 settings.db 后重新配置。本程序不会自动覆盖原配置。')
        return 1
    window = Window(store, config)
    if '--tray' not in sys.argv or not config['host'] or not QSystemTrayIcon.isSystemTrayAvailable():
        window.show()
    exit_code = app.exec()
    handler.close()
    lock.unlock()
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
