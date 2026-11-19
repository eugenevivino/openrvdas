#!/bin/sh
set -eu

installer_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
console_dir=${installer_dir%/*}
security_dir=${console_dir%/*}/security

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
require_trusted=false
if [ "$uid" -eq 0 ]; then require_trusted=true; fi
for arg do
    if [ "$arg" = --check ]; then require_trusted=true; fi
done
if $require_trusted; then
    for file in "$installer_dir/${0##*/}" "$installer_dir/install_site.py" \
                "$installer_dir/nginx_inventory.py" "$security_dir/check_cds.py" \
                "$security_dir/probe_cds.py" \
                "$security_dir/nginx/render_site.py" \
                "$security_dir/nginx/deepsignal-console.conf.template"; do
        if ! trusted_path "$file"; then
            echo "$file must be in a root-owned release with no symlinks or group/world-writable path components." >&2
            exit 1
        fi
    done
fi

python=${DEEPSIGNAL_PYTHON-/opt/openrvdas/venv/bin/python}
if [ "${python#/}" = "$python" ] || [ ! -f "$python" ] || [ ! -x "$python" ]; then
    echo "OpenRVDAS Python missing or not executable at '$python'. Set DEEPSIGNAL_PYTHON to its absolute path." >&2
    exit 1
fi
if ! "$python" -I -B -c 'import websockets' >/dev/null 2>&1; then
    echo "OpenRVDAS Python at '$python' cannot import websockets." >&2
    exit 1
fi

exec "$python" -I -B "$installer_dir/install_site.py" "$uid" "$@"
