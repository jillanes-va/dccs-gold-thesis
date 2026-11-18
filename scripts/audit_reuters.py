"""Execute the unchanged Reuters pilot with a separate, detailed network audit.

Usage: uv run --no-sync python scripts/audit_reuters.py --live
       uv run --no-sync python scripts/audit_reuters.py --offline-tests
Outputs go to ignored data/diagnostics; no new access route or user agent is used.
"""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import pilot


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def run_offline_tests(out):
    """Save executed test results, including traces of unresolved defects."""
    started = utc_now()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_pilot_reuters.py")
    with (out / "offline_tests.txt").open("w", encoding="utf-8") as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    report = {
        "started_at_utc": started, "finished_at_utc": utc_now(),
        "python": sys.version,
        "pilot_sha256": hashlib.sha256((ROOT / "src/pilot.py").read_bytes()).hexdigest(),
        "test_sha256": hashlib.sha256((ROOT / "tests/test_pilot_reuters.py").read_bytes()).hexdigest(),
        "tests_run": result.testsRun,
        "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.expectedFailures) - len(result.unexpectedSuccesses) - len(result.skipped),
        "failures": [{"test": test.id(), "trace": trace} for test, trace in result.failures],
        "errors": [{"test": test.id(), "trace": trace} for test, trace in result.errors],
        "unresolved_defects": [{"test": test.id(), "trace": trace} for test, trace in result.expectedFailures],
        "unexpected_successes": [test.id() for test in result.unexpectedSuccesses],
        "skipped": [{"test": test.id(), "reason": reason} for test, reason in result.skipped],
        "note": "Offline synthetic inputs; expected failures reproduce unresolved defects. This is not validation of access to live Reuters articles.",
    }
    (out / "offline_results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"tests_run": report["tests_run"], "passed": report["passed"],
                      "unresolved_defects": len(result.expectedFailures), "failures": len(result.failures),
                      "errors": len(result.errors), "output": str(out.resolve())}, indent=2))
    if not result.wasSuccessful():
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true", help="Explicitly enable network requests")
    mode.add_argument("--offline-tests", action="store_true", help="Run and save synthetic tests without network")
    parser.add_argument("--max-per-source", type=int, default=60)
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--system-trust", action="store_true",
                        help="Use the OS certificate store, keeping TLS verification enabled")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.max_per_source <= 60 or args.delay < 3 or args.timeout < 1:
        parser.error("audit bounds: 1..60 candidates, delay >= 3 seconds, timeout >= 1")
    if args.system_trust and args.live:
        import truststore
        truststore.inject_into_ssl()
    started = utc_now()
    out = args.output or ROOT / "data" / "diagnostics" / ("reuters_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    out.mkdir(parents=True, exist_ok=False)
    if args.offline_tests:
        run_offline_tests(out)
        return
    config = argparse.Namespace(sources=["reuters"], max_per_source=args.max_per_source,
                                delay=args.delay, timeout=args.timeout, min_words=100,
                                output=str(out / "pilot"))
    git = subprocess.run(["git", "-c", f"safe.directory={ROOT.as_posix()}", "rev-parse", "HEAD"],
                         cwd=ROOT, capture_output=True, text=True)
    manifest = {
        "started_at_utc": started, "source": "reuters", "configuration": vars(config),
        "python": sys.version, "system": platform.platform(),
        "git_head": git.stdout.strip() if git.returncode == 0 else None,
        "tls_trust": "system" if args.system_trust else "requests_default",
        "pilot_sha256": hashlib.sha256((ROOT / "src/pilot.py").read_bytes()).hexdigest(),
        "dependencies": {name: importlib.metadata.version(name) for name in
                         ("requests", "trafilatura", "beautifulsoup4", "python-dateutil")},
        "note": "Unchanged pilot; audit is observational. No retries or access bypasses.",
    }
    send = pilot.requests.Session.send
    permitted = pilot.Fetcher.permitted
    request_count = 0

    with (out / "http.jsonl").open("w", encoding="utf-8") as http_log, \
         (out / "robots_decisions.jsonl").open("w", encoding="utf-8") as robots_log:

        def audited_send(session, request, **kwargs):
            nonlocal request_count
            request_count += 1
            record = {"request_id": request_count, "started_at_utc": utc_now(),
                      "method": request.method, "url": request.url}
            tick = time.monotonic()
            try:
                response = send(session, request, **kwargs)
                record.update(http_status=response.status_code, final_url=response.url,
                              content_type=response.headers.get("Content-Type"),
                              retry_after=response.headers.get("Retry-After"),
                              location=response.headers.get("Location"),
                              response_bytes=len(response.content),
                              response_sha256=hashlib.sha256(response.content).hexdigest(),
                              redirects=[{"url": r.url, "http_status": r.status_code}
                                         for r in response.history])
                if urlparse(request.url).path == "/robots.txt":
                    (out / f"robots_response_{record['request_id']}.txt").write_text(response.text, encoding="utf-8")
                    record["robots_body_file"] = f"robots_response_{record['request_id']}.txt"
                    record["looks_like_robots"] = any(line.strip().lower().startswith("user-agent:") for line in response.text.splitlines())
                return response
            except pilot.requests.RequestException as exc:
                record.update(error_type=type(exc).__name__, error=str(exc)[:1000])
                raise
            finally:
                record.update(finished_at_utc=utc_now(), elapsed_seconds=round(time.monotonic() - tick, 4))
                http_log.write(json.dumps(record, ensure_ascii=False) + "\n")
                http_log.flush()
                print("HTTP_AUDIT " + json.dumps(record, ensure_ascii=False), flush=True)

        def audited_permitted(fetcher, url):
            result = permitted(fetcher, url)
            p = urlparse(url)
            rp = fetcher.robots.get(f"{p.scheme}://{p.netloc}")
            record = {"checked_at_utc": utc_now(), "url": url, "allowed": result,
                      "parser_available": rp is not None,
                      "reason": "allowed" if result else ("explicit_rule" if rp is not None else "robots_unavailable"),
                      "crawl_delay": rp.crawl_delay(pilot.AGENT) if rp is not None else None}
            robots_log.write(json.dumps(record) + "\n")
            robots_log.flush()
            return result

        try:
            with patch.object(pilot.requests.Session, "send", audited_send), \
                 patch.object(pilot.Fetcher, "permitted", audited_permitted):
                pilot.run(config)
            manifest["completed"] = True
        except BaseException as exc:
            manifest.update(completed=False, failure_type=type(exc).__name__, failure=str(exc))
            raise
        finally:
            manifest.update(finished_at_utc=utc_now(), http_send_calls=request_count)
            (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"AUDIT_DIRECTORY={out.resolve()}", flush=True)


if __name__ == "__main__":
    main()
