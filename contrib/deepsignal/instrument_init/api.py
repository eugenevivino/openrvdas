"""Side-effect-free setup engine facade, except for explicit apply."""

from .profile import load_profile
from .runner import AuditLog, run


def _step(step, line_ending='', include_timeout=True):
    text = step['send'] + line_ending
    value = {'name': step['name'], 'class': step['class'], 'bytes_text': text,
             'bytes_hex': text.encode().hex(), 'expect': step.get('expect')}
    if include_timeout:
        value['timeout_s'] = step.get('timeout_s', 1.0)
    return value


def propose_init(profile, port):
    profile = load_profile(profile, allow_unreviewed=True)
    return {'instrument': profile['instrument'], 'port': dict(port),
            'precondition': 'logger on this port is stopped',
            'steps': [_step(s, profile['line_ending']) for s in profile['steps']]}


def describe_reader_sends(profile):
    profile = load_profile(profile, allow_unreviewed=True)
    reinit = profile['reinit']
    triggers = {'on_open': True, 'after_silence_s': reinit.get('after_silence_s'),
                'on_reconnect': bool(reinit.get('on_reconnect', False)),
                'max_per_hour': reinit.get('max_per_hour')}
    normal = [_step(s, profile['line_ending'], False) for s in profile['steps']
              if s['class'] in {'query', 'setup'}]
    persist = [dict(_step(s, profile['line_ending'], False),
                    policy='never sent by the reader') for s in profile['steps']
               if s['class'] == 'persist']
    return {'instrument': profile['instrument'], 'profile_id': profile['profile_id'],
            'version': profile['version'], 'triggers': triggers, 'steps': normal,
            'persist_steps': persist}


def apply_init(proposal, confirm, allow_persist=False, transport=None, audit_log=None,
               profile=None):
    if not confirm:
        raise ValueError('confirm: saw false; expected true; example: confirm=True')
    if not proposal.get('port', {}).get('free', False):
        raise ValueError('port free: saw false; expected a stopped logger; example: free: true')
    if transport is None or profile is None or audit_log is None:
        raise ValueError('transport/profile/audit_log are required to apply a proposal')
    classes = {'query', 'setup', 'persist'} if allow_persist else {'query', 'setup'}
    return run(load_profile(profile, allow_unreviewed=True), transport, 'manual',
               AuditLog(audit_log), classes=classes)['records']
