"""Optional read-only Redis channel and key discovery."""

import time


def scan_redis(target, listen_s=3, client_factory=None):
    try:
        if client_factory is None:
            import redis
            client_factory = redis.Redis
    except ImportError:
        return [{"transport": "redis", "port": target, "status":
                 "skipped: redis is not installed"}]
    host, separator, port = target.partition(":")
    client = client_factory(host=host, port=int(port) if separator else 6379)
    channels_raw = list(client.pubsub_channels())
    channels = [item.decode("utf-8", "replace") for item in channels_raw]
    keys = []
    for key in client.scan_iter(count=100):
        if len(keys) >= 1000:
            break
        keys.append({"key": key.decode("utf-8", "replace"),
                     "type": client.type(key).decode("ascii", "replace")})
    messages = []
    if channels_raw:
        subscriber = client.pubsub()
        try:
            subscriber.subscribe(*channels_raw)
            deadline = time.monotonic() + listen_s
            while time.monotonic() < deadline and len(messages) < 200:
                message = subscriber.get_message(ignore_subscribe_messages=True, timeout=0.1)
                if message:
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8", "replace")
                    messages.append(str(data))
        finally:
            subscriber.close()
    return [{"transport": "redis", "port": target, "status": "live",
             "lines_per_second": len(messages) / listen_s,
             "sample_lines": messages[:5], "capture_lines": messages,
             "nmea_talkers": [],
             "nmea_sentences": [], "baud": None, "channels": channels,
             "keys": keys, "listen_s": listen_s}]
