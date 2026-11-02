#!/usr/bin/env python3

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone


DEFAULT_RESOLVERS = [
    {"name": "Cloudflare", "address": "1.1.1.1"},
    {"name": "Google", "address": "8.8.8.8"},
    {"name": "Quad9", "address": "9.9.9.9"},
]

DEFAULT_DOMAINS = [
    "nvidia.com",
    "intel.com",
    "cloudflare.com",
]


def query_dns(server, port, domain, record_type, timeout):
    command = [
        "dig",
        f"@{server}",
        "-p", str(port),
        domain,
        record_type,
        f"+time={timeout}",
        "+tries=1",
        "+dnssec",
        "+adflag",
        "+noall",
        "+comments",
        "+answer",
        "+stats",
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout + 2,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "TIMEOUT",
            "answers": [],
            "latency_ms": None,
            "dnssec_ad": False,
            "error": "Query process timed out",
        }

    output = result.stdout + "\n" + result.stderr
    output_lower = output.lower()

    status_match = re.search(r"status:\s*([A-Z]+)", output)
    flags_match = re.search(r";;\s*flags:\s*([^;]+);", output)
    time_match = re.search(r"Query time:\s*(\d+)\s*msec", output)

    status = status_match.group(1) if status_match else "ERROR"
    flags = flags_match.group(1).split() if flags_match else []

    if "connection refused" in output_lower:
        status = "CONNECTION_REFUSED"
    elif "timed out" in output_lower:
        status = "TIMEOUT"

    answers = []

    for line in output.splitlines():
        line = line.strip()

        if not line or line.startswith(";"):
            continue

        fields = line.split()

        if len(fields) >= 5:
            answer_type = fields[3].upper()

            if answer_type == "RRSIG":
                continue

            answers.append({
                "name": fields[0],
                "ttl": fields[1],
                "type": answer_type,
                "data": " ".join(fields[4:]),
            })

    error = None

    if status in ("ERROR", "TIMEOUT"):
        error = output.strip()[-500:] or (
            "Query timed out" if status == "TIMEOUT"
            else f"dig exited with code {result.returncode}"
        )

    return {
        "status": status,
        "answers": answers,
        "latency_ms": int(time_match.group(1)) if time_match else None,
        "dnssec_ad": "ad" in flags,
        "error": error,
    }


def compare_results(results):
    successful = [
        item for item in results
        if item["status"] == "NOERROR"
    ]

    nonempty = [
        item for item in successful
        if item["answers"]
    ]

    answer_sets = {
        tuple(sorted(
            (answer["type"], answer["data"])
            for answer in item["answers"]
        ))
        for item in nonempty
    }

    statuses = {item["status"] for item in results}

    findings = []

    if "TIMEOUT" in statuses:
        findings.append("At least one resolver timed out.")

    if "SERVFAIL" in statuses:
        findings.append("At least one resolver returned SERVFAIL.")

    if "CONNECTION_REFUSED" in statuses:
        findings.append(
            "At least one DNS resolver refused the connection. "
            "Check whether the service is running and listening on the configured port."
        )

    if "ERROR" in statuses:
        findings.append(
            "At least one resolver returned an unexpected DNS query error."
        )

    if "NXDOMAIN" in statuses and "NOERROR" in statuses:
        findings.append(
            "Resolvers disagree about domain existence. "
            "Investigate possible DNS interference."
        )

    if len(answer_sets) > 1:
        findings.append(
            "Resolvers returned different answers. "
            "This can be normal because of CDN, geography, or load balancing."
        )

    if successful and not nonempty:
        findings.append(
            "NOERROR was returned without records (possible NODATA response)."
        )

    if not findings:
        findings.append("No obvious DNS inconsistency detected.")

    return findings


def main():
    parser = argparse.ArgumentParser(
        description="Read-only DNS diagnostics for multiple resolvers."
    )

    parser.add_argument(
        "--domain",
        action="append",
        help="Domain to test. Can be specified multiple times.",
    )
    parser.add_argument(
        "--server",
        action="append",
        help="Additional DNS server IP to test. Can be specified multiple times.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=53,
        help="Port for additional DNS servers (default: 53).",
    )
    parser.add_argument(
        "--include-local",
        action="store_true",
        help="Also test the local DNS service at 127.0.0.1:53.",
    )
    parser.add_argument(
        "--include-unbound",
        action="store_true",
        help="Also test local Unbound.",
    )
    parser.add_argument(
        "--unbound-port",
        type=int,
        choices=range(1, 65536),
        default=5353,
        help="Local Unbound port (default: 5353).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=3,
        choices=range(1, 11),
        help="Per-query timeout in seconds (default: 3).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    args = parser.parse_args()

    if not shutil.which("dig"):
        print("ERROR: dig is not installed. Install dnsutils.", file=sys.stderr)
        return 2

    domains = args.domain or DEFAULT_DOMAINS

    resolvers = [
        {**item, "port": 53, "scope": "public"}
        for item in DEFAULT_RESOLVERS
    ]

    for server in args.server or []:
        resolvers.append({
            "name": f"Custom ({server})",
            "address": server,
            "port": args.port,
            "scope": "custom",
        })

    if args.include_local:
        resolvers.append({
            "name": "Local DNS",
            "address": "127.0.0.1",
            "port": 53,
            "scope": "local",
        })

    if args.include_unbound:
        resolvers.append({
            "name": "Local Unbound",
            "address": "127.0.0.1",
            "port": args.unbound_port,
            "scope": "local",
        })

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read-only",
        "results": [],
    }

    for domain in domains:
        for record_type in ("A", "AAAA"):
            query_results = []

            for resolver in resolvers:
                port = resolver["port"]

                result = query_dns(
                    resolver["address"],
                    port,
                    domain,
                    record_type,
                    args.timeout,
                )

                entry = {
                    "resolver": resolver["name"],
                    "server": resolver["address"],
                    "port": port,
                    "scope": resolver["scope"],
                    "domain": domain,
                    "record_type": record_type,
                    **result,
                }

                query_results.append(entry)

            report["results"].extend(query_results)

            for scope in ("public", "custom", "local"):
                scoped_results = [
                    item for item in query_results
                    if item["scope"] == scope
                ]

                if not scoped_results:
                    continue

                findings = compare_results(scoped_results)

                report.setdefault("findings", []).append({
                    "scope": scope,
                    "domain": domain,
                    "record_type": record_type,
                    "items": findings,
                })

    report["dnssec_checks"] = []

    for resolver in resolvers:
        port = resolver["port"]

        valid_test = query_dns(
            resolver["address"],
            port,
            "cloudflare.com",
            "A",
            args.timeout,
        )

        invalid_test = query_dns(
            resolver["address"],
            port,
            "dnssec-failed.org",
            "A",
            args.timeout,
        )

        if (
            valid_test["status"] == "NOERROR"
            and valid_test["dnssec_ad"]
            and invalid_test["status"] == "SERVFAIL"
        ):
            verdict = "VALIDATION_CONFIRMED"
        elif invalid_test["status"] == "NOERROR":
            verdict = "VALIDATION_NOT_CONFIRMED"
        elif (
            valid_test["status"] == "NOERROR"
            and invalid_test["status"] == "SERVFAIL"
        ):
            verdict = "BOGUS_REJECTED_AD_NOT_CONFIRMED"
        else:
            verdict = "INCONCLUSIVE"

        report["dnssec_checks"].append({
            "resolver": resolver["name"],
            "server": resolver["address"],
            "port": port,
            "scope": resolver["scope"],
            "valid_domain_status": valid_test["status"],
            "valid_domain_ad": valid_test["dnssec_ad"],
            "invalid_domain_status": invalid_test["status"],
            "verdict": verdict,
        })

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print("DNS Diagnostics")
    print("================")
    print(f"Generated: {report['generated_at']}")
    print("Mode: READ ONLY")
    print()

    for item in report["results"]:
        latency = (
            f"{item['latency_ms']} ms"
            if item["latency_ms"] is not None
            else "N/A"
        )

        print(
            f"{item['domain']} {item['record_type']} | "
            f"{item['resolver']} ({item['server']}) | "
            f"Scope: {item['scope']} | "
            f"{item['status']} | {latency} | "
            f"DNSSEC AD: {item['dnssec_ad']}"
        )

        for answer in item["answers"]:
            print(f"  {answer['type']} {answer['data']}")

        if item["error"]:
            print(f"  Error: {item['error']}")

    print()
    print("Findings")
    print("--------")

    for finding in report["findings"]:
        print(
            f"{finding['domain']} {finding['record_type']} "
            f"[{finding['scope']}]:"
        )

        for message in finding["items"]:
            print(f"  - {message}")

    print()
    print()
    print("DNSSEC Validation")
    print("-----------------")

    for item in report["dnssec_checks"]:
        print(
            f"{item['resolver']} ({item['server']}) | "
            f"Scope: {item['scope']} | "
            f"Valid domain: {item['valid_domain_status']} | "
            f"AD: {item['valid_domain_ad']} | "
            f"Invalid domain: {item['invalid_domain_status']} | "
            f"{item['verdict']}"
        )

    print("Note: Different IP answers do not by themselves prove DNS spoofing.")
    print("DNSSEC AD is an indicator, not a complete DNS integrity verdict.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
