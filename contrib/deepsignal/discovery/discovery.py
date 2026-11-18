"""Command line entry point for strictly read-only stream discovery."""

import argparse
import json
import os

import yaml

from contrib.deepsignal.discovery.cds_scan import scan_cds
from contrib.deepsignal.discovery.file_scan import scan_files
from contrib.deepsignal.discovery.mqtt_scan import scan_mqtt
from contrib.deepsignal.discovery.redis_scan import scan_redis
from contrib.deepsignal.discovery.serial_scan import candidate_ports, scan_port
from contrib.deepsignal.discovery.tcp_http_scan import scan_http, scan_tcp
from contrib.deepsignal.discovery.udp_scan import scan_udp_port


def _safe_name(value):
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in str(value))


def write_results(results, output_dir=".", capture_dir=None):
    """Write stable JSON output and optional bounded text captures."""
    os.makedirs(output_dir, exist_ok=True)
    if capture_dir:
        os.makedirs(capture_dir, exist_ok=True)
        for result in results:
            lines = result.get("capture_lines", [])[:200]
            if not lines:
                continue
            name = "%s_%s.txt" % (result["transport"], _safe_name(result["port"]))
            with open(os.path.join(capture_dir, name), "w", encoding="utf-8") as target:
                target.write("\n".join(lines) + "\n")
    public = [{key: value for key, value in result.items() if key != "capture_lines"}
              for result in results]
    path = os.path.join(output_dir, "discovery.json")
    with open(path, "w", encoding="utf-8") as target:
        json.dump({"streams": public}, target, indent=2, sort_keys=True)
        target.write("\n")
    return path


def parse_ports(values):
    ports = set()
    for value in values:
        try:
            if "-" in value:
                first, last = (int(item) for item in value.split("-", 1))
                if first > last:
                    raise ValueError()
                ports.update(range(first, last + 1))
            else:
                ports.add(int(value))
        except ValueError as error:
            raise ValueError("UDP ports saw %r; expected PORT or FIRST-LAST, for example 6221-6230"
                             % value) from error
    if any(port < 1 or port > 65535 for port in ports):
        raise ValueError("UDP ports saw a value outside 1-65535; expected a valid local port, "
                         "for example 6221")
    return sorted(ports)


def build_parser():
    parser = argparse.ArgumentParser(description="Passively discover data streams on this box")
    parser.add_argument("--listen-s", type=float, default=3)
    parser.add_argument("--config", help="YAML cruise definition containing udp_ports")
    parser.add_argument("--serial", action="append", default=[])
    parser.add_argument("--all-serial", action="store_true")
    parser.add_argument("--udp", action="append", default=[])
    parser.add_argument("--mqtt")
    parser.add_argument("--mqtt-credentials")
    parser.add_argument("--redis")
    parser.add_argument("--cds")
    parser.add_argument("--files")
    parser.add_argument("--tcp", action="append", default=[])
    parser.add_argument("--http", action="append", default=[])
    parser.add_argument("--capture")
    parser.add_argument("--output-dir", default=".")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.listen_s <= 0:
        parser.error("listen-s saw %r; expected seconds greater than zero, for example 3" %
                     args.listen_s)
    configured_ports = []
    if args.config:
        try:
            with open(args.config, encoding="utf-8") as source:
                config = yaml.safe_load(source) or {}
        except (OSError, yaml.YAMLError) as error:
            parser.error("config saw %r; expected a readable YAML file, for example "
                         "contrib/deepsignal/configs/discovery_example.yaml (%s)" %
                         (args.config, error))
        if not isinstance(config, dict):
            parser.error("config saw %s; expected a YAML mapping, for example 'udp_ports: [6221]'"
                         % type(config).__name__)
        configured_ports = config.get("udp_ports", [])
        if not isinstance(configured_ports, list):
            parser.error("udp_ports saw %r; expected a YAML list, for example [6221, 6222]" %
                         configured_ports)
        configured_ports = [str(value) for value in configured_ports]
    try:
        udp_ports = parse_ports(args.udp + configured_ports or ["6221-6230"])
    except ValueError as error:
        parser.error(str(error))
    serial_ports = list(args.serial)
    if args.all_serial:
        serial_ports.extend(candidate_ports())
    results = [scan_port(port, args.listen_s) for port in sorted(set(serial_ports))]
    results.extend(scan_udp_port(port, args.listen_s) for port in udp_ports)
    if args.mqtt:
        results.extend(scan_mqtt(args.mqtt, args.listen_s, args.mqtt_credentials))
    else:
        print("MQTT skipped: no --mqtt target was given")
    if args.redis:
        results.extend(scan_redis(args.redis, args.listen_s))
    else:
        print("Redis skipped: no --redis target was given")
    if args.cds:
        results.append(scan_cds(args.cds, args.listen_s))
    else:
        print("CDS skipped: no --cds target was given")
    if args.files:
        results.extend(scan_files(args.files))
    else:
        print("Files skipped: no --files directory was given")
    if not args.tcp:
        print("TCP skipped: no --tcp target was given")
    if not args.http:
        print("HTTP skipped: no --http target was given")
    results.extend(scan_tcp(target, args.listen_s) for target in args.tcp)
    results.extend(scan_http(url, args.listen_s) for url in args.http)
    print("TRANSPORT  PORT/TARGET                 BAUD    LINES/S  STATUS")
    for result in results:
        print("{transport:<10} {port!s:<27} {baud!s:<7} {rate!s:<8} {status}".format(
            transport=result["transport"], port=result["port"],
            baud=result.get("baud", "-"), rate=result.get("lines_per_second", "-"),
            status=result.get("status", "unknown")))
    write_results(results, args.output_dir, args.capture)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
