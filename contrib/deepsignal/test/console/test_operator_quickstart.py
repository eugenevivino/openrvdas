"""Exercise the README's ship setup handoff through the packaged renderer."""

from argparse import ArgumentParser
from pathlib import Path
import re
import shlex

import pytest

from contrib.deepsignal.security.nginx.render_site import add_site_arguments, render_site


README = Path(__file__).resolve().parents[2] / 'console/README.md'


@pytest.mark.parametrize(('scheme', 'listen'), [('http', '80'), ('https', '443 ssl')])
def test_operator_quickstart_renders_guide_example(scheme, listen):
    quickstart = README.read_text().split('### Try it without a ship', 1)[0]
    obsolete = re.search(r'install\.sh|--(?:server-name|nginx-conf|check|uninstall)\b', quickstart)
    assert obsolete is None, f'Competing setup instructions in README: {obsolete.group()}'

    link = re.search(r'\[([^\]]+)\]\((docs/install\.md)#([^)]+)\)', quickstart)
    assert link, 'The ship quick-start must link to the installation section of the guide'
    label, path, anchor = link.groups()
    assert 'install' in label.lower() and 'console' in label.lower()
    guide = (README.parent / path).read_text()
    headings = re.findall(r'^## (.+)$', guide, re.MULTILINE)
    sections = {heading.lower().replace(' ', '-'): heading for heading in headings}
    assert anchor in sections, f'No heading matches #{anchor} in {path}'
    section = guide.split(f'## {sections[anchor]}\n', 1)[1].split('\n## ', 1)[0]
    example = re.search(r'```sh\n(.*?)\n```', section, re.DOTALL)
    assert example, 'The linked section must contain the installer example'
    sudo, installer, *options = shlex.split(example[1].replace('\\\n', ''))
    assert sudo == 'sudo' and Path(installer).name == 'install.sh'

    parser = ArgumentParser(allow_abbrev=False)
    add_site_arguments(parser)
    assert parser.parse_args(options).origin == ['http://ship.example']
    certificate = '/etc/ssl/certs/ship.example.pem'
    key = '/etc/ssl/private/ship.example.key'
    if scheme == 'https':
        assert '`--ssl-certificate`' in section and '`--ssl-certificate-key`' in section
        options[options.index('http://ship.example')] = 'https://ship.example'
        options.extend(['--ssl-certificate', certificate, '--ssl-certificate-key', key])

    site = render_site(parser.parse_args(options)).contents.decode()
    assert f'listen {listen};' in site
    assert 'server_name ship.example;' in site
    assert 'location /console/' in site and 'location = /cds-ws' in site
    assert rf'\A(?:{scheme}://ship\.example)\z' in site
    if scheme == 'https':
        assert f'ssl_certificate {certificate};' in site
        assert f'ssl_certificate_key {key};' in site
    else:
        assert 'ssl_certificate' not in site
