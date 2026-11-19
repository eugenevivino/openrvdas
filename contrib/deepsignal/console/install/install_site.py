"""Manage the dedicated DeepSignal Console nginx site."""

import argparse
import difflib
import fcntl
import os
from pathlib import Path
import re
import runpy
import shutil
import stat
import subprocess
import sys
import tempfile
import time


INSTALL = Path(__file__).resolve().parent
SECURITY = INSTALL.parents[1] / 'security'
RENDERER = runpy.run_path(str(SECURITY / 'nginx/render_site.py'))
INVENTORY = runpy.run_path(str(INSTALL / 'nginx_inventory.py'))
Inventory = INVENTORY['Inventory']
SITE_NAME = RENDERER['SITE_NAME']


def command(*args, capture=False):
    return subprocess.run(args, capture_output=capture, check=True, timeout=15)


def snapshot(main, path, contents, ports, nginx):
    inventory = Inventory(main, path, contents, ports)
    if not nginx:
        return inventory.scan(None)
    result = subprocess.run(nginx_command(nginx, '-T'), capture_output=True, timeout=15)
    if result.returncode or b'conflicting server name' in result.stderr:
        if result.stderr:
            sys.stderr.buffer.write(result.stderr)
        # Still list identifiable inventory failures if nginx could not dump.
        inventory.scan(None)
        raise ValueError(f'{main}: nginx -T could not validate the configuration')
    return inventory.scan(result.stdout)


def nginx_command(nginx, action):
    return (nginx[0], action, *nginx[1:])


def master_pid():
    pid = command('systemctl', 'show', '--property=MainPID', '--value', 'nginx',
                  capture=True).stdout.strip()
    if not pid.isdigit() or int(pid) <= 1:
        raise ValueError('Cannot identify the running nginx master.')
    return pid.decode()


def service_configuration(main):
    master = master_pid()
    output = command('ps', '-o', 'args=', '-p', master, '-ww', capture=True).stdout
    title = output.decode().strip()
    prefix = 'nginx: master process '
    if not title.startswith(prefix):
        raise ValueError('Cannot identify the running nginx master command.')
    invocation = title.removeprefix(prefix)
    # nginx flattens argv when it sets its process title. The stock service
    # globals below are the only multiword argument the installer can verify.
    invocation, separator, globals_ = invocation.partition(' -g ')
    if separator and globals_ not in ('daemon on;', 'daemon off;', 'master_process on;',
                                      'daemon on; master_process on;',
                                      'daemon off; master_process on;'):
        raise ValueError('Unclassifiable nginx master global directives.')
    binary, *options = invocation.split()
    if not Path(binary).is_absolute() or len(options) % 2:
        raise ValueError('Unclassifiable nginx master command.')
    parsed = {}
    for flag, value in zip(options[::2], options[1::2]):
        if flag not in ('-p', '-c') or flag in parsed or not Path(value).is_absolute():
            raise ValueError('Unclassifiable nginx master arguments.')
        parsed[flag] = value
    if '-c' in parsed and Path(parsed['-c']) != main:
        raise ValueError(f'{main}: nginx master uses {parsed["-c"]} instead.')
    # With no -c, the main path printed by this binary must match main.
    if separator:
        options.extend(('-g', globals_))
    return master, (binary, *options)


def worker_generation(master):
    if master_pid() != master:
        raise ValueError('The nginx master changed during installation.')
    output = command('ps', '-o', 'pid=,args=', '--ppid', master, capture=True).stdout
    return {int(pid) for pid in re.findall(rb'^[ \t]*(\d+) nginx: worker process[ \t]*$',
                                           output, re.MULTILINE)}


def confirm_reload(master, previous):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        current = worker_generation(master)
        if current and not current & previous:
            command('systemctl', 'is-active', '--quiet', 'nginx')
            return
    raise ValueError('Could not confirm a new nginx worker generation after reload.')


def run_checker(args, path):
    cmd = [sys.executable, '-I', '-B', str(SECURITY / 'check_cds.py'),
           '--nginx-site', str(path), '--openrvdas-root', args.openrvdas_root, '--local-nginx']
    for origin in args.origin:
        cmd.extend(('--origin', origin))
    if args.ssl_certificate:
        cmd.extend(('--ssl-certificate', args.ssl_certificate,
                    '--ssl-certificate-key', args.ssl_certificate_key))
    for port in args.udp_port:
        cmd.extend(('--udp-port', str(port)))
    if args.udp_interface:
        cmd.extend(('--udp-interface', args.udp_interface))
    environment = os.environ | {'NO_PROXY': '*', 'no_proxy': '*'}
    subprocess.run(cmd, env=environment, cwd='/', check=True, timeout=45)


def set_site(path, contents, previous_mode=None):
    if contents is None:
        path.unlink()
        return
    # Hidden staging directories cannot match any accepted include glob.
    with tempfile.TemporaryDirectory(prefix='.deepsignal-', dir=path.parent) as staging:
        proposed = Path(staging) / SITE_NAME
        proposed.write_bytes(contents)
        proposed.chmod(0o644 if previous_mode is None else previous_mode)
        os.replace(proposed, path)


def apply(args, main, path, files, desired, rendered, ports, nginx, master):
    if not nginx:
        raise ValueError('nginx is required to test and reload the site.')
    original = files.get(path)
    previous_mode = stat.S_IMODE(path.stat().st_mode) if original is not None else None
    if not worker_generation(master):
        raise ValueError('Cannot identify the active nginx workers.')
    if files != snapshot(main, path, rendered, ports, nginx):
        raise ValueError('The effective nginx configuration changed before installation.')
    changed = desired != original
    reload_attempted = False
    try:
        if changed:
            set_site(path, desired, previous_mode)
        updated = dict(files)
        if desired is None:
            updated.pop(path, None)
        else:
            updated[path] = desired
        if updated != snapshot(main, path, rendered, ports, nginx):
            raise ValueError('The effective nginx configuration changed while installing.')
        command(*nginx_command(nginx, '-t'))
        previous = worker_generation(master)
        if not previous:
            raise ValueError('Cannot identify the active nginx workers.')
        reload_attempted = True
        command('systemctl', 'reload', 'nginx')
        confirm_reload(master, previous)
        if updated != snapshot(main, path, rendered, ports, nginx):
            raise ValueError('The effective nginx configuration changed during reload.')
        if not args.uninstall:
            run_checker(args, path)
    except (OSError, ValueError, subprocess.SubprocessError):
        if changed and not path.is_symlink() and (
                path.read_bytes() if path.exists() else None) == desired:
            set_site(path, original, previous_mode)
            print('The original nginx site was restored.', file=sys.stderr)
            if reload_attempted:
                try:
                    if files != snapshot(main, path, rendered, ports, nginx):
                        raise ValueError('The effective configuration changed.')
                    previous = worker_generation(master)
                    if not previous:
                        raise ValueError('Cannot identify the active nginx workers.')
                    command('systemctl', 'reload', 'nginx')
                    confirm_reload(master, previous)
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    print(f'Could not confirm the nginx rollback reload: {exc}', file=sys.stderr)
        raise
    print('nginx reload confirmed.')


def site_path(args, main):
    if args.nginx_site is not None:
        path = Path(os.path.abspath(args.nginx_site))
        if path.name != SITE_NAME:
            raise ValueError(f'Use a dedicated {SITE_NAME} path for --nginx-site.')
        return path
    for dirname in ('sites-enabled', 'conf.d'):
        parent = main.parent / dirname
        if parent.is_dir():
            return parent / SITE_NAME
    raise ValueError(f'No nginx configuration found in {main.parent / "sites-enabled"} or '
                     f'{main.parent / "conf.d"}. Use --nginx-site.')


def install(args, site, uid):
    rendered = site.contents
    if args.render:
        sys.stdout.buffer.write(rendered)
        return
    if not (args.dry_run or args.check) and uid != 0:
        raise ValueError('Run this installer as root, or use --dry-run to preview the change.')
    main = Path(os.path.abspath(args.nginx_main))
    path = site_path(args, main)
    if path == main:
        raise ValueError('The installer site must differ from the nginx main configuration.')
    if path.is_symlink():
        raise ValueError(f'{path}: installer site must be a regular file, with no symlink.')
    binary = shutil.which('nginx')
    nginx = (binary, '-c', str(main)) if binary else None
    master = None
    if binary and not args.dry_run:
        master, nginx = service_configuration(main)
    ports = {*RENDERER['CDS_PORTS'], *args.udp_port}
    if any(abs(site.port - port) <= 1 for port in args.udp_port):
        raise ValueError('The console listener is too close to a CDS UDP port.')
    # Serialize installs, including idempotent reloads, without adding a lock file.
    fd = os.open(main.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH if args.dry_run or args.check else fcntl.LOCK_EX)
        files = snapshot(main, path, rendered, ports, nginx)
        if args.check:
            run_checker(args, path)
        else:
            desired = None if args.uninstall else rendered
            if args.dry_run:
                diff = difflib.diff_bytes(difflib.unified_diff,
                                          (files.get(path) or b'').splitlines(keepends=True),
                                          (desired or b'').splitlines(keepends=True),
                                          str(path).encode(), str(path).encode() + b' (proposed)')
                sys.stdout.buffer.writelines(diff)
            else:
                apply(args, main, path, files, desired, rendered, ports, nginx, master)
    finally:
        os.close(fd)


def main():
    uid = int(sys.argv[1])
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    RENDERER['add_site_arguments'](parser)
    parser.add_argument('--nginx-conf', dest='nginx_site', type=Path,
                        help=argparse.SUPPRESS)
    parser.add_argument('--nginx-main', default='/etc/nginx/nginx.conf')
    parser.add_argument('--udp-port', type=int, action='append', default=[])
    parser.add_argument('--udp-interface')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--render', action='store_true')
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--uninstall', action='store_true')
    args = parser.parse_args(sys.argv[2:])
    if bool(args.udp_port) != bool(args.udp_interface):
        parser.error('supply --udp-port and --udp-interface together')
    if any(not 1 <= port <= 65535 for port in args.udp_port):
        parser.error('--udp-port must be between 1 and 65535')
    try:
        site = RENDERER['render_site'](args)
        install(args, site, uid)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'Console nginx installer: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
