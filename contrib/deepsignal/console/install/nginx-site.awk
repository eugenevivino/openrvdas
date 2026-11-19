# Return byte offsets for the managed block (or its insertion point), and the
# selected server's opening brace and local /cds-ws endpoint. The installer copies all
# other bytes verbatim. Run with LC_ALL=C so offsets are bytes even in UTF-8 files.

function word() {
    if (in_word) {
        words[++count] = token
        token = ""
        in_word = 0
    }
}

function listener(    address, port, scheme, i) {
    address = words[2]
    port = 80
    scheme = "ws"
    if (address ~ /^[0-9]+$/) {
        port = address
        address = "*"
    } else if (address ~ /:[0-9]+$/) {
        port = address
        sub(/^.*:/, "", port)
        sub(/:[0-9]+$/, "", address)
    }
    if (address == "*" || address == "0.0.0.0") address = "127.0.0.1"
    if (address == "[::]") address = "[::1]"
    for (i = 3; i <= count; i++) if (words[i] == "ssl") scheme = "wss"
    endpoints[server] = port " " scheme " " address
}

function cds_target(target,    port) {
    if (target ~ /^(https?:\/\/)?unix:/) return 0
    sub(/^[A-Za-z]+:\/\//, "", target)
    sub(/[\/?#].*$/, "", target)
    if (target !~ /:[0-9]+$/) return 0
    sub(/^.*:/, "", target)
    port = target + 0
    return port == 8766 || (udp_port && port == udp_port)
}

function directive(end, position, line_prefix,    i, path) {
    if (end != "}" && !count) invalid = 1
    if (end == "{") {
        if (words[1] == "server" && count == 1 && depth == http_depth) {
            server = ++servers
            server_depth = depth + 1
            server_start[server] = position
        } else if (words[1] == "http" && depth == 0) {
            http_depth = 1
        } else if (words[1] == "stream" && depth == 0) {
            stream_depth = 1
        } else if (words[1] == "upstream" && depth == http_depth) {
            upstream_depth = depth + 1
        }
        depth++
    } else if (end == ";") {
        if (words[1] ~ /_pass$/ && cds_target(words[2])) {
            if (server) direct_cds[server] = 1
            if (stream_depth) direct_stream = 1
        }
        if (words[1] == "server" && depth == upstream_depth && cds_target(words[2])) direct_stream = 1
        if (stream_depth && words[1] == "listen" && udp_port) {
            path = words[2]
            sub(/^.*:/, "", path)
            for (i = 3; i <= count; i++) if (words[i] == "udp" && path + 0 == udp_port) direct_stream = 1
        }
        if (server && depth == server_depth && words[1] == "server_name") {
            if (!(server in primary_name)) primary_name[server] = words[2]
            for (i = 2; i <= count; i++) if (words[i] == ENVIRON["CONSOLE_SERVER_NAME"]) named[server] = 1
        } else if (server && depth == server_depth && words[1] == "listen") {
            if (!(server in endpoints)) listener()
        }
    } else {
        if (count || depth <= 0) invalid = 1
        if (server && depth == server_depth) {
            if (in_marker) bad_markers[server] = 1
            in_marker = 0
            insert_at[server] = (line_prefix ~ /^[ \t]*$/) ? offset : position
            server = 0
        }
        if (depth <= http_depth) http_depth = 0
        if (depth == stream_depth) stream_depth = 0
        if (depth == upstream_depth) upstream_depth = 0
        depth--
    }
    for (i = 1; i <= count; i++) delete words[i]
    count = 0
}

function marker(comment, position, line_prefix) {
    if (!server || depth != server_depth) return
    if (comment ~ /^# BEGIN deepsignal-console[ \t\r]*$/) {
        if ((line_prefix !~ /^[ \t]*$/ && line_prefix !~ /    $/) || begin_at[server] != "") {
            bad_markers[server] = 1
        }
        begin_at[server] = (line_prefix ~ /^[ \t]*$/) ? offset : position - 4
        in_marker = 1
    } else if (comment ~ /^# END deepsignal-console[ \t\r]*$/) {
        if (!in_marker || line_prefix !~ /^[ \t]*$/) bad_markers[server] = 1
        end_at[server] = offset + length($0) + 1
        in_marker = 0
    }
}

{
    for (column = 1; column <= length($0); column++) {
        char = substr($0, column, 1)
        if (char == "\\") {
            in_word = 1
            token = token char substr($0, ++column, 1)
        } else if (quote != "") {
            if (char == quote) quote = ""
            else token = token char
        } else if (char == "\"" || char == "\047") {
            in_word = 1
            quote = char
        } else if (char == "{" && in_word && token ~ /\$$/) {
            variable = 1
            token = token char
        } else if (char == "}" && variable) {
            variable = 0
            token = token char
        } else if (char == "#" && !in_word) {
            marker(substr($0, column), offset + column - 1, substr($0, 1, column - 1))
            break
        } else if (char ~ /^[ \t\r]$/) {
            word()
        } else if (char ~ /^[{};]$/) {
            word()
            directive(char, offset + column - 1, substr($0, 1, column - 1))
        } else {
            in_word = 1
            token = token char
        }
    }
    if (quote != "") token = token "\n"
    else word()
    offset += length($0) + 1
}

END {
    if (depth || quote != "" || variable || invalid || count) exit 3
    for (i = 1; i <= servers; i++) {
        if (ENVIRON["CONSOLE_SERVER_NAME"] == "" || named[i]) {
            selected = i
            matches++
        }
    }
    if (matches != 1) exit 4
    if (bad_markers[selected]) exit 5
    if (begin_at[selected] != "") printf "%d %d", begin_at[selected], end_at[selected]
    else printf "%d %d", insert_at[selected], insert_at[selected]
    if (direct_cds[selected] || direct_stream) status = "unsafe"
    else status = "check"
    name = ENVIRON["CONSOLE_SERVER_NAME"]
    if (name == "") name = primary_name[selected]
    if (name == "") name = "_"
    endpoint = selected in endpoints ? endpoints[selected] : "80 ws 127.0.0.1"
    print " " status, server_start[selected], name, endpoint
}
