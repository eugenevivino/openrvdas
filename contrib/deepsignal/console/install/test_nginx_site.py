"""Regression tests for selecting the console nginx host and checking the relay."""

import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest


INSTALLER = Path(__file__).with_name('install.sh').resolve()
README = INSTALLER.parent.parent / 'README.md'
SECURITY = README.parents[1] / 'security'
RELAY_TEMPLATES = ('cds-ws.conf', 'cds-ws-react.conf')


class InstallTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.conf = self.root / 'ship.conf'
        self.installer = self.root / 'contrib/deepsignal/console/install/install.sh'
        self.installer.parent.mkdir(parents=True)
        shutil.copyfile(INSTALLER, self.installer)
        shutil.copyfile(INSTALLER.with_name('nginx-site.awk'),
                        self.installer.with_name('nginx-site.awk'))
        self.tools = self.root / 'bin'
        self.tools.mkdir()
        # Simulate root ownership on the developer's filesystem. The trust
        # regressions override ownership or mode for a single fixture path.
        for name, body in {
            'id': 'echo 0',
            'nginx': 'if [ "$1" = -T ]; then printf "# configuration file %s:\\n" '
                     '"$TEST_NGINX_MAIN"; fi',
            'python3': f'exec {shlex.quote(sys.executable)} "$@"',
            'stat': 'for path do :; done\n'
                    'case "$path" in\n'
                    '  "$SERVICE_OWNED") echo "1000 755" ;;\n'
                    '  "$SERVICE_WRITABLE") echo "0 775" ;;\n'
                    '  *) echo "0 755" ;;\n'
                    'esac',
        }.items():
            command = self.tools / name
            command.write_text(f'#!/bin/sh\n{body}\n', encoding='utf-8')
            command.chmod(0o755)

    def run_install(self, *args, env=None):
        return subprocess.run(
            ['/bin/sh', str(self.installer), '--nginx-conf', str(self.conf),
             '--no-reload', '--openrvdas-root', str(self.root), *args],
            env=(os.environ | {'PATH': str(self.tools) + os.pathsep + os.environ['PATH'],
                               'TEST_NGINX_MAIN': str(self.conf)}
                 | (env or {})),
            capture_output=True, text=True, check=False,
        )

    def test_multisite_requires_an_unambiguous_name(self):
        original = 'server { server_name ship; }\nserver { server_name ship other; }\n'
        for args in [(), ('--server-name', 'ship'), ('--server-name', 'absent')]:
            with self.subTest(args=args):
                self.conf.write_text(original, encoding='utf-8')
                result = self.run_install(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('server', result.stderr)
                self.assertEqual(self.conf.read_text(encoding='utf-8'), original)

    def test_install_and_uninstall_only_touch_named_server(self):
        self.stage_static_gate()
        other = ('server {\n    server_name other;\n'
                 '    # BEGIN deepsignal-console\n'
                 '    location /console/ { return 404; }\n'
                 '    # END deepsignal-console\n}\n')
        selected = ('server { # }\n    server_name ship alias;\n'
                    '    location / { return 200 "a } # b"; }}\n')
        suffix = '# Preserve this last line without a newline'
        original = other + selected + suffix
        self.conf.write_text(original, encoding='utf-8')
        result = self.run_install('--server-name', 'alias')
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.conf.read_text(encoding='utf-8')
        self.assertTrue(installed.startswith(other))
        self.assertTrue(installed.endswith(suffix))
        self.assertEqual(installed.count('# BEGIN deepsignal-console'), 2)
        self.assertIn('location = /cds-ws { return 503; }', installed)
        again = self.run_install('--server-name', 'alias')
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(self.conf.read_text(encoding='utf-8'), installed)
        removed = self.run_install('--server-name', 'alias', '--uninstall')
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertEqual(self.conf.read_text(encoding='utf-8'), original)

    def test_rejects_nginx_syntax_in_install_root(self):
        original = 'server {\n    server_name ship;\n}\n'
        self.conf.write_text(original, encoding='utf-8')
        result = self.run_install('--openrvdas-root', '/srv/ship; include extra.conf; #')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--openrvdas-root', result.stderr)
        self.assertEqual(self.conf.read_text(encoding='utf-8'), original)

    def test_refuses_stock_cds_proxy_in_either_template(self):
        for template in ('Django', 'React'):
            with self.subTest(template=template):
                original = (f'# {template}\nserver {{\n    server_name ship;\n'
                            '    location /cds-ws { proxy_pass http://localhost:8766; }\n}\n')
                self.conf.write_text(original, encoding='utf-8')
                result = self.run_install()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('read-only relay', result.stderr)
                self.assertIn('Django and React', result.stderr)
                self.assertIn('UDP', result.stderr)
                self.assertEqual(self.conf.read_text(encoding='utf-8'), original)

    def test_refuses_direct_cds_and_udp_exposure_before_changing_nginx(self):
        checker = self.root / 'contrib/deepsignal/security/check_cds.py'
        checker.parent.mkdir(parents=True)
        checker.write_text('def main(): print("checker ran")\n', encoding='utf-8')
        relay = ('location = /cds-ws { '
                 'proxy_pass http://unix:/run/deepsignal/cds-gateway.sock:; }\n')
        for extra, stream in (
            ('location /raw { proxy_pass http://127.0.0.1:8766; }', ''),
            ('', 'stream { server { listen 6225 udp; proxy_pass 127.0.0.1:6225; } }'),
        ):
            with self.subTest(extra=extra, stream=stream):
                original = (f'events {{}}\nhttp {{ server {{ server_name ship;\n'
                            f'{relay}{extra}\n}} }}\n{stream}\n')
                self.conf.write_text(original, encoding='utf-8')
                result = self.run_install('--udp-port', '6225', '--udp-interface', '127.0.0.1')
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('read-only relay', result.stderr)
                self.assertNotIn('checker ran', result.stdout)
                self.assertEqual(self.conf.read_text(encoding='utf-8'), original)
                self.assertFalse(list(self.root.glob('*.deepsignal-backup-*')))

    def stage_static_gate(self):
        checker = self.root / 'contrib/deepsignal/security/check_cds.py'
        checker.parent.mkdir(parents=True)
        checker.write_text(
            (SECURITY / 'check_cds.py').read_text(encoding='utf-8').split(
                "if __name__ == '__main__':", 1)[0] +
            '\ndef check_cds_listener(**kwargs): return True, "CDS bound"\n'
            'def check_udp_listener(*args): return True, "UDP bound"\n'
            'async def check_live(*args, **kwargs): return []\n',
            encoding='utf-8',
        )
        source = self.root / 'contrib/deepsignal/console/src/pages.ts'
        source.parent.mkdir()
        shutil.copyfile(README.parent / 'src/pages.ts', source)
        return (SECURITY / 'nginx/cds-ws.conf').read_text(encoding='utf-8')

    def test_refuses_direct_cds_in_nested_include_or_sibling_host(self):
        relay = self.stage_static_gate()
        original = f'server {{ server_name ship;\n{relay}\n}}\n'
        extra = 'server { server_name other; location /raw { proxy_pass http://127.0.0.1:8766; } }'
        main = self.root / 'nginx.conf'
        sites = self.root / 'sites'
        sites.mkdir()
        (sites / 'extra.conf').write_text('include sibling.conf;', encoding='utf-8')
        (self.root / 'sibling.conf').write_text(extra, encoding='utf-8')
        for site, includes in (
            (original, 'include sites/*.conf;'),
            (original + extra, ''),
        ):
            with self.subTest(includes=includes):
                self.conf.write_text(site, encoding='utf-8')
                main.write_text(f'events {{}} http {{ include ship.conf; {includes} }}',
                                encoding='utf-8')
                result = self.run_install('--server-name', 'ship',
                                          env={'TEST_NGINX_MAIN': str(main)})
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.conf.read_text(encoding='utf-8'), site)
                self.assertFalse(list(self.root.glob('*.deepsignal-backup-*')))

    def test_refuses_named_stream_upstream_to_cds_udp_bind(self):
        relay = self.stage_static_gate()
        original = (f'events {{}} http {{ server {{ server_name ship;\n{relay}\n}} }}\n'
                    'stream { upstream feed { server 127.0.0.1:6225; } '
                    'server { listen 7225 udp; proxy_pass feed; } }\n')
        self.conf.write_text(original, encoding='utf-8')
        result = self.run_install('--udp-port', '6225', '--udp-interface', '127.0.0.1')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.conf.read_text(encoding='utf-8'), original)
        self.assertFalse(list(self.root.glob('*.deepsignal-backup-*')))

    def test_refuses_variable_proxy_when_relay_is_absent(self):
        self.stage_static_gate()
        original = ('server { server_name ship; set $backend 127.0.0.1:8766; '
                    'location /raw { proxy_pass http://$backend; } }\n')
        self.conf.write_text(original, encoding='utf-8')
        result = self.run_install()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.conf.read_text(encoding='utf-8'), original)
        self.assertFalse(list(self.root.glob('*.deepsignal-backup-*')))

    def test_install_accepts_guarded_relay_in_include(self):
        relay = self.stage_static_gate()
        main = self.root / 'nginx.conf'
        main.write_text('events {} http { include ship.conf; }', encoding='utf-8')
        self.conf.write_text('server { server_name ship; include relay.conf; }', encoding='utf-8')
        (self.root / 'relay.conf').write_text(relay, encoding='utf-8')
        result = self.run_install(env={'TEST_NGINX_MAIN': str(main)})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('# BEGIN deepsignal-console', self.conf.read_text(encoding='utf-8'))
        self.assertNotIn('return 503', self.conf.read_text(encoding='utf-8'))

    def test_backup_stays_out_of_nginx_wildcard_includes(self):
        self.stage_static_gate()
        main = self.root / 'nginx.conf'
        sites = self.root / 'sites'
        sites.mkdir()
        self.conf = sites / 'ship.conf'
        original = 'server { server_name ship; }\n'
        self.conf.write_text(original, encoding='utf-8')
        main.write_text('events {} http { include sites/*; }', encoding='utf-8')
        (self.tools / 'nginx').write_text(
            '#!/bin/sh\n'
            'if [ "$1" = -T ]; then\n'
            '    printf "# configuration file %s:\\n" "$TEST_NGINX_MAIN"\n'
            '    for path in "$TEST_SITES"/*; do\n'
            '        printf "# configuration file %s:\\n" "$path"\n'
            '    done\n'
            'fi\n', encoding='utf-8',
        )
        result = self.run_install(env={'TEST_NGINX_MAIN': str(main), 'TEST_SITES': str(sites)})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(list(sites.glob('ship.conf.deepsignal-backup-*')), [])
        [backup] = sites.glob('.ship.conf.deepsignal-backup-*')
        self.assertEqual(backup.read_text(encoding='utf-8'), original)

    def test_tcp_relay_requires_the_trusted_checker(self):
        original = ('server { server_name ship; location = /cds-ws { '
                    'proxy_pass http://127.0.0.1:8767; } }\n')
        self.conf.write_text(original, encoding='utf-8')
        result = self.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('read-only relay checker is missing', result.stderr)
        self.assertEqual(self.conf.read_text(encoding='utf-8'), original)

    def test_refuses_direct_cds_in_security_templates(self):
        for template in RELAY_TEMPLATES:
            with self.subTest(template=template):
                relay = (SECURITY / 'nginx' / template).read_text(encoding='utf-8')
                self.assertIn('127.0.0.1:8767', relay)
                original = f'server {{ server_name ship;\n{relay.replace("8767", "8766")}\n}}\n'
                self.conf.write_text(original, encoding='utf-8')
                result = self.run_install()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('read-only relay', result.stderr)
                self.assertEqual(self.conf.read_text(encoding='utf-8'), original)
                self.assertFalse(list(self.root.glob('*.deepsignal-backup-*')))

    def test_relay_self_check_reports_missing_checker(self):
        self.conf.write_text(
            'server { server_name ship; location = /cds-ws { '
            'proxy_pass http://unix:/run/deepsignal/cds-gateway.sock:; } }\n',
            encoding='utf-8',
        )
        result = self.run_install('--check')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('read-only relay checker is missing', result.stderr)
        self.assertIn('Django and React', result.stderr)
        self.assertIn('UDP', result.stderr)

    def test_readme_routes_initial_setup_through_the_relay_gate(self):
        readme = README.read_text(encoding='utf-8')
        setup = readme.split('### Try it without a ship', 1)[0]
        command = '/opt/deepsignal-release/contrib/deepsignal/console/install/install.sh'
        self.assertIn(command, setup)
        self.assertNotIn('sudo /opt/openrvdas/', setup)
        self.assertIn('install.sh --check', setup)
        self.assertIn('Django and React', setup)
        self.assertIn('UDP', setup)
        self.assertNotIn('location /console/', setup)

    def test_relay_self_check_refuses_a_release_missing_its_checker(self):
        original = ('server { server_name ship; location = /cds-ws { '
                    'proxy_pass http://unix:/run/deepsignal/cds-gateway.sock:; } }\n')
        self.conf.write_text(original, encoding='utf-8')
        # A checker in the service checkout cannot replace the release checker.
        deployment = self.root / 'deployment'
        checker = deployment / 'contrib/deepsignal/security/check_cds.py'
        checker.parent.mkdir(parents=True)
        checker.write_text('raise SystemExit(0)\n', encoding='utf-8')

        for args in ((), ('--check',)):
            with self.subTest(args=args):
                result = self.run_install('--openrvdas-root', str(deployment), *args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('read-only relay checker is missing', result.stderr)
                self.assertEqual(self.conf.read_text(encoding='utf-8'), original)

    def test_relay_self_check_delegates_to_197_and_propagates_failure(self):
        self.conf.write_text(
            'server { server_name ship; location = /cds-ws { '
            'proxy_pass http://unix:/run/deepsignal/cds-gateway.sock:; } }\n',
            encoding='utf-8',
        )
        checker = self.root / 'contrib/deepsignal/security/check_cds.py'
        checker.parent.mkdir(parents=True)
        for exit_code in (0, 1):
            with self.subTest(exit_code=exit_code):
                checker.write_text(
                    'def main():\n    print("#197 checker called")\n'
                    f'    raise SystemExit({exit_code})\n'
                    'if __name__ == "__main__": main()\n', encoding='utf-8',
                )
                result = self.run_install('--check')
                self.assertEqual(result.returncode, exit_code, result.stderr)
                self.assertIn('#197 checker called', result.stdout)
                if exit_code:
                    original = self.conf.read_bytes()
                    result = self.run_install()
                    self.assertEqual(result.returncode, exit_code, result.stderr)
                    self.assertIn('#197 checker called', result.stdout)
                    self.assertEqual(self.conf.read_bytes(), original)

    def test_relay_self_check_passes_the_optional_udp_bind_to_197(self):
        self.conf.write_text(
            'server { server_name ship; location /cds-ws { '
            'proxy_pass http://unix:/run/deepsignal/cds-gateway.sock:; } }\n',
            encoding='utf-8',
        )
        checker = self.root / 'contrib/deepsignal/security/check_cds.py'
        checker.parent.mkdir(parents=True)
        checker.write_text(
            'import sys\n'
            'def main():\n'
            '    assert sys.argv[-4:] == ["--udp-port", "6225", "--udp-interface", "127.0.0.1"]\n'
            'if __name__ == "__main__": main()\n',
            encoding='utf-8',
        )
        result = self.run_install('--check', '--udp-port', '6225', '--udp-interface', '127.0.0.1')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_refuses_service_writable_checker_and_helper_before_execution(self):
        original = ('server { server_name ship; location = /cds-ws { '
                    'proxy_pass http://unix:/run/deepsignal/cds-gateway.sock:; } }\n')
        self.conf.write_text(original, encoding='utf-8')
        checker = self.root / 'contrib/deepsignal/security/check_cds.py'
        checker.parent.mkdir(parents=True)
        checker.write_text('print("checker executed")\n', encoding='utf-8')
        helper = self.installer.with_name('nginx-site.awk')
        with helper.open('a', encoding='utf-8') as stream:
            stream.write('\nBEGIN { print "helper executed" > "/dev/stderr" }\n')

        checker_diagnostic = '#197 read-only relay checker'
        for variable, path, diagnostic, marker in (
            ('SERVICE_OWNED', checker, checker_diagnostic, 'checker executed'),
            ('SERVICE_WRITABLE', checker.parent, checker_diagnostic, 'checker executed'),
            ('SERVICE_WRITABLE', helper, 'nginx-site.awk', 'helper executed'),
            ('SERVICE_OWNED', helper.parent, 'install.sh', 'helper executed'),
        ):
            with self.subTest(path=path):
                result = self.run_install(env={variable: str(path.resolve())})
                self.assertNotIn(marker, result.stdout + result.stderr)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(diagnostic, result.stderr)
                self.assertIn('root-owned', result.stderr)
                self.assertEqual(self.conf.read_text(encoding='utf-8'), original)
                self.assertFalse(list(self.root.glob('*.deepsignal-backup-*')))

    def test_relay_self_check_uses_selected_host_port_and_config(self):
        checker = self.root / 'contrib/deepsignal/security/check_cds.py'
        checker.parent.mkdir(parents=True)
        checker.write_text(
            'import os, sys\n'
            'from pathlib import Path\n'
            'from types import SimpleNamespace\n'
            'websockets = SimpleNamespace(connect=lambda uri, **kwargs: kwargs)\n'
            'def main():\n'
            '    url = sys.argv[sys.argv.index("--gateway-url") + 1]\n'
            '    assert url == os.environ["TEST_GATEWAY_URL"], url\n'
            '    source = sys.argv[sys.argv.index("--console-source") + 1]\n'
            '    assert source == os.environ["TEST_CONSOLE_SOURCE"], source\n'
            '    assert websockets.connect(url) == {\n'
            '        "host": os.environ["TEST_ADDRESS"], "origin": os.environ["TEST_ORIGIN"]\n'
            '    }\n'
            '    assert websockets.connect("ws://127.0.0.1:8766") == {}\n'
            '    for flag in ("--nginx-config", "--nginx-react-config", "--nginx-site"):\n'
            '        assert sys.argv[sys.argv.index(flag) + 1] == os.environ["TEST_NGINX_MAIN"]\n'
            '    snapshot_path = sys.argv[sys.argv.index("--nginx-site-snapshot") + 1]\n'
            '    snapshot = Path(snapshot_path).read_bytes()\n'
            '    assert b"server_name ship.example" in snapshot and b"other.example" in snapshot\n'
            '    offset = int(sys.argv[sys.argv.index("--nginx-server-offset") + 1])\n'
            '    assert snapshot[offset:].startswith(b"{ listen ")\n'
            '    assert b"server_name ship.example" in snapshot[offset:]\n'
            '    assert b"server_name other.example" in snapshot[:offset]\n'
            '    assert websockets.connect(url, origin="https://foreign.invalid") == {\n'
            '        "host": os.environ["TEST_ADDRESS"], "origin": "https://foreign.invalid"\n'
            '    }\n'
            'if __name__ == "__main__": main()\n',
            encoding='utf-8',
        )
        listeners = (
            ('80', 'http', '80', '127.0.0.1'),
            ('443 ssl', 'https', '443', '127.0.0.1'),
            ('8080', 'http', '8080', '127.0.0.1'),
            ('*:8443 ssl', 'https', '8443', '127.0.0.1'),
            ('[::]:8444 ssl', 'https', '8444', '::1'),
        )
        for listen, scheme, port, address in listeners:
            with self.subTest(listen=listen):
                self.conf.write_text(
                    'server { server_name other.example; location /cds-ws { '
                    'proxy_pass http://localhost:8766; } }\n'
                    f'server {{ listen {listen}; server_name ship.example; location /cds-ws {{ '
                    'proxy_pass http://unix:/run/deepsignal/cds-gateway.sock:; } }\n',
                    encoding='utf-8',
                )
                ws = 'wss' if scheme == 'https' else 'ws'
                origin_port = '' if port in ('80', '443') else f':{port}'
                deployment = self.root / 'deployment'
                result = self.run_install(
                    '--check', '--server-name', 'ship.example', '--openrvdas-root', str(deployment),
                    env={
                        'TEST_GATEWAY_URL': f'{ws}://ship.example:{port}/cds-ws',
                        'TEST_ORIGIN': f'{scheme}://ship.example{origin_port}',
                        'TEST_ADDRESS': address,
                        'TEST_CONSOLE_SOURCE': str(deployment / 'contrib/deepsignal/console'),
                    },
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_197_gate_through_django_and_react_nginx(self):
        source = SECURITY / 'check_cds.py'
        self.assertTrue(source.is_file(), '#197 check_cds.py is required for the integration test')

        nginx = shutil.which('nginx')
        self.assertIsNotNone(nginx, 'nginx is required to run the #197 integration test')
        nginx_command = self.tools / 'nginx'
        nginx_command.write_text(
            f'#!/bin/sh\nexec {shlex.quote(nginx)} -p {shlex.quote(str(self.root) + "/")} '
            f'-c {shlex.quote(str(self.root / "nginx.conf"))} "$@"\n',
            encoding='utf-8',
        )
        checker = self.root / 'contrib/deepsignal/security/check_cds.py'
        checker.parent.mkdir(parents=True)
        shutil.copyfile(source, checker)
        console_source = self.root / 'contrib/deepsignal/console/src/pages.ts'
        console_source.parent.mkdir(parents=True)
        shutil.copyfile(README.parent / 'src/pages.ts', console_source)
        for name, body in {
            'ss': 'echo "LISTEN 0 128 127.0.0.1:8766 0.0.0.0:*"',
            'supervisorctl': 'exit 0',
        }.items():
            command = self.tools / name
            command.write_text(f'#!/bin/sh\n{body}\n', encoding='utf-8')
            command.chmod(0o755)

        app_routes = ('location / { uwsgi_pass unix:/tmp/django.sock; }',
                      'location / { try_files $uri /index.html; }')
        for snippet, app_route in zip(RELAY_TEMPLATES, app_routes):
            with self.subTest(snippet=snippet):
                route = (SECURITY / 'nginx' / snippet).read_text(encoding='utf-8')
                asyncio.run(self.exercise_live_gate(nginx, route, app_route))

    @contextmanager
    def running_nginx(self, nginx, listener):
        nginx_conf = self.root / 'nginx.conf'
        nginx_conf.write_text(
            'daemon off; master_process off; error_log stderr; pid nginx.pid;\n'
            'events {}\nhttp { access_log off;\n'
            'client_body_temp_path client_body; proxy_temp_path proxy;\n'
            'fastcgi_temp_path fastcgi; uwsgi_temp_path uwsgi; scgi_temp_path scgi;\n'
            f'include "{self.conf}";\n}}\n', encoding='utf-8',
        )
        # nginx inherits the already listening socket, so clients can connect at startup.
        fd = listener.fileno()
        process = subprocess.Popen(
            [nginx, '-p', str(self.root) + '/', '-c', str(nginx_conf)],
            stderr=subprocess.PIPE, text=True, pass_fds=(fd,),
            env=os.environ | {'NGINX': f'{fd};'},
        )
        try:
            yield
            if process.poll() is not None:
                self.fail(process.stderr.read())
        finally:
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=5)

    async def exercise_live_gate(self, nginx, route, app_route):
        from contrib.deepsignal.security.cds_gateway import ReadOnlyGateway
        import websockets

        cache = {'temperature': [[1, 19.1]]}
        publishes = []

        async def cached_data(websocket):
            fields = {}
            async for message in websocket:
                request = json.loads(message)
                kind = request['type']
                response = {'type': kind, 'status': 200}
                if kind == 'publish':
                    record = request['data']
                    publishes.append(record)
                    for field, value in record['fields'].items():
                        cache.setdefault(field, []).append([record['timestamp'], value])
                elif kind == 'subscribe':
                    fields = request['fields']
                elif kind == 'ready':
                    response = {'type': 'data', 'data': {field: cache[field] for field in fields}}
                await websocket.send(json.dumps(response))

        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            port = listener.getsockname()[1]
            site = (f'server {{ listen 127.0.0.1:{port} default_server; return 404; }}\n'
                    f'server {{ listen 127.0.0.1:{port}; server_name ship.example;\n'
                    f'{app_route}\n{route}\n}}\n')
            self.conf.write_text(site, encoding='utf-8')
            async with websockets.serve(cached_data, '127.0.0.1', 8766):
                gateway = ReadOnlyGateway()
                async with websockets.serve(gateway.handler, '127.0.0.1', 8767):
                    for args in ((), ('--check',)):
                        with self.running_nginx(nginx, listener):
                            result = await asyncio.to_thread(self.run_install, '--server-name',
                                                             'ship.example', *args)
                            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                            self.assertIn('live publish through the gateway is refused',
                                          result.stdout)
                            self.assertIn('live subscribe through the gateway returns data',
                                          result.stdout)
                            self.assertIn('nginx refuses a WebSocket with a foreign Origin',
                                          result.stdout)
                            self.assertIn('# BEGIN deepsignal-console', self.conf.read_text())
                    self.assertEqual(cache['temperature'], [[1, 19.1]])
                    # Only the checker's two direct loopback seeds may reach the cache.
                    self.assertEqual([record['fields'] for record in publishes],
                                     [{'deepsignal_gateway_self_test': 1}] * 2)

                self.conf.write_text(site, encoding='utf-8')
                async with websockets.serve(cached_data, '127.0.0.1', 8767):
                    with self.running_nginx(nginx, listener):
                        result = await asyncio.to_thread(self.run_install, '--server-name',
                                                         'ship.example')
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn('FAIL: gateway accepted a live publish', result.stdout)
                        self.assertEqual(self.conf.read_text(encoding='utf-8'), site)


if __name__ == '__main__':
    unittest.main()
