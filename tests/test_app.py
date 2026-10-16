import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from settings import DEFAULTS, Store, validate
from engine import PopupEngine
from mqtt_link import MqttLink

APP = QApplication.instance() or QApplication([])


class StoreTests(unittest.TestCase):
    def test_secrets_encrypted_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            c = DEFAULTS | dict(password='secret-TEST-8371', rtsp='rtsp://user:PASS_TEST@host/live')
            store.save(c)
            self.assertEqual(store.load(), c)
            raw = store.path.read_bytes()
            self.assertNotIn(b'secret-TEST-8371', raw)
            self.assertNotIn(b'PASS_TEST', raw)

    def test_no_external_player_required(self):
        validate(DEFAULTS | dict(rtsp='rtsp://host/live'))

    def test_legacy_settings_migrate(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.save(DEFAULTS | dict(player='old.exe', precheck=True))
            self.assertEqual(store.load(), DEFAULTS)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = PopupEngine()
        self.engine.timer.stop()
        self.engine.config = DEFAULTS | dict(rtsp='rtsp://localhost/live')

    def tearDown(self):
        self.engine.stop()
        self.engine.popup.deleteLater()

    def trigger(self, now=100):
        with patch('engine.time.monotonic', return_value=now), patch.object(self.engine, 'launch_player'):
            self.engine.trigger(self.engine.config)

    def test_immediate_popup_without_external_process(self):
        self.trigger()
        self.assertTrue(self.engine.popup.isVisible())
        self.assertEqual(self.engine.deadline, 0)

    def test_first_frame_starts_clock(self):
        self.trigger()
        self.engine.state = 'connecting'
        with patch('engine.time.monotonic', return_value=104):
            self.engine.on_frame(Mock(isValid=lambda: False))
            self.assertEqual(self.engine.deadline, 0)
            self.engine.on_frame(Mock(isValid=lambda: True))
        self.assertEqual(self.engine.deadline, 164)
        self.assertEqual(self.engine.state, 'playing')

    def test_repeat_extends_wait_and_display(self):
        self.trigger()
        self.trigger(110)
        self.assertEqual(self.engine.wait_until, 155)
        self.engine.deadline = 160
        self.trigger(120)
        self.assertEqual(self.engine.deadline, 180)

    def test_deadline_closes_and_releases(self):
        self.trigger()
        self.engine.deadline = 120
        self.engine._tick(121)
        self.assertFalse(self.engine.popup.isVisible())
        self.assertEqual(self.engine.state, 'idle')

    def test_wait_timeout(self):
        self.trigger()
        self.engine._tick(146)
        self.assertEqual(self.engine.state, 'idle')

    def test_stalled_video_retries_without_resetting_deadline(self):
        self.trigger()
        self.engine.state = 'playing'
        self.engine.last_frame = 100
        self.engine.deadline = 160
        self.engine._tick(109)
        self.assertEqual(self.engine.state, 'waiting')
        self.assertEqual(self.engine.deadline, 160)
        self.assertEqual(self.engine.next_attempt, 111)

    def test_old_player_errors_are_ignored(self):
        self.engine.state = 'connecting'
        self.engine.player = Mock()
        self.engine.failed(Mock())
        self.assertEqual(self.engine.state, 'connecting')
        self.engine.failed(self.engine.player)
        self.assertEqual(self.engine.state, 'retry')

    def test_user_close_stops_retries(self):
        self.trigger()
        self.engine.popup.close()
        self.assertEqual(self.engine.state, 'idle')

    def test_late_frame_does_not_restart_stopped_playback(self):
        self.engine.stop()
        self.engine.on_frame(Mock(isValid=lambda: True))
        self.assertEqual(self.engine.state, 'idle')
        self.assertEqual(self.engine.deadline, 0)


class GuiTests(unittest.TestCase):
    def test_form_roundtrip(self):
        from app import Window
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Store(directory), DEFAULTS.copy())
            values = window.values()
            for key in DEFAULTS:
                if key != 'autostart':
                    self.assertEqual(values[key], DEFAULTS[key])
            window.engine.timer.stop()
            window.tray.hide()
            window.deleteLater()


class MqttTests(unittest.TestCase):
    def test_filter_retained_and_payload_and_old_clients(self):
        link = MqttLink()
        count = []
        link.ring.connect(lambda: count.append(1))
        with patch('mqtt_link.mqtt.Client') as factory:
            client = factory.return_value
            link.start(DEFAULTS | dict(host='localhost'))
            msg = Mock(retain=True, payload=b'ring')
            client.on_message(client, None, msg)
            msg.retain = False
            msg.payload = b'off'
            client.on_message(client, None, msg)
            msg.payload = b'ring'
            client.on_message(client, None, msg)
            self.assertEqual(len(count), 1)
            link.stop()
            client.on_message(client, None, msg)
            self.assertEqual(len(count), 1)


if __name__ == '__main__':
    unittest.main()
