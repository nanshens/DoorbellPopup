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

    def test_reject_non_potplayer(self):
        with self.assertRaises(ValueError):
            validate(DEFAULTS | dict(rtsp='rtsp://host/live', player='cmd.exe'))


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = PopupEngine()
        self.engine.timer.stop()

    def tearDown(self):
        self.engine.timer.stop()

    def test_repeated_trigger_extends_without_spawn(self):
        with patch('engine.time.monotonic', return_value=100):
            self.engine.trigger(DEFAULTS)
        self.assertEqual(self.engine.wait_until, 145)
        with patch('engine.time.monotonic', return_value=110):
            self.engine.trigger(DEFAULTS)
        self.assertEqual(self.engine.wait_until, 155)
        self.engine.deadline = 170
        with patch('engine.time.monotonic', return_value=150):
            self.engine.trigger(DEFAULTS)
        self.assertEqual(self.engine.deadline, 210)
        self.assertIsNone(self.engine.player)

    def test_deadline_terminates_only_owned_handle(self):
        own = Mock()
        own.poll.return_value = None
        own.stdout = None
        unrelated = Mock()
        self.engine.player = own
        self.engine.state = 'playing'
        self.engine.deadline = 100
        self.engine._tick(101)
        own.terminate.assert_called_once()
        unrelated.terminate.assert_not_called()
        self.assertEqual(self.engine.state, 'idle')

    def test_probe_timeout_retry(self):
        self.engine.config = DEFAULTS.copy()
        self.engine.state = 'probing'
        self.engine.wait_until = 200
        self.engine.probe_started = 100
        probe = Mock()
        probe.poll.return_value = None
        self.engine.probe = probe
        self.engine._tick(109)
        probe.terminate.assert_called_once()
        self.assertEqual(self.engine.state, 'waiting')

    def test_wait_timeout_does_not_launch(self):
        self.engine.config = DEFAULTS.copy()
        self.engine.state = 'waiting'
        self.engine.wait_until = 20
        with patch.object(self.engine, 'launch_probe') as launch:
            self.engine._tick(21)
            launch.assert_not_called()
        self.assertEqual(self.engine.state, 'idle')

    def test_success_without_frame_is_failure(self):
        self.engine.config = DEFAULTS.copy()
        self.engine.state = 'probing'
        self.engine.wait_until = 200
        probe = Mock(returncode=0)
        probe.poll.return_value = 0
        probe.stdout.read.return_value = b''
        self.engine.probe = probe
        with patch.object(self.engine, 'launch_player') as launch:
            self.engine._tick(110)
            launch.assert_not_called()
        self.assertEqual(self.engine.state, 'waiting')

    def test_ready_frame_launches(self):
        self.engine.config = DEFAULTS.copy()
        self.engine.state = 'probing'
        self.engine.wait_until = 200
        probe = Mock(returncode=0)
        probe.poll.return_value = 0
        probe.stdout.read.return_value = b'\x12'
        self.engine.probe = probe
        with patch.object(self.engine, 'launch_player') as launch:
            self.engine._tick(110)
            launch.assert_called_once_with(110)

    def test_display_clock_starts_at_window_and_restart_keeps_deadline(self):
        self.engine.config = DEFAULTS | dict(restart_seconds=20)
        self.engine.state = 'playing'
        self.engine.wait_until = 150
        self.engine.player_started = 100
        own = Mock()
        own.poll.return_value = None
        own.stdout = None
        self.engine.player = own
        with patch.object(self.engine, 'windows', return_value=[99]), patch.object(self.engine, 'position'):
            self.engine._tick(102)
            self.assertEqual(self.engine.deadline, 162)
            self.engine._tick(121)
        self.assertEqual(self.engine.deadline, 162)
        self.assertEqual(self.engine.state, 'waiting')

    def test_launch_uses_new_instance(self):
        self.engine.config = DEFAULTS | dict(rtsp='rtsp://host/live')
        with patch('engine.subprocess.Popen') as popen:
            self.engine.launch_player(100)
            self.assertEqual(popen.call_args.args[0], [DEFAULTS['player'], 'rtsp://host/live', '/new'])


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
