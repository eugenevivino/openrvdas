#!/bin/sh
set -eu

OPENRVDAS_ROOT=/opt/openrvdas
NGINX_CONF=
SERVER_NAME=
DRY_RUN=false
UNINSTALL=false
CHECK=false
RELOAD=true
UDP_PORT=
UDP_INTERFACE=

usage() {
    echo "Usage: $0 [--openrvdas-root PATH] [--nginx-conf PATH] [--server-name NAME] [--dry-run] [--uninstall | --check] [--no-reload]"
    echo "Use --server-name for a configuration with multiple server blocks. Use --check to run the #197 relay self-test."
    echo "For a cache that uses --udp, supply --udp-port PORT and --udp-interface ADDRESS."
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --openrvdas-root) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; OPENRVDAS_ROOT=$2; shift 2 ;;
        --nginx-conf) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; NGINX_CONF=$2; shift 2 ;;
        --server-name) [ "$#" -ge 2 ] && [ -n "$2" ] || { usage >&2; exit 2; }; SERVER_NAME=$2; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --uninstall) UNINSTALL=true; shift ;;
        --check) CHECK=true; shift ;;
        --udp-port) [ "$#" -ge 2 ] && [ -n "$2" ] || { usage >&2; exit 2; }; UDP_PORT=$2; shift 2 ;;
        --udp-interface) [ "$#" -ge 2 ] && [ -n "$2" ] || { usage >&2; exit 2; }; UDP_INTERFACE=$2; shift 2 ;;
        --no-reload) RELOAD=false; shift ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if $CHECK && $UNINSTALL; then usage >&2; exit 2; fi
if { [ -n "$UDP_PORT" ] && [ -z "$UDP_INTERFACE" ]; } ||
   { [ -z "$UDP_PORT" ] && [ -n "$UDP_INTERFACE" ]; }; then
    echo "Supply both --udp-port and --udp-interface to check the CDS UDP feed." >&2
    exit 2
fi
if ! $UNINSTALL; then
    case "$OPENRVDAS_ROOT" in
        /*) ;;
        *) echo "Use an absolute path for --openrvdas-root." >&2; exit 2 ;;
    esac
    case "$OPENRVDAS_ROOT" in
        *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./-]*)
            echo "Use only letters, digits, slashes, underscores, dots and hyphens in --openrvdas-root." >&2
            exit 2 ;;
    esac
fi

if [ -z "$NGINX_CONF" ]; then
    for candidate in /etc/nginx/sites-enabled/openrvdas.conf /etc/nginx/conf.d/openrvdas.conf; do
        if [ -f "$candidate" ]; then NGINX_CONF=$candidate; break; fi
    done
    if [ -z "$NGINX_CONF" ]; then
        echo "No nginx configuration found. Checked /etc/nginx/sites-enabled/openrvdas.conf and /etc/nginx/conf.d/openrvdas.conf." >&2
        exit 1
    fi
fi

if [ ! -f "$NGINX_CONF" ]; then
    echo "Nginx configuration not found: $NGINX_CONF" >&2
    exit 1
fi
case "$NGINX_CONF" in /*) ;; *) NGINX_CONF=$PWD/$NGINX_CONF ;; esac

installer_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
nginx_helper=$installer_dir/nginx-site.awk

trusted_path() (
    path=$1
    [ -f "$path" ] || return 1
    while :; do
        [ ! -L "$path" ] || return 1
        metadata=$(stat -c '%u %a' -- "$path" 2>/dev/null ||
                   stat -f '%u %Lp' -- "$path" 2>/dev/null) || return 1
        read -r owner mode <<EOF
$metadata
EOF
        case "$mode" in ''|*[!0-7]*) return 1 ;; esac
        [ "$owner" = 0 ] && [ "$((0$mode & 022))" -eq 0 ] || return 1
        [ "$path" != / ] || return 0
        path=${path%/*}
        path=${path:-/}
    done
)

uid=$(id -u)
if [ "$uid" -ne 0 ] && ! $UNINSTALL && ! $CHECK && ! $DRY_RUN; then
    echo "Run this installer as root, or use --dry-run to preview the change." >&2
    exit 1
fi
if [ "$uid" -eq 0 ] || $CHECK; then
    for program in "$installer_dir/${0##*/}" "$nginx_helper"; do
        if ! trusted_path "$program"; then
            echo "$program must be in a root-owned release with no symlinks or group/world-writable path components." >&2
            exit 1
        fi
    done
fi

temp_parent=${TMPDIR:-/tmp}
# Root's snapshot must not sit in a caller-selected writable directory.
if [ "$uid" -eq 0 ]; then temp_parent=/tmp; fi
temp_dir=$(mktemp -d "$temp_parent/deepsignal-console.XXXXXX")
trap 'rm -rf "$temp_dir"' EXIT
trap 'exit 1' HUP INT TERM
original=$temp_dir/original
tmp=$temp_dir/proposed
cp "$NGINX_CONF" "$original"

if region=$(LC_ALL=C CONSOLE_SERVER_NAME="$SERVER_NAME" awk -v udp_port="$UDP_PORT" -f "$nginx_helper" "$original"); then
    read -r start end relay server_start probe_name probe_port probe_scheme probe_address <<EOF
$region
EOF
else
    case "$?" in
        4) echo "Select exactly one nginx server in $NGINX_CONF with --server-name NAME if needed." >&2 ;;
        5) echo "The selected server has an incomplete or duplicate DeepSignal Console marker block." >&2 ;;
        *) echo "Could not read nginx server blocks in $NGINX_CONF." >&2 ;;
    esac
    exit 1
fi

relay_warning() {
    echo "Check that both Django and React nginx templates send /cds-ws to the #197 read-only relay." >&2
    echo "Bind the cache to loopback and bind any optional CDS UDP feed (--udp) to a named interface instead of all interfaces (INADDR_ANY)." >&2
}

nginx_dump=$temp_dir/nginx-dump
dump_nginx() {
    # The dump may contain credentials. Retain it only in the private directory.
    nginx -T > "$1"
}

check_relay() (
    release_root=$(CDPATH='' cd -- "$installer_dir/../../../.." && pwd -P) || return 1
    checker=$release_root/contrib/deepsignal/security/check_cds.py
    if [ ! -f "$checker" ]; then
        echo "The #197 read-only relay checker is missing at $checker. Stage a release that includes #197." >&2
        return 1
    fi
    if ! trusted_path "$checker"; then
        echo "The #197 read-only relay checker at $checker must be root-owned, with no symlinks or group/world-writable path components." >&2
        return 1
    fi
    # The first file dumped by nginx is the main configuration used by nginx -t.
    if ! dump_nginx "$nginx_dump" || ! IFS= read -r header < "$nginx_dump"; then
        echo "Could not read the effective nginx configuration with nginx -T." >&2
        return 1
    fi
    case "$header" in
        '# configuration file /'*:) nginx_main=${header#\# configuration file }; nginx_main=${nginx_main%:} ;;
        *) echo "Could not identify the main nginx configuration from nginx -T." >&2; return 1 ;;
    esac
    snapshot=$original
    if ! $CHECK; then snapshot=$tmp; fi
    gateway_url=$probe_scheme://$probe_name:$probe_port/cds-ws
    set -- --gateway-url "$gateway_url" --nginx-config "$nginx_main" \
        --nginx-react-config "$nginx_main" --nginx-dump "$nginx_dump" --nginx-site "$NGINX_CONF" \
        --nginx-site-snapshot "$snapshot" --nginx-server-offset "$server_start" \
        --console-source "${OPENRVDAS_ROOT%/}/contrib/deepsignal/console"
    if ! $CHECK; then
        set -- "$@" --allow-missing-relay
        if $DRY_RUN; then set -- "$@" --nginx-only; fi
    fi
    if [ -n "$UDP_PORT" ]; then
        set -- "$@" --udp-port "$UDP_PORT" --udp-interface "$UDP_INTERFACE"
    else
        echo "If the cache uses --udp, supply --udp-port and --udp-interface to check its UDP bind." >&2
    fi
    cd / || return 1
    export NO_PROXY='*' no_proxy='*'
    # Pin the nginx handshakes to the selected listen address.
    python3 -I -B - "$checker" "$gateway_url" "$probe_name" "$probe_address" "$@" <<'PY'
import ipaddress
import re
import runpy
import sys
from urllib.parse import urlsplit

checker, gateway_url, name, address = sys.argv[1:5]
sys.argv = [checker, *sys.argv[5:]]
program = runpy.run_path(checker)
websockets = program.get('websockets')
if websockets is not None:
    connect = websockets.connect

    def connect_with_origin(uri, **kwargs):
        if uri == gateway_url:
            if not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?', name):
                sys.exit('Set a concrete server_name on the selected nginx server to check /cds-ws.')
            try:
                kwargs['host'] = str(ipaddress.ip_address(address.strip('[]')))
            except ValueError:
                sys.exit('Use an IP address or wildcard in the selected nginx listen directive.')
            endpoint = urlsplit(gateway_url)
            scheme, default_port = ('https', 443) if endpoint.scheme == 'wss' else ('http', 80)
            origin_host = endpoint.hostname if endpoint.port == default_port else endpoint.netloc
            kwargs.setdefault('origin', f'{scheme}://{origin_host}')
        return connect(uri, **kwargs)

    websockets.connect = connect_with_origin
sys.exit(program['main']())
PY
)

render_site() {
    dd if="$original" bs=1 count="$start" 2>/dev/null
    if ! $UNINSTALL; then
        cat <<EOF
    # BEGIN deepsignal-console
    location /console/ {
        alias ${OPENRVDAS_ROOT%/}/contrib/deepsignal/console/dist/;
        try_files \$uri \$uri/ /console/index.html;
    }
EOF
        if [ "$1" = missing ]; then
            echo '    location = /cds-ws { return 503; }'
        fi
        echo '    # END deepsignal-console'
    fi
    tail -c "+$((end + 1))" "$original"
} > "$tmp"

if ! $CHECK; then render_site "$relay"; fi
if ! $UNINSTALL; then
    if [ "$relay" = unsafe ]; then
        echo "The nginx site must use the #197 read-only relay before installing the console." >&2
        relay_warning
        exit 1
    fi
    gate_output=$temp_dir/gate-output
    if check_relay > "$gate_output"; then
        cat "$gate_output"
    else
        cat "$gate_output"
        relay_warning
        exit 1
    fi
    if $CHECK; then exit 0; fi
    if grep -Fxq 'PASS: selected nginx server has no /cds-ws relay.' "$gate_output"; then
        relay_warning
        echo "Live data will stay unavailable until the read-only relay is configured." >&2
        render_site missing
    fi
fi

if ! cmp -s "$NGINX_CONF" "$original"; then
    echo "The nginx configuration changed while the installer was running. Please rerun the command." >&2
    exit 1
fi

if cmp -s "$NGINX_CONF" "$tmp"; then
    if $UNINSTALL; then
        echo "DeepSignal Console was already uninstalled; no changes were needed."
    else
        echo "DeepSignal Console was already installed; no changes were needed."
        echo "Open http://<server>/console/"
    fi
    exit 0
fi

if $DRY_RUN; then
    echo "Dry run only; this is the change that would be made to $NGINX_CONF:"
    diff -u "$NGINX_CONF" "$tmp" || true
    exit 0
fi

if [ "$uid" -ne 0 ]; then
    echo "Run this installer as root, or use --dry-run to preview the change." >&2
    exit 1
fi

backup_suffix=.deepsignal-backup-$(date +%Y%m%d%H%M%S).XXXXXX
if $UNINSTALL && ! dump_nginx "$nginx_dump"; then exit 1; fi
backup=$(mktemp "$NGINX_CONF$backup_suffix")
cp -p "$NGINX_CONF" "$backup"
# A broad include such as sites-enabled/* can pick up the new backup.
if ! dump_nginx "$temp_dir/nginx-before-write" 2>/dev/null ||
   ! cmp -s "$nginx_dump" "$temp_dir/nginx-before-write"; then
    hidden_backup=$(mktemp "${NGINX_CONF%/*}/.${NGINX_CONF##*/}$backup_suffix")
    mv "$backup" "$hidden_backup"
    backup=$hidden_backup
    if ! dump_nginx "$temp_dir/nginx-before-write" ||
       ! cmp -s "$nginx_dump" "$temp_dir/nginx-before-write"; then
        rm -f "$backup"
        echo "The effective nginx configuration changed while preparing the backup." >&2
        exit 1
    fi
fi
echo "Saved a backup at $backup."

if ! cat "$tmp" > "$NGINX_CONF" || ! nginx -t; then
    cp -p "$backup" "$NGINX_CONF"
    echo "Nginx rejected the change, so the original configuration was restored from $backup."
    exit 1
fi

if $RELOAD; then
    systemctl reload nginx
    echo "Nginx was reloaded."
else
    echo "Nginx was not reloaded. Run: systemctl reload nginx"
fi

if $UNINSTALL; then
    echo "DeepSignal Console was removed from nginx."
else
    echo "DeepSignal Console was added to nginx."
    echo "Open http://<server>/console/"
fi
