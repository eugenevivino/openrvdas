"""Fail-closed inventory of configuration outside the installer-owned site."""

from __future__ import annotations

from dataclasses import dataclass
import fnmatch
from pathlib import Path
import re
import stat


# A deliberately limited grammar for adjacent sites. Directives that can select a
# backend, load configuration, or execute code need explicit classification.
_LEAF = {
    'main': frozenset('daemon master_process pid user worker_processes worker_rlimit_nofile '
                      'worker_shutdown_timeout'.split()),
    'events': frozenset('worker_connections multi_accept use accept_mutex'.split()),
    'http': frozenset('access_log default_type log_format sendfile tcp_nopush tcp_nodelay '
                      'keepalive_timeout types_hash_max_size server_names_hash_bucket_size '
                      'server_tokens gzip gzip_types gzip_vary client_max_body_size '
                      'client_body_temp_path proxy_temp_path fastcgi_temp_path '
                      'uwsgi_temp_path scgi_temp_path ssl_protocols ssl_prefer_server_ciphers '
                      'ssl_ciphers ssl_session_cache ssl_session_timeout'.split()),
    'web': frozenset('access_log root alias index try_files return add_header '
                     'client_max_body_size autoindex default_type proxy_set_header '
                     'proxy_http_version proxy_read_timeout proxy_send_timeout '
                     'proxy_buffering proxy_redirect fastcgi_param uwsgi_param scgi_param '
                     'ssl_certificate ssl_certificate_key ssl_protocols ssl_ciphers '
                     'ssl_session_cache ssl_session_timeout ssl_prefer_server_ciphers'.split()),
    'server': frozenset({'server_name'}),
    'stream': frozenset('access_log log_format proxy_timeout proxy_connect_timeout '
                        'ssl_preread proxy_protocol'.split()),
    'upstream': frozenset({'keepalive', 'least_conn', 'ip_hash', 'zone'}),
}
_BLOCKS = {
    'main': {'events': 'events', 'http': 'http', 'stream': 'stream'},
    'http': {'server': 'server', 'upstream': 'http_upstream', 'types': 'types'},
    'stream': {'server': 'stream_server', 'upstream': 'stream_upstream'},
    'server': {'location': 'location', 'types': 'types'},
    'location': {'location': 'location', 'types': 'types'},
}
_PROXIES = {
    'proxy_pass': ('http', 'https'),
    'grpc_pass': ('grpc', 'grpcs'),
    'uwsgi_pass': ('uwsgi', 'suwsgi'),
    'fastcgi_pass': (),
    'scgi_pass': (),
    'memcached_pass': (),
}
_MODULE = re.compile(r'(?:/?[\w./-]+/)?ngx_(?:stream|http_geoip|http_image_filter|'
                     r'http_xslt_filter|http_perl|stream_geoip|mail)_module\.so')
_TOKEN = re.compile(
    r'''[ \t\r\n]+|\#[^\n]*|[{};]|"(?:[^"\\\n])*"|'(?:[^'\\\n])*'|'''
    r'''(?:\$\{[a-zA-Z_0-9]+\}|[^ \t\r\n{};'"\\#])+'''
)
_INCLUDE = re.compile(r'/?[a-zA-Z0-9_.?*/-]+')
_HEADER = re.compile(rb'^# configuration file (/[^\r\n]+):\n', re.MULTILINE)
_ADDRESS = r'(?:\[[0-9a-fA-F:.]+\]|[a-zA-Z0-9_.-]+|\*)'
_PORT = r'[0-9]{1,5}'
_LISTEN = re.compile(rf'(?:(?:{_ADDRESS}:)?({_PORT})(?:-({_PORT}))?|({_ADDRESS}))')
_BACKEND = re.compile(rf'({_ADDRESS})(?::({_PORT}))?')
_UNIX = re.compile(r'unix:/[a-zA-Z0-9_./-]+(?::/[^\s;{}]*)?')
_WORD = re.compile(r'[a-zA-Z0-9_.-]+')


class InventoryError(ValueError):
    pass


@dataclass
class Directive:
    words: tuple
    line: int
    children: list | None


def _directives(data):
    contents = data.decode('utf-8')
    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', contents):
        raise ValueError('unexpected control character')
    stack = [[]]
    words = []
    line = start_line = 1
    end = 0
    for token in _TOKEN.finditer(contents):
        if token.start() != end:
            raise ValueError(f'unrecognized syntax at line {line}')
        end = token.end()
        value = token[0]
        if value[0] in ' \t\r\n#':
            line += value.count('\n')
            continue
        if value == '}':
            if words or len(stack) == 1:
                raise ValueError(f'unexpected closing brace at line {line}')
            stack.pop()
        elif value in (';', '{'):
            if not words:
                raise ValueError(f'empty directive at line {line}')
            children = [] if value == '{' else None
            stack[-1].append(Directive(tuple(words), start_line, children))
            if children is not None:
                stack.append(children)
            words = []
        else:
            if not words:
                start_line = line
            boundary = ' \t\r\n;{}'
            if words and words[0] == 'if' and value[0] in ('"', "'"):
                boundary += ')'
            if end < len(contents) and contents[end] not in boundary:
                raise ValueError(f'unsupported token boundary at line {line}')
            words.append(value[1:-1] if value[0] in ('"', "'") else value)
    if end != len(contents) or words or len(stack) != 1:
        raise ValueError(f'incomplete configuration at line {line}')
    return stack[0]


def _listen_port(target):
    if _UNIX.fullmatch(target):
        return None
    match = _LISTEN.fullmatch(target)
    if match is None:
        raise ValueError('unclassifiable listen endpoint')
    first, last, host_only = match.groups()
    if host_only and host_only.isdecimal():
        raise ValueError('invalid listen port')
    lo = int(first or 80)
    hi = int(last or lo)
    if not 1 <= lo <= hi <= 65535:
        raise ValueError('invalid listen port or range')
    return lo, hi


def _backend_port(target, protocols, *, default, path=False):
    if '$' in target:
        raise ValueError('variable backend')
    scheme, separator, endpoint = target.partition('://')
    if separator:
        if scheme not in protocols:
            raise ValueError('unclassifiable backend protocol')
        if scheme in ('https', 'grpcs'):
            default = 443
    else:
        if protocols and 'http' in protocols:
            raise ValueError('missing proxy backend protocol')
        endpoint = target
    if _UNIX.fullmatch(endpoint):
        return None
    if path and separator:
        endpoint = re.split(r'[/\?]', endpoint, maxsplit=1)[0]
    match = _BACKEND.fullmatch(endpoint)
    if match is None:
        raise ValueError('unclassifiable backend endpoint')
    if match[2] is None:
        if default is None and not _WORD.fullmatch(match[1]):
            raise ValueError('unclassifiable upstream name')
        return default
    port = int(match[2])
    if not 1 <= port <= 65535:
        raise ValueError('invalid backend port')
    return port


class Inventory:
    def __init__(self, main, site, owned, protected_ports):
        self.main = main
        self.site = site
        self.real_site = site.resolve()
        self.owned = owned
        self.protected_ports = protected_ports
        self.files = {}
        self.problems = []
        self.active = set()
        self.site_uses = 0
        self.upstreams = {'http': set(), 'stream': set()}
        self.references = []

    def issue(self, path, message):
        self.problems.append(f'{path}: {message}')

    def inspect_file(self, path, context):
        if path == self.site:
            self.site_uses += 1
            if context != 'http':
                self.issue(path, 'installer site must be included directly in http')
        try:
            if path != self.site and path.resolve() == self.real_site:
                raise ValueError('installer site is included through an alias')
            if path == self.site and not path.exists() and not path.is_symlink():
                return
            real = path.resolve(strict=True)
            if real in self.active:
                raise ValueError('cyclic include')
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError('expected a regular configuration file')
            data = path.read_bytes()
            if path in self.files and self.files[path] != data:
                raise ValueError('configuration changed during inventory')
            self.files[path] = data
            if path == self.site:
                if path.is_symlink() or data not in (b'', self.owned):
                    raise ValueError('site differs from the rendered template')
                return
            directives = _directives(data)
        except (OSError, ValueError, RuntimeError) as exc:
            self.issue(path, str(exc))
            return
        self.active.add(real)
        try:
            self.inspect(directives, path, context)
        finally:
            self.active.remove(real)

    def include(self, pattern, context):
        suffix = Path(pattern)
        if not _INCLUDE.fullmatch(pattern) or '..' in suffix.parts:
            raise ValueError('unclassifiable include path')
        path = self.main.parent / suffix
        if any(c in str(path.parent) for c in '*?'):
            raise ValueError('wildcards in include directories are unsupported')
        if not any(c in path.name for c in '*?'):
            if path != self.site and not path.is_file():
                raise ValueError(f'missing or non-regular include {path}')
            self.inspect_file(path, context)
            return
        if path.name.startswith('.'):
            raise ValueError('hidden-file includes are unsupported')
        candidates = {entry for entry in path.parent.iterdir()
                      if not entry.name.startswith('.') and
                      fnmatch.fnmatchcase(entry.name, path.name)}
        if (path.parent.resolve() == self.real_site.parent and
                fnmatch.fnmatchcase(self.site.name, path.name)):
            candidates.add(path.parent / self.site.name)
        for candidate in sorted(candidates):
            self.inspect_file(candidate, context)

    def inspect(self, directives, path, context):
        for directive in directives:
            name, *args = directive.words
            try:
                if directive.children is None:
                    self.leaf(name, args, path, context, directive.line)
                else:
                    self.block(name, args, directive.children, path, context)
            except (OSError, ValueError) as exc:
                self.issue(path, f'line {directive.line}: {exc}')

    def block(self, name, args, children, path, context):
        child_context = _BLOCKS.get(context, {}).get(name)
        if child_context is None:
            raise ValueError(f'unclassifiable {name} block in {context}')
        if name == 'upstream' and len(args) == 1 and _WORD.fullmatch(args[0]):
            self.upstreams[context].add(args[0].lower())
        elif name == 'location' and len(args) in (1, 2):
            if ((len(args) == 2 and args[0] not in ('=', '^~')) or
                    not args[-1].startswith(('/', '@'))):
                raise ValueError('unclassifiable location modifier or path')
            if args[-1].startswith('/cds-ws'):
                raise ValueError('unowned /cds-ws location')
        elif args or name in ('upstream', 'location'):
            raise ValueError(f'unexpected arguments to {name}')
        self.inspect(children, path, child_context)

    def leaf(self, name, args, path, context, line):
        if name == 'include' and len(args) == 1:
            self.include(args[0], context)
        elif name == 'listen' and context in ('server', 'stream_server') and args:
            ports = _listen_port(args[0])
            if ports and any(ports[0] - 1 <= p <= ports[1] + 1 for p in self.protected_ports):
                raise ValueError('listener at or adjacent to a CDS port')
        elif name == 'server' and context in ('http_upstream', 'stream_upstream') and args:
            if any(option.startswith('service=') for option in args[1:]):
                raise ValueError('unclassifiable SRV upstream port')
            port = _backend_port(args[0], (), default=80 if context == 'http_upstream' else None)
            if port in self.protected_ports:
                raise ValueError(f'upstream targets CDS port {port}')
            if port is None and not _UNIX.fullmatch(args[0]):
                raise ValueError('missing stream upstream port')
        elif ((name in _PROXIES and context in ('server', 'location')) or
              (name == 'proxy_pass' and context == 'stream_server')):
            self.proxy(name, args, path, context, line)
        elif name == 'load_module' and context == 'main' and len(args) == 1:
            if not _MODULE.fullmatch(args[0]):
                raise ValueError('unclassifiable nginx module')
        elif context == 'types' and '/' in name and args and all(_WORD.fullmatch(a) for a in args):
            return
        elif (name == 'error_log' and
              context in ('main', 'http', 'server', 'stream', 'stream_server')):
            if not args or ':server=' in args[0] or args[0].startswith('syslog:'):
                raise ValueError('unclassifiable error_log destination')
        elif args and self.harmless(name, context):
            if name == 'access_log' and args[0].startswith('syslog:'):
                raise ValueError('unclassifiable access_log destination')
        elif not args and context.endswith('_upstream') and name in ('least_conn', 'ip_hash'):
            return
        else:
            raise ValueError(f'unclassifiable {name} directive in {context}')

    def harmless(self, name, context):
        return (name in _LEAF.get(context, ()) or
                context in ('server', 'location') and name in _LEAF['web'] or
                context == 'stream_server' and name in _LEAF['stream'] or
                context.endswith('_upstream') and name in _LEAF['upstream'])

    def proxy(self, name, args, path, context, line):
        if len(args) != 1:
            raise ValueError(f'unexpected arguments to {name}')
        stream = context == 'stream_server'
        protocols = () if stream else _PROXIES[name]
        port = _backend_port(args[0], protocols, default=80 if protocols else None,
                             path=bool(protocols))
        if port in self.protected_ports:
            raise ValueError(f'{name} targets CDS port {port}')
        if port is None and not _UNIX.fullmatch(args[0]):
            namespace = 'stream' if stream else 'http'
            self.references.append((path, line, namespace, args[0].lower()))

    def verify_dump(self, dump):
        sections = list(_HEADER.finditer(dump))
        if (not sections or sections[0].start() or
                Path(sections[0][1].decode()) != self.main):
            raise InventoryError(f'{self.main}: unexpected nginx -T main configuration')
        seen = set()
        for index, header in enumerate(sections):
            path = Path(header[1].decode())
            end = sections[index + 1].start() if index + 1 < len(sections) else len(dump)
            if path not in self.files or path in seen:
                self.issue(path, 'unaccounted configuration from nginx -T')
            elif dump[header.end():end] != self.files[path] + b'\n':
                self.issue(path, 'configuration differs from nginx -T')
            seen.add(path)
        for path in self.files.keys() - seen:
            self.issue(path, 'configuration missing from nginx -T')

    def scan(self, dump):
        try:
            self.inspect_file(self.main, 'main')
        except RecursionError:
            self.issue(self.main, 'configuration nesting is too deep')
        if self.site_uses != 1:
            self.issue(self.site, 'expected exactly one include of the installer site')
        for path, line, namespace, name in self.references:
            if name not in self.upstreams[namespace]:
                self.issue(path, f'line {line}: unresolved {namespace} upstream')
        if dump is not None:
            self.verify_dump(dump)
        if self.problems:
            raise InventoryError('\n'.join(dict.fromkeys(self.problems)))
        return self.files
