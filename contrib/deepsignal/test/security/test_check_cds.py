from pathlib import Path
from types import SimpleNamespace

from contrib.deepsignal.security.check_cds import check_cds_listener
from contrib.deepsignal.security.check_cds import check_nginx
from contrib.deepsignal.security.check_cds import check_udp_listener


def runner_with(output):
    def run(unused_command, **unused_kwargs):
        return SimpleNamespace(stdout=output)
    return run


def test_cds_listener_pass_and_fail():
    passed = check_cds_listener(runner_with('LISTEN 0 128 127.0.0.1:8766 0.0.0.0:*'))
    failed = check_cds_listener(runner_with('LISTEN 0 128 0.0.0.0:8766 0.0.0.0:*'))
    assert passed[0]
    assert not failed[0]


def test_udp_listener_pass_and_fail():
    passed = check_udp_listener(6225, '10.2.3.4',
                                runner_with('UNCONN 0 0 10.2.3.4:6225 0.0.0.0:*'))
    failed = check_udp_listener(6225, '10.2.3.4',
                                runner_with('UNCONN 0 0 0.0.0.0:6225 0.0.0.0:*'))
    assert passed[0]
    assert not failed[0]


def test_nginx_pass_and_fail(tmp_path):
    config = tmp_path / 'cds-ws.conf'
    config.write_text('location /cds-ws { proxy_pass http://127.0.0.1:8767; }')
    assert check_nginx(config)[0]
    config.write_text('location /cds-ws { proxy_pass http://127.0.0.1:8766; }')
    assert not check_nginx(config)[0]
    assert not check_nginx(Path(tmp_path / 'missing'))[0]
