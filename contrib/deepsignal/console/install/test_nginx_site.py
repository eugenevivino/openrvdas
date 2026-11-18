"""Regression tests for selecting the console nginx host and checking the relay."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


INSTALLER = Path(__file__).with_name('install.sh').resolve()
README = INSTALLER.parent.parent / 'README.md'


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
        (self.tools / 'python3').symlink_to(sys.executable)
        for name, body in {'id': 'echo 0', 'nginx': 'exit 0'}.items():
            command = self.tools / name
            command.write_text(f'#!/bin/sh\n{body}\n', encoding='utf-8')
            command.chmod(0o755)

    def run_install(self, *args):
        return subprocess.run(
            ['/bin/sh', str(self.installer), '--nginx-conf', str(self.conf),
             '--no-reload', '--openrvdas-root', str(self.root), *args],
            env=os.environ | {'PATH': str(self.tools) + os.pathsep + os.environ['PATH']},
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
        self.assertIn('sudo /opt/openrvdas/contrib/deepsignal/console/install/install.sh', setup)
        self.assertIn('install.sh --check', setup)
        self.assertIn('Django and React', setup)
        self.assertIn('UDP', setup)
        self.assertNotIn('location /console/', setup)

    def test_relay_self_check_refuses_a_deployment_missing_its_checker(self):
        original = ('server { server_name ship; location = /cds-ws { '
                    'proxy_pass http://unix:/run/deepsignal/cds-gateway.sock:; } }\n')
        self.conf.write_text(original, encoding='utf-8')
        # A checker in the staging checkout cannot verify a different installation.
        staged_checker = self.root / 'contrib/deepsignal/security/check_cds.py'
        staged_checker.parent.mkdir(parents=True)
        staged_checker.write_text('raise SystemExit(0)\n', encoding='utf-8')
        deployment = self.root / 'deployment'
        deployment.mkdir()

        result = self.run_install('--check', '--openrvdas-root', str(deployment))
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
                checker.write_text(f'print("#197 checker called")\nraise SystemExit({exit_code})\n',
                                   encoding='utf-8')
                result = self.run_install('--check')
                self.assertEqual(result.returncode, exit_code, result.stderr)
                self.assertIn('#197 checker called', result.stdout)

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
            'assert sys.argv[1:] == ["--udp-port", "6225", "--udp-interface", "127.0.0.1"]\n',
            encoding='utf-8',
        )
        result = self.run_install('--check', '--udp-port', '6225', '--udp-interface', '127.0.0.1')
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
