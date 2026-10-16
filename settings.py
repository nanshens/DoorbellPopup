"""Windows current-user encryption; no plaintext secrets on disk."""
import base64
from contextlib import contextmanager
import json
import sqlite3
import subprocess
import sys
import winreg
from pathlib import Path

import win32crypt

DEFAULTS = dict(rtsp='', player=r'C:\Program Files\DAUM\PotPlayer\PotPlayerMini64.exe',
                width=640, height=360, x=40, y=40, seconds=60,
                host='', port=1883, username='', password='', topic='home/doorbell/ring',
                payload='ring', tls=False, ca='', wait_seconds=45, probe_seconds=8,
                retry_seconds=2, restart_seconds=0, autostart=False)
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_NAME = 'DoorbellPopup'


def app_dir():
    return Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent


def protect(value):
    return base64.b64encode(win32crypt.CryptProtectData(
        value.encode('utf-8'), 'DoorbellPopup', None, None, None, 1)).decode('ascii')


def unprotect(value):
    return win32crypt.CryptUnprotectData(base64.b64decode(value), None, None, None, 1)[1].decode('utf-8')


class Store:
    def __init__(self, directory):
        self.path = Path(directory) / 'settings.db'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def load(self):
        with self.connect() as db:
            row = db.execute('SELECT data FROM settings WHERE id=1').fetchone()
        result = DEFAULTS.copy()
        if row:
            data = json.loads(row[0])
            for key in ('rtsp', 'password'):
                data[key] = unprotect(data[key])
            result.update(data)
        return result

    def save(self, config):
        data = config.copy()
        for key in ('rtsp', 'password'):
            data[key] = protect(data[key])
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES(1, ?)',
                       (json.dumps(data, ensure_ascii=False),))


def startup_command():
    if getattr(sys, 'frozen', False):
        args = [sys.executable, '--tray']
    else:
        pythonw = Path(sys.executable).with_name('pythonw.exe')
        args = [str(pythonw), str(Path(__file__).with_name('app.py')), '--tray']
    return subprocess.list2cmdline(args)


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, RUN_NAME)[0] == startup_command()
    except FileNotFoundError:
        return False


def set_startup(enabled):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:
                pass


def validate(c, mqtt_required=False):
    from urllib.parse import urlsplit
    url = urlsplit(c['rtsp'])
    if url.scheme.lower() not in ('rtsp', 'rtsps') or not url.hostname:
        raise ValueError('请填写有效的 rtsp:// 或 rtsps:// 视频地址。')
    if any(ch in c['rtsp'] for ch in ('\r', '\n', '\x00')):
        raise ValueError('视频地址不能包含换行或空字符。')
    player = Path(c['player'])
    if not player.is_file() or player.name.lower() not in ('potplayermini.exe', 'potplayermini64.exe'):
        raise ValueError('请选择 PotPlayerMini.exe 或 PotPlayerMini64.exe（不是快捷方式）。')
    if mqtt_required and not c['host'].strip():
        raise ValueError('请填写 MQTT broker 主机名或 IP。')
    if c['host'] and ('://' in c['host'] or '/' in c['host']):
        raise ValueError('Broker 只填写主机名或 IP，不含 mqtt:// 或路径。')
    if not c['topic'] or any(ch in c['topic'] for ch in ('#', '+', '\x00')):
        raise ValueError('请使用一个明确的 topic，不使用通配符。')
    if len(c['topic'].encode('utf-8')) > 65535:
        raise ValueError('Topic 太长。')
    if c['tls'] and c['ca'] and not Path(c['ca']).is_file():
        raise ValueError('CA 证书文件不存在。')
