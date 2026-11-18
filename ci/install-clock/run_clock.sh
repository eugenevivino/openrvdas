#!/usr/bin/env bash
set -uo pipefail

readonly ROOT=${GITHUB_WORKSPACE:-$(git rev-parse --show-toplevel)}
readonly OUT="$ROOT/install-clock.json"
readonly LOG="$ROOT/install-clock.log"
readonly ANSWERS="$ROOT/ci/install-clock/answers.txt"
readonly PYTHON_BIN=${PYTHON_BIN:-python3}
readonly T_START=${T_START:-$(date +%s)}
readonly BASE_SHA=${BASE_SHA:-$(git rev-parse HEAD^)}
readonly RUNNER_IMAGE=${RUNNER_IMAGE:-${ImageOS:-unknown}-${ImageVersion:-unknown}}

mem_used_kb() { awk '/MemTotal:/{t=$2}/MemAvailable:/{a=$2}END{print t-a}' /proc/meminfo; }
disk_used_kb() { df -Pk "$ROOT" | awk 'NR==2 {print $3}'; }

mem_before=$(mem_used_kb)
disk_before=$(disk_used_kb)
t_installed=0
t_first_data=0
prompts_shown=0
install_status=125
prompt_status=125
load_status=125
mode_status=125
first_data_status=125
web_status=125

set +e
# read -p suppresses prompts when stdin is not a terminal.  util-linux script
# supplies the pseudo-terminal needed to capture the exact prompts while still
# feeding the checked-in answers on stdin.
script --quiet --return --command \
    "bash '$ROOT/utils/install_openrvdas.sh'" /dev/null \
    < "$ANSWERS" 2>&1 | tee "$LOG"
install_status=${PIPESTATUS[0]}
if (( install_status == 0 )); then
    t_installed=$(date +%s)
fi

prompts_shown=$($PYTHON_BIN "$ROOT/ci/install-clock/parse_clock.py" "$LOG")
answer_count=$(wc -l < "$ANSWERS")
if (( prompts_shown == answer_count )); then
    prompt_status=0
else
    prompt_status=1
    echo "ERROR: installer showed $prompts_shown prompts, answers file has $answer_count lines" >&2
fi

if (( install_status == 0 && prompt_status == 0 )); then
    sudo -u rvdas "$ROOT/venv/bin/python" "$ROOT/server/lmcmd.py" \
        load_configuration "$ROOT/test/NBP1406/NBP1406_cruise.yaml"
    load_status=$?
    if (( load_status == 0 )); then
        sudo -u rvdas "$ROOT/venv/bin/python" "$ROOT/server/lmcmd.py" \
            set_active_mode no_write
        mode_status=$?
    fi

    deadline=$(( $(date +%s) + 300 ))
    while (( load_status == 0 && mode_status == 0 && $(date +%s) <= deadline )); do
        if T_INSTALLED="$t_installed" $PYTHON_BIN - <<'PY'
import json
import os
import urllib.parse
import urllib.request

threshold = float(os.environ["T_INSTALLED"])
with urllib.request.urlopen("http://localhost:8766/fields", timeout=5) as response:
    fields = json.load(response)["fields"]
if not fields:
    raise SystemExit(1)
quoted = ",".join(urllib.parse.quote(field, safe="") for field in fields)
with urllib.request.urlopen("http://localhost:8766/latest/" + quoted,
                            timeout=5) as response:
    latest = json.load(response)
raise SystemExit(0 if any(value and value["timestamp"] > threshold
                          for value in latest.values()) else 1)
PY
        then
            first_data_status=0
            t_first_data=$(date +%s)
            break
        fi
        sleep 2
    done
    if (( first_data_status != 0 )); then
        first_data_status=1
    fi
    curl --fail --silent --show-error --output /dev/null http://localhost/
    web_status=$?
fi

mem_after=$(mem_used_kb)
disk_after=$(disk_used_kb)
peak_mem=$(( mem_before > mem_after ? mem_before : mem_after ))
peak_disk=$(( disk_before > disk_after ? disk_before : disk_after ))

RUNNER_IMAGE="$RUNNER_IMAGE" BASE_SHA="$BASE_SHA" PROMPTS="$prompts_shown" \
T_START="$T_START" T_INSTALLED="$t_installed" T_FIRST_DATA="$t_first_data" \
MEM_BEFORE="$mem_before" MEM_AFTER="$mem_after" PEAK_MEM="$peak_mem" \
DISK_BEFORE="$disk_before" DISK_AFTER="$disk_after" PEAK_DISK="$peak_disk" \
INSTALL_STATUS="$install_status" PROMPT_STATUS="$prompt_status" \
LOAD_STATUS="$load_status" MODE_STATUS="$mode_status" \
FIRST_DATA_STATUS="$first_data_status" WEB_STATUS="$web_status" \
$PYTHON_BIN - <<'PY' > "$OUT"
import json
import os

env = os.environ
start = int(env["T_START"])
installed = int(env["T_INSTALLED"])
first_data = int(env["T_FIRST_DATA"])
result = {
    "runner_image": env["RUNNER_IMAGE"],
    "base_sha": env["BASE_SHA"],
    "prompts_shown": int(env["PROMPTS"]),
    "install_seconds": installed - start if installed else None,
    "first_data_seconds": first_data - start if first_data else None,
    "ram_used_kb": {
        "before": int(env["MEM_BEFORE"]), "after": int(env["MEM_AFTER"]),
        "peak": int(env["PEAK_MEM"]),
    },
    "disk_used_kb": {
        "before": int(env["DISK_BEFORE"]), "after": int(env["DISK_AFTER"]),
        "peak": int(env["PEAK_DISK"]),
    },
    "exit_status": {
        "install": int(env["INSTALL_STATUS"]),
        "prompt_count": int(env["PROMPT_STATUS"]),
        "load_configuration": int(env["LOAD_STATUS"]),
        "set_active_mode": int(env["MODE_STATUS"]),
        "first_data": int(env["FIRST_DATA_STATUS"]),
        "web_console": int(env["WEB_STATUS"]),
    },
}
print(json.dumps(result, indent=2, sort_keys=True))
PY
cat "$OUT"

(( install_status == 0 && prompt_status == 0 && load_status == 0 &&
   mode_status == 0 && first_data_status == 0 && web_status == 0 ))
