"""Exercise the README's ship setup handoff through the packaged renderer."""

from argparse import ArgumentParser
from pathlib import Path
import re
import shlex

import pytest

from contrib.deepsignal.security.nginx.render_site import add_site_arguments, render_site


README = Path(__file__).resolve().parents[2] / 'console/README.md'
INSTALLER = '/opt/deepsignal-release/contrib/deepsignal/console/install/install.sh'
GUIDE = 'docs/install.md'
INSTALL_ANCHOR = 'configure-nginx-and-install'
CHECK_ANCHOR = 'check-or-remove-the-site'
INSTALL_LINK = (
    f'[Install the DeepSignal Console (root-owned installer at {INSTALLER})]'
    f'({GUIDE}#{INSTALL_ANCHOR})'
)
CHECK_LINK = f'[Installed-site verification (install.sh --check)]({GUIDE}#{CHECK_ANCHOR})'
GUIDE_REFERENCES = (
    'For Django and React deployments, follow the release prerequisites.\n\n'
    f'{INSTALL_LINK}\n\n'
    'Verify the installed site with every option used for installation.\n\n'
    f'{CHECK_LINK}\n'
)

# Mask comments, fenced code and HTML containers before checking link visibility.
NON_PROSE = re.compile(
    r'<!--.*?(?:-->|\Z)'
    r'|^ {0,3}(?P<fence>(?P<marker>`|~)(?P=marker){2,})[^\n]*\n.*?'
    r'(?:^ {0,3}(?P=fence)(?P=marker)*[ \t]*$|\Z)'
    r'|<(?P<tag>details|div|pre|script|span|style|template)\b[^>]*>.*?(?:</(?P=tag)\s*>|\Z)',
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
COMPETING_SETUP = re.compile(
    r'install\.sh\b|--(?:server-name|nginx-conf|udp-port|udp-interface|check|uninstall)\b'
    r'|\blocation\s+(?:=\s*)?/(?:console/|cds-ws)'
    r'|\b(?:http|server)\s*\{|\b(?:listen|proxy_pass)\s+[^;\n]+;'
)


def assert_guide_handoff(quickstart):
    visible = NON_PROSE.sub('[non-prose block]', quickstart)
    paragraphs = [part.rstrip(' \t') for part in re.split(r'\n(?:[ \t]*\n)+', visible.strip('\n'))]
    for link in (INSTALL_LINK, CHECK_LINK):
        assert paragraphs.count(link) == 1, f'Expected one standalone, visible guide link: {link}'
        quickstart = quickstart.replace(link, '', 1)

    competing = COMPETING_SETUP.search(quickstart.replace('\\\n', ''))
    assert competing is None, f'Competing setup outside the guide links: {competing.group()}'

    guide = (README.parent / GUIDE).read_text()
    sections = {
        heading.lower().replace(' ', '-'): body
        for heading, body in re.findall(r'^## ([^\n]+)\n(.*?)(?=^## |\Z)', guide, re.M | re.S)
    }
    for anchor in (INSTALL_ANCHOR, CHECK_ANCHOR):
        assert anchor in sections, f'No heading matches #{anchor} in {GUIDE}'
    return sections[INSTALL_ANCHOR]


def test_quickstart_accepts_guide_references():
    assert_guide_handoff(GUIDE_REFERENCES)


@pytest.mark.parametrize(('instruction', 'offending'), [
    pytest.param(f'sudo {INSTALLER}', 'install.sh', id='bare-install'),
    pytest.param('Run `install.sh --check`.', 'install.sh', id='inline-check'),
    pytest.param('Add --uninstall to remove the site.', '--uninstall', id='prose-uninstall'),
    pytest.param(f'```sh\nsudo {INSTALLER}\n```', 'install.sh', id='fenced'),
    pytest.param(f'    sudo {INSTALLER}', 'install.sh', id='indented'),
    pytest.param(f'sudo \\\n  {INSTALLER}', 'install.sh', id='continued'),
    pytest.param(f'sudo {INSTALLER.replace("deepsignal-release", "openrvdas")}',
                 'install.sh', id='deployment-tree-installer'),
    pytest.param('Set --server-name ship.example.', '--server-name', id='server-name'),
    pytest.param('Set --nginx-conf /etc/nginx/nginx.conf.', '--nginx-conf', id='nginx-conf'),
    pytest.param('Set --udp-port 8766.', '--udp-port', id='udp-port'),
    pytest.param('Set --udp-interface eth0.', '--udp-interface', id='udp-interface'),
    pytest.param('```nginx\nlocation /console/ {\n}\n```', 'location /console/', id='nginx'),
    pytest.param(f'sudo {INSTALLER} --origin http://ship.example', 'install.sh', id='http'),
    pytest.param(
        f'sudo {INSTALLER} --origin https://ship.example \\\n'
        '  --ssl-certificate /etc/ssl/certs/ship.example.pem \\\n'
        '  --ssl-certificate-key /etc/ssl/private/ship.example.key',
        'install.sh', id='https',
    ),
])
def test_quickstart_rejects_competing_setup(instruction, offending):
    message = f'Competing setup outside the guide links: {offending}'
    with pytest.raises(AssertionError, match=re.escape(message)):
        assert_guide_handoff(f'{GUIDE_REFERENCES}\n{instruction}\n')


@pytest.mark.parametrize(('link', 'substitute'), [
    pytest.param(INSTALL_LINK, f'<!--\n\n{INSTALL_LINK}\n\n-->', id='commented-install'),
    pytest.param(CHECK_LINK, f'```md\n\n{CHECK_LINK}\n\n```', id='fenced-check'),
    pytest.param(INSTALL_LINK, f'<div hidden>\n\n{INSTALL_LINK}\n\n</div>', id='hidden-install'),
    pytest.param(CHECK_LINK, f'    {CHECK_LINK}', id='indented-check'),
    pytest.param(INSTALL_LINK, f'sudo \\\n{INSTALL_LINK}', id='wrapped-in-command'),
    pytest.param(CHECK_LINK, CHECK_LINK.replace('--check', '--check; sudo nginx -s reload'),
                 id='shell-in-label'),
    pytest.param(INSTALL_LINK, INSTALL_LINK.replace('deepsignal-release', 'openrvdas'),
                 id='untrusted-install-link'),
    pytest.param(INSTALL_LINK, INSTALL_LINK.replace(INSTALL_ANCHOR, 'check'),
                 id='wrong-install-anchor'),
    pytest.param(CHECK_LINK, CHECK_LINK.replace(CHECK_ANCHOR, 'install'),
                 id='wrong-check-anchor'),
])
def test_quickstart_requires_visible_guide_links(link, substitute):
    with pytest.raises(AssertionError, match='Expected one standalone, visible guide link'):
        assert_guide_handoff(GUIDE_REFERENCES.replace(link, substitute))


@pytest.mark.parametrize(('scheme', 'listen'), [('http', '80'), ('https', '443 ssl')])
def test_operator_quickstart_renders_guide_example(scheme, listen):
    quickstart = README.read_text().split('### Try it without a ship', 1)[0]
    section = assert_guide_handoff(quickstart)
    example = re.search(r'```sh\n(.*?)\n```', section, re.DOTALL)
    assert example, 'The linked section must contain the installer example'
    sudo, installer, *options = shlex.split(example[1].replace('\\\n', ''))
    assert (sudo, installer) == ('sudo', INSTALLER)

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
    assert 'location /console/ {' in site
    assert 'location = /cds-ws {' in site
    assert 'proxy_pass http://127.0.0.1:8767;' in site
    assert rf'if ($http_origin !~ "\A(?:{scheme}://ship\.example)\z")' in site
    if scheme == 'https':
        assert f'ssl_certificate {certificate};' in site
        assert f'ssl_certificate_key {key};' in site
    else:
        assert 'ssl_certificate' not in site
