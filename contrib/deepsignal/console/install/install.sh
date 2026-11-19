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
    read -r start end relay server_start server_size probe_name probe_port probe_scheme probe_address <<EOF
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
    case "$probe_name" in
        ''|[!a-zA-Z0-9]*|*[!a-zA-Z0-9.-]*|*[!a-zA-Z0-9])
            echo "Set a concrete server_name on the selected nginx server to check /cds-ws." >&2
            return 1 ;;
    esac
    selected_site=$temp_dir/selected-site
    {
        printf 'server '
        dd if="$original" bs=1 skip="$server_start" count="$server_size" 2>/dev/null
    } > "$selected_site" || return 1
    gateway_url=$probe_scheme://$probe_name:$probe_port/cds-ws
    set -- --gateway-url "$gateway_url" --nginx-config "$selected_site" \
        --nginx-react-config "$selected_site" \
        --console-source "${OPENRVDAS_ROOT%/}/contrib/deepsignal/console"
    if [ -n "$UDP_PORT" ]; then
        set -- "$@" --udp-port "$UDP_PORT" --udp-interface "$UDP_INTERFACE"
    else
        echo "If the cache uses --udp, supply --udp-port and --udp-interface to check its UDP bind." >&2
    fi
    cd / || return 1
    export NO_PROXY='*' no_proxy='*'
    # Give the nginx handshake the required browser Origin and pin it to the listen address.
    python3 -I -B - "$checker" "$gateway_url" "$probe_address" "$@" <<'PY'
import ipaddress
import runpy
import sys
from urllib.parse import urlsplit

checker, gateway_url, address = sys.argv[1:4]
try:
    address = str(ipaddress.ip_address(address.strip('[]')))
except ValueError:
    sys.exit('Use an IP address or wildcard in the selected nginx listen directive.')
sys.argv = [checker, *sys.argv[4:]]
program = runpy.run_path(checker)
websockets = program.get('websockets')
if websockets is not None:
    connect = websockets.connect
    endpoint = urlsplit(gateway_url)
    scheme, default_port = ('https', 443) if endpoint.scheme == 'wss' else ('http', 80)
    origin_host = endpoint.hostname if endpoint.port == default_port else endpoint.netloc
    origin = f'{scheme}://{origin_host}'

    def connect_with_origin(uri, **kwargs):
        if uri == gateway_url:
            kwargs.update(host=address, origin=origin)
        return connect(uri, **kwargs)

    websockets.connect = connect_with_origin
sys.exit(program['main']())
PY
)

if ! $UNINSTALL; then
    if [ "$relay" = unsafe ]; then
        echo "The selected server's /cds-ws must point to the #197 read-only relay before installing the console." >&2
        relay_warning
        exit 1
    elif [ "$relay" = missing ]; then
        relay_warning
        if $CHECK; then exit 1; fi
        echo "Live data will stay unavailable until the read-only relay is configured." >&2
    elif $DRY_RUN && ! $CHECK; then
        relay_warning
    elif ! check_relay; then
        relay_warning
        exit 1
    fi
    if $CHECK; then exit 0; fi
fi

{
    dd if="$original" bs=1 count="$start" 2>/dev/null
    if ! $UNINSTALL; then
        cat <<EOF
    # BEGIN deepsignal-console
    location /console/ {
        alias ${OPENRVDAS_ROOT%/}/contrib/deepsignal/console/dist/;
        try_files \$uri \$uri/ /console/index.html;
    }
EOF
        if [ "$relay" = missing ]; then
            echo '    location = /cds-ws { return 503; }'
        fi
        echo '    # END deepsignal-console'
    fi
    tail -c "+$((end + 1))" "$original"
} > "$tmp"

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

backup="$NGINX_CONF.deepsignal-backup-$(date +%Y%m%d%H%M%S)"
cp -p "$NGINX_CONF" "$backup"
cat "$tmp" > "$NGINX_CONF"
echo "Saved a backup at $backup."

if ! nginx -t; then
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
