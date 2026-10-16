import ssl
import uuid

import paho.mqtt.client as mqtt
from PySide6.QtCore import QObject, Signal


class MqttLink(QObject):
    status = Signal(str)
    ring = Signal()

    def __init__(self):
        super().__init__()
        self.client = None

    def stop(self):
        old, self.client = self.client, None
        if old:
            old.disconnect()
            old.loop_stop()
        self.status.emit('MQTT：未连接')

    def start(self, config):
        self.stop()
        c = config.copy()
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id='doorbell-' + uuid.uuid4().hex[:16], clean_session=True)
        self.client = client
        if c['username']:
            client.username_pw_set(c['username'], c['password'])
        if c['tls']:
            context = ssl.create_default_context(cafile=c['ca'] or None)
            client.tls_set_context(context)
        client.reconnect_delay_set(min_delay=1, max_delay=30)

        def connected(cl, userdata, flags, reason, properties):
            if cl is not self.client:
                return
            if reason.is_failure:
                self.status.emit('MQTT：连接被拒绝，请检查账号和 broker 权限')
            else:
                self.status.emit('MQTT：已连接，正在订阅')
                rc, _ = cl.subscribe(c['topic'], qos=1)
                if rc != mqtt.MQTT_ERR_SUCCESS:
                    self.status.emit('MQTT：订阅发送失败')

        def subscribed(cl, userdata, mid, codes, properties):
            if cl is self.client:
                self.status.emit('MQTT：订阅被拒绝' if any(x.is_failure for x in codes)
                                 else 'MQTT：已连接并订阅，等待门铃')

        def disconnected(cl, userdata, flags, reason, properties):
            if cl is self.client:
                self.status.emit('MQTT：已断开，将自动重连')

        def failed(cl, userdata):
            if cl is self.client:
                self.status.emit('MQTT：无法连接，将自动重试')

        def message(cl, userdata, msg):
            if cl is not self.client or msg.retain or len(msg.payload) > 4096:
                return
            try:
                text = msg.payload.decode('utf-8')
            except UnicodeDecodeError:
                return
            if text == c['payload']:
                self.ring.emit()

        client.on_connect = connected
        client.on_subscribe = subscribed
        client.on_disconnect = disconnected
        client.on_connect_fail = failed
        client.on_message = message
        client.connect_async(c['host'], c['port'], keepalive=30)
        client.loop_start()
        self.status.emit('MQTT：正在连接')
