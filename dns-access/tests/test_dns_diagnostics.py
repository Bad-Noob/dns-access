import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "dns-diagnostics.py"

SPEC = importlib.util.spec_from_file_location(
    "dns_diagnostics",
    MODULE_PATH,
)

dns = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dns)


class QueryDnsTests(unittest.TestCase):

    @patch.object(dns.subprocess, "run")
    def test_successful_a_query(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["dig"],
            returncode=0,
            stdout=(
                ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 1234\n"
                ";; flags: qr rd ra ad; QUERY: 1, ANSWER: 1\n"
                "example.com. 300 IN A 192.0.2.10\n"
                ";; Query time: 15 msec\n"
            ),
            stderr="",
        )

        result = dns.query_dns("1.1.1.1", 53, "example.com", "A", 3)

        self.assertEqual(result["status"], "NOERROR")
        self.assertEqual(len(result["answers"]), 1)
        self.assertEqual(result["answers"][0]["data"], "192.0.2.10")
        self.assertTrue(result["dnssec_ad"])
        self.assertEqual(result["latency_ms"], 15)

    @patch.object(dns.subprocess, "run")
    def test_nxdomain(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["dig"],
            returncode=0,
            stdout=";; ->>HEADER<<- opcode: QUERY, status: NXDOMAIN, id: 1\n",
            stderr="",
        )

        result = dns.query_dns("1.1.1.1", 53, "missing.example", "A", 3)

        self.assertEqual(result["status"], "NXDOMAIN")
        self.assertEqual(result["answers"], [])

    @patch.object(dns.subprocess, "run")
    def test_servfail(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["dig"],
            returncode=0,
            stdout=";; ->>HEADER<<- opcode: QUERY, status: SERVFAIL, id: 1\n",
            stderr="",
        )

        result = dns.query_dns("1.1.1.1", 53, "example.com", "A", 3)

        self.assertEqual(result["status"], "SERVFAIL")

    @patch.object(dns.subprocess, "run")
    def test_connection_refused(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["dig"],
            returncode=9,
            stdout="",
            stderr=";; communications error to 127.0.0.1#5353: connection refused",
        )

        result = dns.query_dns("127.0.0.1", 5353, "example.com", "A", 3)

        self.assertEqual(result["status"], "CONNECTION_REFUSED")

    @patch.object(dns.subprocess, "run")
    def test_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["dig"],
            timeout=5,
        )

        result = dns.query_dns("1.1.1.1", 53, "example.com", "A", 3)

        self.assertEqual(result["status"], "TIMEOUT")
        self.assertIsNone(result["latency_ms"])

    @patch.object(dns.subprocess, "run")
    def test_dig_reported_timeout(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["dig"],
            returncode=9,
            stdout="",
            stderr=(
                ";; communications error to 9.9.9.9#53: timed out\\n"
                ";; no servers could be reached"
            ),
        )

        result = dns.query_dns("9.9.9.9", 53, "example.com", "A", 3)

        self.assertEqual(result["status"], "TIMEOUT")
        self.assertIsNone(result["latency_ms"])
        self.assertIn("timed out", result["error"].lower())

    @patch.object(dns.subprocess, "run")
    def test_rrsig_is_not_treated_as_a_record(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["dig"],
            returncode=0,
            stdout=(
                ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 1\n"
                ";; flags: qr rd ra ad; QUERY: 1, ANSWER: 2\n"
                "example.com. 300 IN A 192.0.2.10\n"
                "example.com. 300 IN RRSIG A 8 2 300 20300101000000 20290101000000 1234 example.com. ABCD\n"
            ),
            stderr="",
        )

        result = dns.query_dns("1.1.1.1", 53, "example.com", "A", 3)

        self.assertEqual(
            [answer["type"] for answer in result["answers"]],
            ["A"],
        )


class CompareResultsTests(unittest.TestCase):

    def make_result(self, status, answers=None):
        return {
            "status": status,
            "answers": answers or [],
        }

    def test_identical_answers(self):
        answer = [{"type": "A", "data": "192.0.2.10"}]

        findings = dns.compare_results([
            self.make_result("NOERROR", answer),
            self.make_result("NOERROR", answer),
        ])

        self.assertEqual(
            findings,
            ["No obvious DNS inconsistency detected."],
        )

    def test_nxdomain_and_noerror_disagreement(self):
        findings = dns.compare_results([
            self.make_result("NXDOMAIN"),
            self.make_result("NOERROR", [{"type": "A", "data": "192.0.2.10"}]),
        ])

        self.assertTrue(any("disagree" in item.lower() for item in findings))

    def test_different_answers(self):
        findings = dns.compare_results([
            self.make_result("NOERROR", [{"type": "A", "data": "192.0.2.10"}]),
            self.make_result("NOERROR", [{"type": "A", "data": "192.0.2.20"}]),
        ])

        self.assertTrue(any("different answers" in item.lower() for item in findings))

    def test_timeout_finding(self):
        findings = dns.compare_results([
            self.make_result("TIMEOUT"),
        ])

        self.assertTrue(any("timed out" in item.lower() for item in findings))

    def test_servfail_finding(self):
        findings = dns.compare_results([
            self.make_result("SERVFAIL"),
        ])

        self.assertTrue(any("servfail" in item.lower() for item in findings))

    def test_connection_refused_finding(self):
        findings = dns.compare_results([
            self.make_result("CONNECTION_REFUSED"),
        ])

        self.assertTrue(any("refused" in item.lower() for item in findings))

    def test_nodata_finding(self):
        findings = dns.compare_results([
            self.make_result("NOERROR"),
            self.make_result("NOERROR"),
        ])

        self.assertTrue(any("NODATA" in item for item in findings))


if __name__ == "__main__":
    unittest.main()
