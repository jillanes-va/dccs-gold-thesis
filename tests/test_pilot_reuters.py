"""Offline Reuters-focused characterization and defect reproduction.

Run: uv run --offline --no-sync python -m unittest discover -s tests -v
All HTML is synthetic. expectedFailure identifies an unresolved defect, not a fix.
"""

import argparse
import contextlib
import csv
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from src import pilot


HOME = "https://www.reuters.com"
URL = HOME + "/business/synthetic-economy-story-2026-04-15/"
SEEDS = pilot.SOURCES["reuters"]["seeds"]
PATTERNS = pilot.SOURCES["reuters"]["patterns"]
HOST = "www.reuters.com"
SESSION_REQUEST = requests.Session.request
TEXT = " ".join([
    "The central bank published its quarterly economic assessment on Wednesday. "
    "Officials discussed inflation, employment and trade with representatives from several industries.",
    "Manufacturers reported that energy costs had stabilised during the previous quarter. "
    "However, shipping delays continued to affect production schedules across the region.",
    "Household spending increased gradually as wage growth supported demand for services. "
    "Retailers said customers were comparing prices more carefully before making large purchases.",
    "Analysts cautioned that the preliminary figures could be revised when additional information became available. "
    "They recommended examining several months of observations before drawing conclusions about the outlook.",
    "The finance ministry will publish detailed national accounts next month. "
    "Those statistics are expected to provide further information about investment, exports and public expenditure.",
    "Independent researchers emphasised that changes in commodity markets have multiple possible explanations. "
    "This fictional article is a software test fixture and makes no claim about actual economic events.",
])


def article_html(published="2026-04-15T12:30:00Z", body=TEXT, **overrides):
    node = {"@type": "NewsArticle", "headline": "Synthetic economic outlook",
            "datePublished": published, "author": [{"@type": "Person", "name": "Test Writer"}],
            "publisher": {"@type": "Organization", "name": "Reuters"}}
    node.update(overrides)
    return ('<html lang="en"><head><title>Synthetic economic outlook</title>'
            '<script type="application/ld+json">' + json.dumps(node) + '</script></head>'
            '<body><main><article><h1>Synthetic economic outlook</h1><p>' + body +
            '</p></article></main></body></html>')


def response(url=URL, code=200, body="<html>ok</html>", content_type="text/html"):
    r = requests.Response()
    r.status_code = code
    r.url = url
    r._content = body.encode("utf-8")
    r.encoding = "utf-8"
    r.headers["Content-Type"] = content_type
    r.request = requests.Request("GET", url).prepare()
    return r


class OfflineCase(unittest.TestCase):
    def setUp(self):
        # Any unexpected real network access is a test failure.
        guard = patch.object(requests.Session, "request", side_effect=AssertionError("Network forbidden in offline tests"))
        guard.start()
        self.addCleanup(guard.stop)


class URLTests(OfflineCase):
    def test_same_host_relative_links(self):
        self.assertEqual(pilot.article_links('<a href="/business/story/">a</a>', SEEDS[0], PATTERNS, HOST), [HOME + "/business/story"])

    def test_foreign_host_excluded(self):
        self.assertEqual(pilot.article_links('<a href="https://example.org/business/story/">a</a>', SEEDS[0], PATTERNS, HOST), [])

    def test_duplicate_links_and_queries_collapse(self):
        html = '<a href="/business/story/?utm=a">a</a><a href="/business/story/#x">b</a>'
        self.assertEqual(pilot.article_links(html, SEEDS[0], PATTERNS, HOST), [HOME + "/business/story"])

    def test_discovery_page_excluded(self):
        self.assertEqual(pilot.article_links('<a href="/business/">a</a>', SEEDS[0], PATTERNS, HOST), [])

    def test_link_order_is_stable(self):
        html = ''.join(f'<a href="/business/{n}/">x</a>' for n in [3, 1, 3, 2])
        self.assertEqual(pilot.article_links(html, SEEDS[0], PATTERNS, HOST), [HOME + f"/business/{n}" for n in [3, 1, 2]])

    def test_non_article_path_excluded(self):
        self.assertEqual(pilot.article_links('<a href="/account/sign-in/">a</a>', SEEDS[0], PATTERNS, HOST), [])

    def test_missing_href_ignored(self):
        self.assertEqual(pilot.article_links('<a>no URL</a>', SEEDS[0], PATTERNS, HOST), [])

    def test_non_http_links_ignored(self):
        self.assertEqual(pilot.article_links('<a href="mailto:reporter@example.org">a</a>', SEEDS[0], PATTERNS, HOST), [])


class MetadataTests(OfflineCase):
    def test_jsonld_graph(self):
        soup = pilot.BeautifulSoup('<script type="application/ld+json">{"@graph":[{"@type":"NewsArticle","headline":"x"}]}</script>', "html.parser")
        self.assertTrue(any(n.get("headline") == "x" for n in pilot.jsonld_nodes(soup)))

    def test_jsonld_array(self):
        soup = pilot.BeautifulSoup('<script type="application/ld+json">[{"@type":"NewsArticle"}]</script>', "html.parser")
        self.assertEqual(list(pilot.jsonld_nodes(soup))[0]["@type"], "NewsArticle")

    def test_invalid_jsonld_is_ignored(self):
        soup = pilot.BeautifulSoup('<script type="application/ld+json">not-json</script>', "html.parser")
        self.assertEqual(list(pilot.jsonld_nodes(soup)), [])

    def test_meta_property(self):
        soup = pilot.BeautifulSoup('<meta property="og:title" content=" Title ">', "html.parser")
        self.assertEqual(pilot.get_meta(soup, "og:title"), "Title")

    def test_meta_name(self):
        soup = pilot.BeautifulSoup('<meta name="pubdate" content="2026-01-15">', "html.parser")
        self.assertEqual(pilot.get_meta(soup, "pubdate"), "2026-01-15")

    def test_meta_missing(self):
        self.assertEqual(pilot.get_meta(pilot.BeautifulSoup("", "html.parser"), "og:title"), "")

    def test_real_extractor_synthetic_article(self):
        data = pilot.extract(article_html(), URL)
        self.assertEqual(data["title"], "Synthetic economic outlook")
        self.assertEqual(data["publisher"], "Reuters")
        self.assertEqual(data["author"], "Test Writer")
        self.assertEqual(data["published_at"], "2026-04-15T12:30:00+00:00")
        self.assertEqual(data["language"], "en")
        self.assertGreaterEqual(data["word_count"], 100)
        self.assertIn("quarterly economic assessment", data["text"])

    def test_author_dictionary(self):
        self.assertEqual(pilot.extract(article_html(author={"name": "Writer"}), URL)["author"], "Writer")

    def test_author_list(self):
        self.assertEqual(pilot.extract(article_html(author=[{"name": "A"}, {"name": "B"}]), URL)["author"], "A, B")

    def test_missing_publisher_remains_explicit(self):
        self.assertEqual(pilot.extract(article_html(publisher=""), URL)["publisher"], "")

    def test_empty_page(self):
        with patch.object(pilot.trafilatura, "extract_metadata", return_value=None), patch.object(pilot.trafilatura, "extract", return_value=None):
            data = pilot.extract("<html></html>", URL)
        self.assertEqual(data["word_count"], 0)
        self.assertEqual(data["published_at"], "")

    def test_meta_title_and_date_fallback(self):
        html = '<html><head><meta property="og:title" content="Fallback"><meta property="article:published_time" content="2026-03-01T08:00:00Z"></head></html>'
        with patch.object(pilot.trafilatura, "extract_metadata", return_value=None):
            data = pilot.extract(html, URL)
        self.assertEqual(data["title"], "Fallback")
        self.assertEqual(data["published_at"], "2026-03-01T08:00:00+00:00")


class FetcherTests(OfflineCase):
    def test_robots_cached_per_origin(self):
        fetcher = pilot.Fetcher(0, 20)
        with patch.object(fetcher.session, "get", return_value=response(HOME + "/robots.txt", body="User-agent: *\nAllow: /")) as get:
            self.assertTrue(fetcher.permitted(SEEDS[0]))
            self.assertTrue(fetcher.permitted(SEEDS[1]))
            get.assert_called_once_with(HOME + "/robots.txt", timeout=20)

    def test_current_reuters_wildcard_denial(self):
        body = "User-agent: Googlebot\nDisallow: /search\n\nUser-agent: *\nAllow: /plus/\nDisallow: /"
        fetcher = pilot.Fetcher(0, 20)
        with patch.object(fetcher.session, "get", return_value=response(HOME + "/robots.txt", body=body)) as get:
            self.assertFalse(fetcher.permitted(SEEDS[0]))
            self.assertFalse(fetcher.permitted(SEEDS[1]))
            self.assertEqual(get.call_count, 1)

    def test_disallowed_never_requests_page(self):
        fetcher = pilot.Fetcher(0, 20)
        with patch.object(fetcher, "permitted", return_value=False), patch.object(fetcher.session, "get") as get:
            self.assertEqual(fetcher.get(URL), (None, "robots_disallowed_or_unavailable", None))
            get.assert_not_called()

    def test_non_http_url_rejected(self):
        fetcher = pilot.Fetcher(0, 20)
        with patch.object(fetcher.session, "get") as get:
            self.assertFalse(fetcher.permitted("file:///tmp/article"))
            get.assert_not_called()

    def test_positive_delay_is_applied(self):
        fetcher = pilot.Fetcher(3, 20)
        fetcher.last[HOST] = 100
        with patch.object(fetcher, "permitted", return_value=True), patch.object(fetcher.session, "get", return_value=response()), patch.object(pilot.time, "monotonic", return_value=101), patch.object(pilot.time, "sleep") as sleep:
            fetcher.get(URL)
        sleep.assert_called_once_with(2)

    def test_elapsed_delay_does_not_sleep(self):
        fetcher = pilot.Fetcher(3, 20)
        fetcher.last[HOST] = 100
        with patch.object(fetcher, "permitted", return_value=True), patch.object(fetcher.session, "get", return_value=response()), patch.object(pilot.time, "monotonic", return_value=104), patch.object(pilot.time, "sleep") as sleep:
            fetcher.get(URL)
        sleep.assert_not_called()

    def test_redirect_allowed(self):
        fetcher = pilot.Fetcher(0, 20)
        target = HOME + "/world/redirected"
        with patch.object(fetcher, "permitted", return_value=True) as allowed, patch.object(fetcher.session, "get", return_value=response(target)):
            self.assertEqual(fetcher.get(URL), ("<html>ok</html>", "ok", 200))
        self.assertEqual(allowed.call_count, 2)

    def test_redirect_disallowed_body_not_processed(self):
        fetcher = pilot.Fetcher(0, 20)
        with patch.object(fetcher, "permitted", side_effect=[True, False]), patch.object(fetcher.session, "get", return_value=response(HOME + "/private/")):
            self.assertEqual(fetcher.get(URL), (None, "redirect_robots_disallowed", 200))

    def test_user_agent_is_identifiable(self):
        self.assertEqual(pilot.Fetcher(0, 20).session.headers["User-Agent"], pilot.AGENT)
        self.assertIn("AcademicNewsPilot", pilot.AGENT)


class PipelineTests(OfflineCase):
    def execute(self, get, max_articles=60, extractor=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name)
        args = argparse.Namespace(sources=["reuters"], max_per_source=max_articles,
                                  min_words=100, delay=0, timeout=20, output=str(out))
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(pilot.Fetcher, "get", side_effect=get))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            if extractor is not None:
                stack.enter_context(patch.object(pilot, "extract", side_effect=extractor))
            pilot.run(args)
        with (out / "attempts.csv").open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        records = [json.loads(line) for line in (out / "articles.jsonl").read_text(encoding="utf-8").splitlines()]
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        return rows, records, summary

    def test_both_discovery_failures_create_audit_and_no_articles(self):
        rows, records, summary = self.execute(lambda url: (None, "robots_disallowed_or_unavailable", None))
        self.assertEqual(len(rows), 2)
        self.assertEqual(records, [])
        self.assertEqual(summary, {"reuters": {"discovery_robots_disallowed_or_unavailable": 2}})
        self.assertTrue(all(row["http_status"] == "" for row in rows))

    def test_sixty_candidates_mixed_outcomes_real_extractor(self):
        urls = [HOME + f"/business/synthetic-{i}-2026-04-15" for i in range(60)]
        # First seed: 30 unique. Second: 10 repeated plus 30 new.
        indexes = {SEEDS[0]: range(30), SEEDS[1]: range(20, 60)}
        fetched = []

        def get(url):
            fetched.append(url)
            if url in indexes:
                return ''.join(f'<a href="{urls[i]}">Synthetic {i}</a>' for i in indexes[url]), "ok", 200
            i = urls.index(url)
            group = i % 10
            if group == 0:
                return None, "blocked_or_rate_limited", 403
            if group == 1:
                return None, "blocked_or_rate_limited", 429
            if group == 2:
                return None, "request_error:Timeout", None
            if group == 3:
                return None, "http_error", 404
            if group == 4:
                return article_html(published="2026-10-21T10:00:00Z"), "ok", 200
            if group == 5:
                return article_html(body="A very short synthetic article."), "ok", 200
            if group == 6:
                return article_html(), "ok", 200
            if group == 7:
                return "BROKEN_FIXTURE", "ok", 200
            if group == 8:
                return None, "not_html", 200
            return "NO_DATE_FIXTURE", "ok", 200

        actual_extract = pilot.extract

        def extract(html, url):
            if html == "BROKEN_FIXTURE":
                raise ValueError("Deliberate synthetic extraction failure")
            if html == "NO_DATE_FIXTURE":
                return dict(published_at="", title="Synthetic", author="", publisher="", language="en", word_count=150, text=TEXT)
            return actual_extract(html, url)

        rows, records, summary = self.execute(get, extractor=extract)
        expected = {"discovery_ok": 2, "blocked_or_rate_limited": 12,
                    "request_error:Timeout": 6, "http_error": 6, "outside_period": 6,
                    "short_or_empty": 6, "success": 6, "extraction_error": 6,
                    "not_html": 6, "missing_date": 6}
        self.assertEqual(summary, {"reuters": expected})
        self.assertEqual(len(rows), 62)
        self.assertEqual(len(fetched), 62)
        self.assertEqual(len(set(fetched)), 62)
        self.assertEqual(len(records), 6)
        self.assertEqual(sum(summary["reuters"].values()), len(rows))
        self.assertTrue(all(row["platform"] == "reuters" for row in rows))
        self.assertEqual(len([row for row in rows if row["error"]]), 6)
        for record in records:
            self.assertEqual(record["result"], "success")
            self.assertEqual(record["text_sha256"], hashlib.sha256(record["text"].encode()).hexdigest())
            self.assertGreaterEqual(record["word_count"], 100)

    def test_limit_is_attempts_not_successes(self):
        fetched = []
        def get(url):
            fetched.append(url)
            if url in SEEDS:
                return '<a href="/business/a">a</a><a href="/business/b">b</a>', "ok", 200
            return None, "http_error", 404
        rows, records, _ = self.execute(get, max_articles=1)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(fetched), 2)
        self.assertEqual(records, [])

    def test_empty_discovery_is_not_an_article_success(self):
        rows, records, summary = self.execute(lambda url: ("<html>No links</html>", "ok", 200))
        self.assertEqual(len(rows), 2)
        self.assertEqual(records, [])
        self.assertEqual(summary["reuters"], {"discovery_ok": 2})

    def test_csv_quotes_multiline_unicode(self):
        text = 'Texto sintético, con "comillas"\ny una segunda línea.'
        def get(url):
            return ('<a href="/business/a">a</a>', "ok", 200) if url in SEEDS else ("fixture", "ok", 200)
        def extract(html, url):
            return dict(published_at="2026-04-15", title="Título", author="", publisher="Reuters", language="es", word_count=101, text=text)
        rows, records, _ = self.execute(get, max_articles=1, extractor=extract)
        self.assertEqual(rows[1]["text"], text)
        self.assertEqual(records[0]["text"], text)
        self.assertEqual(records[0]["title"], "Título")

    def test_all_layers_with_mock_http_and_real_extraction(self):
        # Only transport is simulated: use actual robots parsing, discovery,
        # HTTP classification, extraction, filtering, CSV, JSONL, and summary.
        def get(session, url, **kwargs):
            if url.endswith("/robots.txt"):
                return response(url, body="User-agent: *\nAllow: /", content_type="text/plain")
            if url in SEEDS:
                return response(url, body=f'<a href="{URL}">Synthetic</a>')
            return response(url, body=article_html())
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        args = argparse.Namespace(sources=["reuters"], max_per_source=1, min_words=100,
                                  delay=0, timeout=20, output=tmp.name)
        with patch.object(requests.Session, "get", autospec=True, side_effect=get) as http, contextlib.redirect_stdout(io.StringIO()):
            pilot.run(args)
        self.assertEqual(http.call_count, 3)
        records = [json.loads(line) for line in (Path(tmp.name) / "articles.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["publisher"], "Reuters")


class KnownDefects(OfflineCase):
    """Desired guarantees that the current pilot demonstrably does not meet."""

    @unittest.expectedFailure
    def test_robots_network_error_has_a_distinct_result(self):
        fetcher = pilot.Fetcher(0, 20)
        with patch.object(fetcher.session, "get", side_effect=requests.exceptions.SSLError("synthetic certificate error")):
            self.assertEqual(fetcher.get(URL)[1], "robots_request_error:SSLError")

    @unittest.expectedFailure
    def test_html_challenge_is_not_accepted_as_robots(self):
        fetcher = pilot.Fetcher(0, 20)
        with patch.object(fetcher.session, "get", return_value=response(HOME + "/robots.txt", body="<html>Please sign in</html>")):
            self.assertFalse(fetcher.permitted(URL))

    @unittest.expectedFailure
    def test_section_pages_are_not_discovered_as_articles(self):
        html = '<a href="/business/finance/">Finance</a><a href="/markets/commodities/">Commodities</a>'
        self.assertEqual(pilot.article_links(html, SEEDS[0], PATTERNS, HOST), [])

    @unittest.expectedFailure
    def test_rate_limit_has_a_distinct_result(self):
        fetcher = pilot.Fetcher(0, 20)
        with patch.object(fetcher, "permitted", return_value=True), patch.object(fetcher.session, "get", return_value=response(code=429)):
            self.assertEqual(fetcher.get(URL)[1], "rate_limited")

    @unittest.expectedFailure
    def test_redirect_permission_checked_before_target_download(self):
        # requests follows redirects inside session.get, before permitted(target).
        fetcher = pilot.Fetcher(0, 20)
        target = "https://private.example.test/restricted"
        events = []
        def send(request, **kwargs):
            events.append(("download", request.url))
            if request.url == URL:
                r = response(URL, 302)
                r.headers["Location"] = target
                return r
            return response(target)
        def permitted(url):
            events.append(("permission", url))
            return url == URL
        # Restore request handling for this instance only; the transport adapter
        # remains mocked, so requests can simulate following a redirect offline.
        with patch.object(fetcher.session, "request", wraps=SESSION_REQUEST.__get__(fetcher.session)), patch.object(fetcher, "permitted", side_effect=permitted), patch.object(fetcher.session.get_adapter(URL), "send", side_effect=send):
            fetcher.get(URL)
        self.assertNotIn(("download", target), events)

    @unittest.expectedFailure
    def test_robots_request_obeys_spacing_before_seed_request(self):
        fetcher = pilot.Fetcher(3, 20)
        events = []
        def get(url, **kwargs):
            events.append(url)
            return response(url, body="User-agent: *\nAllow: /" if url.endswith("robots.txt") else "<html></html>")
        with patch.object(fetcher.session, "get", side_effect=get), patch.object(pilot.time, "monotonic", return_value=100), patch.object(pilot.time, "sleep") as sleep:
            fetcher.get(URL)
        self.assertEqual(len(events), 2)
        sleep.assert_called_once_with(3)

    @unittest.expectedFailure
    def test_attempts_include_retrieval_timestamp(self):
        self.assertIn("fetched_at_utc", pilot.FIELDS)


def add_cases(cls, prefix, cases, check):
    """Give each table entry an individual unittest result (not hidden subtests)."""
    for name, value, expected in cases:
        def test(self, value=value, expected=expected):
            check(self, value, expected)
        setattr(cls, f"test_{prefix}_{name}", test)


class DateTests(OfflineCase):
    pass


add_cases(DateTests, "period", [
    ("start_inclusive", "2026-01-01T00:00:00Z", True),
    ("end_inclusive", "2026-10-15T23:59:59Z", True),
    ("previous_year", "2025-12-31T23:59:59Z", False),
    ("day_after_end", "2026-10-16T00:00:00Z", False),
    ("execution_day_excluded", "2026-10-21T12:00:00Z", False),
    ("next_year", "2027-01-01", False),
    ("middle", "2026-07-15", True),
    ("offset_preserved_calendar_date", "2026-10-15T23:59:59-07:00", True),
    ("empty", "", False), ("none", None, False),
    ("invalid_day", "2026-02-30", False), ("invalid_text", "not a date", False),
], lambda self, value, expected: self.assertEqual(pilot.within_2026(value), expected))

add_cases(DateTests, "parse", [
    ("utc", "2026-04-15T12:30:00Z", "2026-04-15T12:30:00+00:00"),
    ("offset", "2026-04-15T12:30:00-03:00", "2026-04-15T12:30:00-03:00"),
    ("date_only", "2026-04-15", "2026-04-15T00:00:00"),
    ("empty", "", ""), ("none", None, ""),
    ("invalid", "not a date", ""), ("invalid_calendar", "2026-02-30", ""),
], lambda self, value, expected: self.assertEqual(pilot.parse_date(value), expected))

add_cases(URLTests, "clean", [
    ("fragment", URL + "#heading", URL.rstrip("/")),
    ("query", URL + "?utm_source=test", URL.rstrip("/")),
    ("both", URL + "?x=1#h", URL.rstrip("/")),
    ("plain", URL.rstrip("/"), URL.rstrip("/")),
], lambda self, value, expected: self.assertEqual(pilot.clean_url(value), expected))


def check_fetch_status(self, value, expected):
    code, content_type = value
    fetcher = pilot.Fetcher(0, 20)
    with patch.object(fetcher, "permitted", return_value=True), patch.object(fetcher.session, "get", return_value=response(code=code, content_type=content_type)):
        body, status, actual_code = fetcher.get(URL)
    self.assertEqual((status, actual_code), (expected, code))
    self.assertEqual(body is not None, expected == "ok")


add_cases(FetcherTests, "status", [
    ("html", (200, "text/html; charset=utf-8"), "ok"),
    ("xhtml", (200, "application/xhtml+xml"), "ok"),
    ("json", (200, "application/json"), "not_html"),
    ("pdf", (200, "application/pdf"), "not_html"),
    ("missing_content_type", (200, ""), "not_html"),
    ("unauthorized", (401, "text/html"), "blocked_or_rate_limited"),
    ("forbidden", (403, "text/html"), "blocked_or_rate_limited"),
    ("rate_limit", (429, "text/html"), "blocked_or_rate_limited"),
    ("not_found", (404, "text/html"), "http_error"),
    ("server_error", (500, "text/html"), "http_error"),
    ("unavailable", (503, "text/html"), "http_error"),
], check_fetch_status)


def check_request_error(self, exception, expected):
    fetcher = pilot.Fetcher(0, 20)
    with patch.object(fetcher, "permitted", return_value=True), patch.object(fetcher.session, "get", side_effect=exception("Synthetic transport error")):
        self.assertEqual(fetcher.get(URL), (None, expected, None))


add_cases(FetcherTests, "exception", [
    ("timeout", requests.exceptions.Timeout, "request_error:Timeout"),
    ("connection", requests.exceptions.ConnectionError, "request_error:ConnectionError"),
    ("ssl", requests.exceptions.SSLError, "request_error:SSLError"),
    ("redirect_loop", requests.exceptions.TooManyRedirects, "request_error:TooManyRedirects"),
], check_request_error)


def check_robots_http(self, code, expected):
    fetcher = pilot.Fetcher(0, 20)
    with patch.object(fetcher.session, "get", return_value=response(HOME + "/robots.txt", code, "User-agent: *\nAllow: /")) as get:
        self.assertEqual(fetcher.permitted(URL), expected)
        self.assertEqual(fetcher.permitted(SEEDS[1]), expected)
    self.assertEqual(get.call_count, 1)


add_cases(FetcherTests, "robots_http", [
    ("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False),
    ("not_found", 404, False), ("rate_limit", 429, False), ("unavailable", 503, False),
], check_robots_http)


if __name__ == "__main__":
    unittest.main(verbosity=2)
