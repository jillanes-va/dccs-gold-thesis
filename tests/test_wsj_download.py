"""Pruebas de adquisición y procedencia con HTML sintético y transporte sin red."""
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import requests

from src import wsj_download as wsj


URL = "https://www.wsj.com/articles/example-story-1404272455"
TEXT = "\n\n".join(f"Párrafo sintético {i}. " + "economía información investigación datos mercado. " * 10 for i in range(4))


def html(text=TEXT, **fields):
    node = {"@type": "NewsArticle", "headline": "Example story", "articleBody": text,
            "datePublished": "2014-07-01T12:00:00-04:00", **fields}
    return ('<html lang="en"><head><title>Example story</title><script type="application/ld+json">'
            + json.dumps(node) + '</script></head><body><article><p>Vista de ejemplo.</p></article></body></html>').encode()


class FakeResponse:
    def __init__(self, code=200, body=b"", **headers):
        self.status_code = code
        self.body = body
        self.headers = {"Content-Type": "text/html", **headers}

    def iter_content(self, size):
        yield self.body

    def close(self):
        pass


class ExtractionTests(unittest.TestCase):
    def test_jsonld_body_and_publication_preserved(self):
        result = wsj.extract_html(html(), URL)
        self.assertEqual(result["status"], "candidate_unverified")
        self.assertEqual(result["extraction_method"], "jsonld.articleBody")
        self.assertEqual(result["published_at_raw"], "2014-07-01T12:00:00-04:00")
        self.assertFalse(result["full_text_verified"])
        self.assertEqual(result["text_sha256"], wsj.sha(TEXT.strip().encode()))

    def test_restriction_is_not_exported_as_full_article(self):
        for value in (False, "false"):
            result = wsj.extract_html(html(isAccessibleForFree=value), URL)
            self.assertEqual(result["status"], "restricted_content")
            self.assertEqual(result["text"], "")

    def test_nested_restricted_part(self):
        self.assertEqual(wsj.extract_html(html(hasPart={"isAccessibleForFree": False}), URL)["status"], "restricted_content")

    def test_paywall_dom_and_challenge(self):
        for fragment, status in ((b'<div data-testid="paywall">Suscripcion</div>', "restricted_content"),
                                 (b'<iframe src="https://x/captcha"></iframe>', "access_challenge")):
            self.assertEqual(wsj.extract_html(html() + fragment, URL)["status"], status)

    def test_short_text_remains_partial(self):
        result = wsj.extract_html(html("Texto corto de prueba."), URL)
        self.assertEqual(result["status"], "short_or_partial")
        self.assertTrue(result["text"])

    def test_dom_fallback_and_malformed_json(self):
        content = ('<html><head><script type="application/ld+json">{broken</script></head>'
                   '<body><div itemprop="articleBody"><p>' + TEXT + '</p></div></body></html>').encode()
        result = wsj.extract_html(content, URL)
        self.assertEqual(result["status"], "candidate_unverified")
        self.assertEqual(result["extraction_method"], "dom.article_body")

    def test_unrelated_page_and_canonical(self):
        content = html() + b'<link rel="canonical" href="https://www.wsj.com/articles/other-1504272455">'
        self.assertEqual(wsj.extract_html(content, URL)["status"], "identity_mismatch")
        self.assertEqual(wsj.extract_html(html(mainEntityOfPage={"@id": "https://www.wsj.com/"}), URL)["status"], "identity_mismatch")

    def test_archive_rewritten_canonical_is_original_article(self):
        content = html() + ('<link rel="canonical" href="https://web.archive.org/web/20140702000000/' + URL + '">').encode()
        result = wsj.extract_html(content, URL)
        self.assertEqual(result["status"], "candidate_unverified")
        self.assertEqual(result["canonical_url"], URL)

    def test_historic_paid_metadata_and_publication(self):
        content = html() + b'<meta name="article.access" content="paid">'
        self.assertEqual(wsj.extract_html(content, URL)["status"], "restricted_content")
        content = ('<html><head><meta name="article.published" content="2014-07-02T03:40:00.000Z">'
                   '<meta name="article.access" content="free"></head><body>'
                   '<article itemprop="articleBody"><p>' + TEXT + '</p></article></body></html>').encode()
        result = wsj.extract_html(content, URL)
        self.assertEqual(result["status"], "candidate_unverified")
        self.assertEqual(result["published_at_utc"], "2014-07-02T03:40:00+00:00")
        self.assertEqual(result["publication_date_source"], "meta")

    def test_no_arbitrary_homepage_text(self):
        content = ("<html><body><p>" + TEXT + "</p></body></html>").encode()
        self.assertEqual(wsj.extract_html(content, URL)["status"], "no_body")

    def test_wayback_snapshot_identity(self):
        snapshot = {"available": True, "status": "200", "url": "http://web.archive.org/web/20140702000000/" + URL}
        replay, stamp = wsj.validate_snapshot(snapshot, URL)
        self.assertTrue(replay.startswith("https://"))
        self.assertEqual(stamp, "20140702000000")
        with self.assertRaises(ValueError):
            wsj.validate_snapshot(snapshot, URL.replace("1404272455", "1504272455"))

    def test_scope_and_legacy_identity(self):
        self.assertEqual(wsj.identity(URL.replace("www", "online")), wsj.identity(URL))
        self.assertTrue(wsj.same_article(URL, URL.replace("example-story", "new-slug")))
        for url in ("", "https://other.com/story", "https://user:password@www.wsj.com/a", "http://localhost/a"):
            with self.assertRaises(ValueError):
                wsj.normalize_url(url)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.csv = self.root / "input.csv"
        self.output = self.root / "output"
        self.rows = [dict(date="01/07/2014", headlines="Example story", desk="Politics", url=URL)]
        self.write_csv()
        self.config = wsj.Config(delay=0, retries=0, wayback=False)

    def write_csv(self):
        with self.csv.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["date", "headlines", "desk", "url"])
            writer.writeheader()
            writer.writerows(self.rows)

    def run_with(self, responder, **kwargs):
        with patch.object(requests.Session, "get", side_effect=responder) as mocked:
            summary = wsj.run_stage(self.csv, self.output, "2014-07-01", "day", self.config, **kwargs)
        return summary, mocked

    def allowed(self, url, **kwargs):
        return FakeResponse(body=b"User-agent: *\nAllow: /\n", **{"Content-Type": "text/plain"}) if url.endswith("robots.txt") else FakeResponse(body=html())

    def test_dates_and_nested_periods(self):
        self.rows += [dict(date="07/07/2014", headlines="B", desk="Sports", url=URL + "b"),
                      dict(date="08/07/2014", headlines="C", desk="Sports", url=URL + "c")]
        self.write_csv()
        frame = wsj.load_input(self.csv)
        plan = wsj.period_plan(frame, "2014-07-01")
        self.assertEqual(list(plan.csv_rows), [1, 2, 3, 3])
        self.assertEqual(plan.iloc[2].end_exclusive, "2014-08-01")
        self.assertEqual(plan.iloc[3].end_exclusive, "2015-07-01")
        self.assertEqual(str(frame.iloc[0].csv_date.date()), "2014-07-01")

    def test_leap_year_window(self):
        frame = wsj.load_input(self.csv)
        _, end = wsj.select_period(frame, "2020-02-29", "year")
        self.assertEqual(str(end.date()), "2021-02-28")

    def test_duplicate_rows_preserved_and_resume_no_requests(self):
        self.rows *= 2
        self.write_csv()
        original = self.csv.read_bytes()
        summary, mocked = self.run_with(self.allowed)
        self.assertEqual(summary["candidate_articles"], 1)
        self.assertEqual(summary["csv_rows"], 2)
        self.assertEqual(mocked.call_count, 2)
        result = wsj.pd.read_csv(Path(summary["run_dir"]) / "all_rows.csv")
        self.assertEqual(len(result), 2)
        self.assertEqual(list(result.source_row), [2, 3])
        summary2, mocked2 = self.run_with(AssertionError("No debe acceder a red"))
        self.assertEqual(mocked2.call_count, 0)
        self.assertEqual(summary2["cached_articles"], 1)
        self.assertEqual(self.csv.read_bytes(), original)

    def test_disallowed_is_distinct_and_article_not_requested(self):
        summary, mocked = self.run_with(lambda *a, **kw: FakeResponse(body=b"User-agent: *\nDisallow: /\n"))
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(summary["status_counts_unique_articles"], {"robots_disallowed": 1})

    def test_invalid_robots_not_mislabeled_as_disallowed(self):
        summary, mocked = self.run_with(lambda *a, **kw: FakeResponse(body=b"<html>error</html>"))
        self.assertEqual(mocked.call_count, 1)
        self.assertIn("robots_invalid", summary["status_counts_unique_articles"])

    def test_missing_robots_allows_ordinary_fetch(self):
        summary, mocked = self.run_with(lambda url, **kw: FakeResponse(404) if url.endswith("robots.txt") else FakeResponse(body=html()))
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(summary["candidate_articles"], 1)

    def test_denial_no_alternate_domain_or_browser(self):
        self.config.browser = True
        self.rows[0]["url"] = URL.replace("www", "online")
        self.write_csv()
        def denied(url, **kwargs):
            return self.allowed(url) if url.endswith("robots.txt") else FakeResponse(403)
        with patch.object(wsj.Fetcher, "render", side_effect=AssertionError("No renderer after denial")) as render:
            summary, mocked = self.run_with(denied)
        self.assertEqual(mocked.call_count, 2)
        self.assertFalse(render.called)
        self.assertIn("access_denied", summary["status_counts_unique_articles"])

    def test_challenge_is_not_account_authentication(self):
        def denied(url, **kwargs):
            return self.allowed(url) if url.endswith("robots.txt") else FakeResponse(401, body=b'<script src="https://captcha-delivery.com/test"></script>')
        summary, _ = self.run_with(denied)
        self.assertIn("access_challenge", summary["status_counts_unique_articles"])

    def test_legacy_not_found_can_use_modern_domain(self):
        self.rows[0]["url"] = URL.replace("www", "online")
        self.write_csv()
        def legacy(url, **kwargs):
            if url.endswith("robots.txt"):
                return self.allowed(url)
            return FakeResponse(404) if "online.wsj.com" in url else FakeResponse(body=html())
        summary, mocked = self.run_with(legacy)
        self.assertEqual(mocked.call_count, 4)
        self.assertEqual(summary["candidate_articles"], 1)

    def test_robots_tls_error_retains_reason(self):
        summary, mocked = self.run_with(requests.exceptions.SSLError("synthetic TLS failure"))
        self.assertIn("robots_tls_error", summary["status_counts_unique_articles"])
        self.assertEqual(mocked.call_count, 1)

    def test_request_budget_includes_robots_and_pending_row(self):
        self.config.max_requests = 1
        summary, mocked = self.run_with(self.allowed)
        self.assertTrue(summary["request_budget_exhausted"])
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(summary["pending_articles"], 1)
        self.assertEqual(summary["resolved_articles"], 0)

    def test_long_retry_after_survives_invocation(self):
        self.config.retries = 1
        def limited(url, **kwargs):
            return self.allowed(url) if url.endswith("robots.txt") else FakeResponse(429, **{"Retry-After": "3600"})
        summary, mocked = self.run_with(limited)
        self.assertEqual(mocked.call_count, 2)
        state = json.loads((self.output / "checkpoint.json").read_text())
        self.assertGreater(state["host_next_request"]["www.wsj.com"], wsj.time.time() + 3500)
        self.assertIn("retry_after_deferred", summary["status_counts_unique_articles"])

    def test_redirect_outside_scope_is_never_requested(self):
        def redirected(url, **kwargs):
            return self.allowed(url) if url.endswith("robots.txt") else FakeResponse(302, Location="https://example.org/")
        summary, mocked = self.run_with(redirected)
        self.assertEqual(mocked.call_count, 2)
        self.assertIn("redirect_outside_scope", summary["status_counts_unique_articles"])

    def test_redirect_to_different_story_not_attached(self):
        def redirected(url, **kwargs):
            if url.endswith("robots.txt"):
                return self.allowed(url)
            return FakeResponse(302, Location="https://www.wsj.com/articles/other-1504272455") if url == URL else FakeResponse(body=html())
        summary, mocked = self.run_with(redirected)
        self.assertEqual(mocked.call_count, 3)
        self.assertIn("identity_mismatch", summary["status_counts_unique_articles"])

    def test_retry_failure_preserves_previous_run(self):
        summary, _ = self.run_with(lambda url, **kw: self.allowed(url) if url.endswith("robots.txt") else FakeResponse(403))
        original = Path(summary["run_dir"]) / "summary.json"
        original_bytes = original.read_bytes()
        retried, _ = self.run_with(self.allowed, retry_failed=True)
        self.assertEqual(retried["candidate_articles"], 1)
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertEqual(len(list((self.output / "documents").glob("*/*.json"))), 2)

    def test_wayback_after_direct_restriction(self):
        self.config.wayback = True
        replay = "https://web.archive.org/web/20140702000000/" + URL
        def archived(url, **kwargs):
            if url.endswith("robots.txt"):
                return self.allowed(url)
            if url == URL:
                return FakeResponse(body=html(isAccessibleForFree=False))
            if "wayback/available?" in url:
                return FakeResponse(body=json.dumps({"archived_snapshots": {"closest": {
                    "available": True, "url": replay, "status": "200"}}}).encode())
            if url == replay:
                return FakeResponse(body=html())
            raise AssertionError(url)
        summary, mocked = self.run_with(archived)
        self.assertEqual(summary["candidate_articles"], 1)
        self.assertEqual(mocked.call_count, 6)
        export = wsj.pd.read_csv(Path(summary["run_dir"]) / "all_rows.csv", dtype=str)
        self.assertEqual(export.iloc[0].acquisition_platform, "internet_archive_wayback")
        self.assertEqual(export.iloc[0].capture_timestamp, "20140702000000")

    def test_local_authorized_html_requires_no_network(self):
        local = self.root / "local"
        local.mkdir()
        self.config.local_html = str(local)
        article_id = wsj.load_input(self.csv).iloc[0].article_id
        (local / (article_id + ".html")).write_bytes(html())
        summary, mocked = self.run_with(AssertionError("No debe acceder a red"))
        self.assertFalse(mocked.called)
        self.assertEqual(summary["candidate_articles"], 1)

    def test_invalid_url_exported_without_network(self):
        self.rows[0]["url"] = ""
        self.write_csv()
        summary, mocked = self.run_with(AssertionError("No debe acceder a red"))
        self.assertFalse(mocked.called)
        self.assertIn("invalid_url", summary["status_counts_unique_articles"])

    def test_empty_period_has_readable_exports(self):
        self.rows[0]["date"] = "02/07/2014"
        self.write_csv()
        summary, mocked = self.run_with(AssertionError("No debe acceder a red"))
        self.assertEqual(summary["csv_rows"], 0)
        self.assertFalse(mocked.called)
        self.assertTrue(wsj.pd.read_csv(Path(summary["run_dir"]) / "all_rows.csv").empty)


if __name__ == "__main__":
    unittest.main()
