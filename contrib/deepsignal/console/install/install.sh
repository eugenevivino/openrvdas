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
temp_dir=$(mktemp -d "${TMPDIR:-/tmp}/deepsignal-console.XXXXXX")
trap 'rm -rf "$temp_dir"' EXIT
trap 'exit 1' HUP INT TERM
original=$temp_dir/original
tmp=$temp_dir/proposed
cp "$NGINX_CONF" "$original"

if region=$(LC_ALL=C CONSOLE_SERVER_NAME="$SERVER_NAME" awk -f "$installer_dir/nginx-site.awk" "$original"); then
    read -r start end relay <<EOF
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
    if [ ! -f "$OPENRVDAS_ROOT/contrib/deepsignal/security/check_cds.py" ]; then
        echo "The #197 read-only relay checker is missing." >&2
        return 1
    fi
    cd "$OPENRVDAS_ROOT" || return 1
    if [ -n "$UDP_PORT" ]; then
        set -- --udp-port "$UDP_PORT" --udp-interface "$UDP_INTERFACE"
    else
        echo "If the cache uses --udp, supply --udp-port and --udp-interface to check its UDP bind." >&2
    fi
    python3 -B -E -s -m contrib.deepsignal.security.check_cds "$@"
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

if [ "$(id -u)" -ne 0 ]; then
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
