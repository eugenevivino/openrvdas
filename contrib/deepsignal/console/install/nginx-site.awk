# Return byte offsets for the managed block (or its insertion point), and the
# selected server's local /cds-ws configuration. The installer copies all other
# bytes verbatim. Run with LC_ALL=C so offsets are bytes even in UTF-8 files.

function word() {
    if (in_word) {
        words[++count] = token
        token = ""
        in_word = 0
    }
}

function directive(end, position, line_prefix,    i, path, exact) {
    if (end == "{") {
        if (words[1] == "server" && count == 1 && depth == http_depth) {
            server = ++servers
            server_depth = depth + 1
        } else if (words[1] == "http" && depth == 0) {
            http_depth = 1
        } else if (server && depth == server_depth && !in_marker && words[1] == "location") {
            path = words[count]
            exact = words[2] == "="
            if (path == "/cds-ws" && (count == 2 || exact || words[2] == "^~")) {
                routes[server]++
                route_depth = depth + 1
                if (exact || words[2] == "^~") protected_route[server] = 1
            } else if (words[2] == "~" || words[2] == "~*") {
                regex_or_include[server] = 1
            }
        }
        depth++
    } else if (end == ";") {
        if (server && depth == server_depth && words[1] == "server_name") {
            for (i = 2; i <= count; i++) if (words[i] == ENVIRON["CONSOLE_SERVER_NAME"]) named[server] = 1
        } else if (server && depth == server_depth && words[1] == "include") {
            regex_or_include[server] = 1
        } else if (route_depth && words[1] == "proxy_pass") {
            if (depth == route_depth && count == 2 && words[2] == "http://unix:/run/deepsignal/cds-gateway.sock:") {
                gateway[server]++
            } else {
                other_proxy[server] = 1
            }
        } else if (route_depth && words[1] == "include") {
            other_proxy[server] = 1
        }
    } else {
        if (count) invalid = 1
        if (depth == route_depth) route_depth = 0
        if (server && depth == server_depth) {
            if (in_marker) bad_markers[server] = 1
            in_marker = 0
            insert_at[server] = (line_prefix ~ /^[ \t]*$/) ? offset : position
            server = 0
        }
        if (depth <= http_depth) http_depth = 0
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
    if (depth || quote != "" || invalid || count) exit 3
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
    if (!routes[selected]) print " missing"
    else if (routes[selected] == 1 && gateway[selected] == 1 && !other_proxy[selected] &&
        (protected_route[selected] || !regex_or_include[selected])) print " gateway"
    else print " unsafe"
}
