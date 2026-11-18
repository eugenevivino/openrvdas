#!/bin/sh
set -eu

OPENRVDAS_ROOT=/opt/openrvdas
NGINX_CONF=
DRY_RUN=false
UNINSTALL=false
RELOAD=true

usage() {
    echo "Usage: $0 [--openrvdas-root PATH] [--nginx-conf PATH] [--dry-run] [--uninstall] [--no-reload]"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --openrvdas-root) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; OPENRVDAS_ROOT=$2; shift 2 ;;
        --nginx-conf) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; NGINX_CONF=$2; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --uninstall) UNINSTALL=true; shift ;;
        --no-reload) RELOAD=false; shift ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

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

tmp=$(mktemp "${TMPDIR:-/tmp}/deepsignal-console.XXXXXX")
trap 'rm -f "$tmp"' EXIT HUP INT TERM

if $UNINSTALL; then
    awk '
        /^([[:space:]]*)# BEGIN deepsignal-console[[:space:]]*$/ { marked=1; found=1; next }
        /^([[:space:]]*)# END deepsignal-console[[:space:]]*$/ && marked { marked=0; next }
        !marked { print }
        END { if (marked) exit 3 }
    ' "$NGINX_CONF" > "$tmp" || {
        echo "The DeepSignal Console marker block is incomplete; no changes were made." >&2
        exit 1
    }
else
    if grep -q '^[[:space:]]*# BEGIN deepsignal-console[[:space:]]*$' "$NGINX_CONF"; then
        cp "$NGINX_CONF" "$tmp"
    else
        awk -v root="$OPENRVDAS_ROOT" '
            function braces(line,    text, opens, closes) {
                text=line; opens=gsub(/{/, "{", text)
                text=line; closes=gsub(/}/, "}", text)
                return opens-closes
            }
            {
                delta=braces($0)
                if (!inside && $0 ~ /^[[:space:]]*server[[:space:]]*\{/) {
                    inside=1; depth=delta; print; next
                }
                if (inside && depth+delta == 0) {
                    print "    # BEGIN deepsignal-console"
                    print "    location /console/ {"
                    print "        alias " root "/contrib/deepsignal/console/dist/;"
                    print "        try_files $uri $uri/ /console/index.html;"
                    print "    }"
                    print "    # END deepsignal-console"
                    inserted=1; inside=0
                }
                print
                if (inside) depth+=delta
            }
            END { if (!inserted) exit 4 }
        ' "$NGINX_CONF" > "$tmp" || {
            echo "No server { block found in $NGINX_CONF; no changes were made." >&2
            exit 1
        }
    fi
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
