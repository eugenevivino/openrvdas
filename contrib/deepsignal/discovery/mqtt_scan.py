"""Optional passive MQTT topic discovery."""

import time


def scan_mqtt(target, listen_s=3, credentials_path=None, client_factory=None):
    try:
        if client_factory is None:
            import paho.mqtt.client as mqtt
            client_factory = mqtt.Client
    except ImportError:
        return [{"transport": "mqtt", "port": target, "status":
                 "skipped: paho-mqtt is not installed"}]
    host, separator, port = target.partition(":")
    messages = {}
    client = client_factory()
    if credentials_path:
        with open(credentials_path, encoding="utf-8") as source:
            username, password = source.read().rstrip("\n").split(":", 1)
        client.username_pw_set(username, password)
    client.on_connect = lambda connection, userdata, flags, rc: connection.subscribe("#")

    def receive(unused_client, unused_userdata, message):
        del unused_client, unused_userdata
        messages.setdefault(message.topic, []).append(
            message.payload[:200].decode("utf-8", "replace"))
    client.on_message = receive
    client.connect(host, int(port) if separator else 1883)
    client.loop_start()
    time.sleep(listen_s)
    client.loop_stop()
    client.disconnect()
    return [{"transport": "mqtt", "port": topic, "status": "live",
             "lines_per_second": len(payloads) / listen_s,
             "sample_lines": payloads[:5], "capture_lines": payloads[:200],
             "nmea_talkers": [], "nmea_sentences": [], "baud": None}
            for topic, payloads in sorted(messages.items())]
