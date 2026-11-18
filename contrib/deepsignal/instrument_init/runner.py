"""Execute a validated profile against a byte transport."""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone


class AuditLog:
    """Append-only JSON Lines audit sink."""

    def __init__(self, path):
        self.path = str(path)

    def append(self, record):
        with open(self.path, 'a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, sort_keys=True) + '\n')


def _utc(clock):
    value = clock()
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def render_send(step, clock):
    text = step['send']
    text = re.sub(r'\{utc:([^{}]*)\}', lambda match: _utc(clock).strftime(match.group(1)), text)
    secret = os.environ.get(step.get('secret_env', ''), '')
    return text.replace('{secret}', secret), text.replace('{secret}', '***')


def _record(profile, trigger, step, event, data, elapsed, matched=None, display=None):
    shown = data.decode('utf-8', errors='backslashreplace') if display is None else display
    secret = os.environ.get(step.get('secret_env', ''), '')
    if secret:
        shown = shown.replace(secret, '***')
    shown_bytes = shown.encode('utf-8')
    return {'utc': datetime.now(timezone.utc).isoformat(),
            'instrument': profile['instrument'], 'profile_id': profile['profile_id'],
            'version': profile['version'], 'trigger': trigger, 'step': step['name'],
            'event': event, 'bytes_text': shown, 'bytes_hex': shown_bytes.hex(),
            'match': matched, 'elapsed_ms': round(elapsed * 1000, 3)}


def run(profile, transport, trigger, audit, classes=frozenset({'query', 'setup'}),
        clock=lambda: datetime.now(timezone.utc), sleep=time.sleep):
    """Run selected classes, aborting after a required step fails."""
    records = []
    for step in profile['steps']:
        if step['class'] not in classes:
            continue
        sent_text, shown_text = render_send(step, clock)
        payload = (sent_text + profile['line_ending']).encode('utf-8')
        shown_payload = shown_text + profile['line_ending']
        success = False
        for attempt in range(step.get('retries', 0) + 1):
            started = time.monotonic()
            transport.write(payload)
            item = _record(profile, trigger, step, 'send', payload,
                           time.monotonic() - started, display=shown_payload)
            audit.append(item)
            records.append(item)
            if step.get('pause_s'):
                sleep(step['pause_s'])
            if step.get('expect') is None:
                success = True
                break
            deadline = time.monotonic() + step.get('timeout_s', 1.0)
            while time.monotonic() <= deadline:
                reply = transport.readline(max(0, deadline - time.monotonic()))
                if reply is None:
                    break
                decoded = reply.decode('utf-8', errors='replace').rstrip('\r\n')
                matched = re.search(step['expect'], decoded) is not None
                item = _record(profile, trigger, step, 'reply', reply,
                               time.monotonic() - started, matched)
                audit.append(item)
                records.append(item)
                if matched:
                    success = True
                    break
            if success:
                break
        if not success:
            message = f'Initialization step {step["name"]} did not match its expected reply'
            if step.get('optional'):
                logging.warning(message)
            else:
                logging.error(message)
                return {'ok': False, 'failed_step': step['name'], 'records': records}
    return {'ok': True, 'failed_step': None, 'records': records}
