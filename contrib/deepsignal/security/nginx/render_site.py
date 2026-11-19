"""Render the one nginx site owned by the DeepSignal Console installer."""

from dataclasses import dataclass
from pathlib import Path
import re


TEMPLATE = Path(__file__).with_name('deepsignal-console.conf.template')
SITE_NAME = 'deepsignal-console.conf'
CDS_PORTS = (8766, 8767)
_PATH = re.compile(r'/[a-zA-Z0-9_./-]*')
_LABEL = r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
_ORIGIN = re.compile(rf'(https?)://({_LABEL}(?:\.{_LABEL})*)(?::([1-9][0-9]{{0,4}}))?')


def add_site_arguments(parser):
    parser.add_argument('--nginx-site', type=Path, help='installer-owned nginx site')
    parser.add_argument('--openrvdas-root', default='/opt/openrvdas')
    parser.add_argument('--origin', action='append', help='allowed console origin (repeatable)')
    parser.add_argument('--ssl-certificate')
    parser.add_argument('--ssl-certificate-key')


def _absolute_path(path, option):
    if not path or not _PATH.fullmatch(path):
        raise ValueError(f'{option} must be an absolute path without nginx syntax.')
    return path


@dataclass(frozen=True)
class Site:
    contents: bytes
    gateway_url: str
    port: int


def render_site(args):
    if not args.origin:
        raise ValueError('Supply a console origin with --origin.')
    origins = list(dict.fromkeys(args.origin))
    hosts = []
    listeners = set()
    for origin in origins:
        match = _ORIGIN.fullmatch(origin)
        if match is None:
            raise ValueError('Use a canonical HTTP(S) origin with a concrete host and no path.')
        scheme, host, explicit_port = match.groups()
        default_port = 443 if scheme == 'https' else 80
        port = int(explicit_port) if explicit_port else default_port
        if port > 65535 or explicit_port and port == default_port:
            raise ValueError('Use a valid origin port and omit the scheme’s default port.')
        if any(abs(port - cds_port) <= 1 for cds_port in CDS_PORTS):
            raise ValueError('The console listener is too close to a CDS port.')
        hosts.append(host)
        listeners.add((scheme, port))
    if len(listeners) != 1:
        raise ValueError('One nginx site requires all origins to share a scheme and port.')
    (scheme, port), = listeners
    tls = ''
    if scheme == 'https':
        certificate = _absolute_path(args.ssl_certificate, '--ssl-certificate')
        key = _absolute_path(args.ssl_certificate_key, '--ssl-certificate-key')
        tls = f'    ssl_certificate {certificate};\n    ssl_certificate_key {key};\n'
    elif args.ssl_certificate or args.ssl_certificate_key:
        raise ValueError('TLS certificates require an HTTPS console origin.')
    root = _absolute_path(args.openrvdas_root, '--openrvdas-root').rstrip('/')
    values = {
        'LISTEN': f'{port} ssl' if tls else str(port),
        'SERVER_NAMES': ' '.join(hosts),
        'TLS': tls,
        'CONSOLE_DIST': f'{root}/contrib/deepsignal/console/dist/',
        'ORIGINS': r'\A(?:' + '|'.join(origin.replace('.', r'\.') for origin in origins) + r')\z',
    }
    template = TEMPLATE.read_bytes()
    contents = re.sub(rb'@@([A-Z_]+)@@', lambda m: values[m[1].decode()].encode(), template)
    gateway_url = 'ws' + origins[0][4:] + '/cds-ws'
    return Site(contents, gateway_url, port)


def check_site(path, rendered):
    try:
        matches = path.is_file() and not path.is_symlink() and path.read_bytes() == rendered
    except OSError:
        matches = False
    if matches:
        return True, f'PASS: {path} matches the installed console template.'
    return False, f'FAIL: {path} differs from the installed console template.'
