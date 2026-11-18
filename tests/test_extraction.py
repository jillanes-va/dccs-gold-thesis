"""Pruebas sin internet del scraper nuevo; HTML y respuestas sintéticos."""

import contextlib
import io
import importlib.util
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

import requests

from src import extraction as ex


HOME = "https://www.reuters.com"
URL = HOME + "/world/synthetic-report-2026-04-15/"
BODY = " ".join([
    "This synthetic report describes changes in the economy, trade and public investment.",
    "Researchers collected observations from different regions to compare developments over several months.",
    "The fictional central bank released a detailed assessment of employment, inflation and household spending.",
    "Several manufacturers reported higher production costs while service companies announced additional investment plans.",
    "Analysts cautioned that preliminary figures could change once the statistical office received further information.",
    "Officials said that the next quarterly report would contain additional details about exports and business activity.",
    "Economists recommended studying multiple observations before drawing conclusions about any particular policy decision.",
    "All names, claims and events in this fixture are invented for testing software without downloading copyrighted news.",
])


def html(**values):
    article = {"@type": "NewsArticle", "headline": "Synthetic report",
               "articleBody": BODY, "datePublished": "2026-04-15T12:00:00Z",
               "author": {"name": "Test Reporter"}, "publisher": {"name": "Reuters"}}
    article.update(values)
    return ('<html lang="en"><head><title>Synthetic report</title>'
            f'<link rel="canonical" href="{URL}"><script type="application/ld+json">' +
            json.dumps(article) + '</script></head><body><article><p>' + BODY +
            '</p></article></body></html>').encode()


def response(url, status=200, content=b"<html>ok</html>", **headers):
    result = requests.Response()
    result.url = url
    result.status_code = status
    result._content = content
    result._content_consumed = True
    result.headers.update({"Content-Type": "text/html", **headers})
    return result


def args(output=None, *extra):
    argv = ["--delay", "0", "--retries", "0", "--tls-trust", "requests", "--robots-policy", "enforce", *extra]
    if output is not None:
        argv.extend(["--output", str(output)])
    return ex.build_parser().parse_args(argv)


class OfflineCase(unittest.TestCase):
    def setUp(self):
        guard = patch.object(requests.Session, "request", side_effect=AssertionError("Unexpected network access"))
        guard.start()
        self.addCleanup(guard.stop)


class DiscoveryTests(OfflineCase):
    def test_normalization_preserves_meaningful_queries(self):
        self.assertEqual(ex.normalize_url(URL + "?outputType=xml&utm_source=test#top"), URL + "?outputType=xml")

    def test_external_hosts_and_unsafe_urls_rejected(self):
        for url in ["https://example.org/x", "file:///tmp/x", "http://www.reuters.com/x", "https://user:password@www.reuters.com/x", "https://www.reuters.com:123/x"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                ex.normalize_url(url)

    def test_html_sections_excluded_and_duplicates_removed(self):
        page = f'<a href="/business/finance/">section</a><a href="{URL}">a</a><a href="{URL}#top">b</a>'.encode()
        self.assertEqual(ex.discover(page, HOME), [("article", URL)])

    def test_sitemap_index(self):
        xml = b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://www.reuters.com/archive.xml?outputType=xml</loc></sitemap></sitemapindex>'
        self.assertEqual(ex.discover(xml, HOME), [("discovery", HOME + "/archive.xml?outputType=xml")])

    def test_sitemap_urlset(self):
        xml = f'<urlset><url><loc>{URL}</loc></url><url><loc>https://outside.test/other</loc></url></urlset>'.encode()
        self.assertEqual(ex.discover(xml, HOME), [("article", URL)])

    def test_rss(self):
        xml = f'<rss><channel><item><link>{URL}</link></item></channel></rss>'.encode()
        self.assertEqual(ex.discover(xml, HOME), [("article", URL)])

    def test_atom(self):
        xml = f'<feed xmlns="http://www.w3.org/2005/Atom"><entry><link href="{URL}"/></entry></feed>'.encode()
        self.assertEqual(ex.discover(xml, HOME), [("article", URL)])

    def test_explicit_url_uses_no_default_seeds(self):
        items = ex.initial_items(args(None, "--url", URL))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["kind"], "article")


class ExtractionTests(OfflineCase):
    def test_jsonld_metadata_and_body(self):
        document, status = ex.extract_document(html(), URL)
        self.assertEqual(status, "parsed")
        self.assertEqual(document["text"], BODY)
        self.assertEqual(document["published_at_utc"], "2026-04-15T12:00:00+00:00")
        self.assertEqual(document["author"], "Test Reporter")
        self.assertEqual(document["canonical_url"], URL)
        self.assertEqual(document["text_sha256"], ex.digest(BODY.encode()))

    def test_trafilatura_fallback_extracts_real_synthetic_html(self):
        document, _ = ex.extract_document(html(articleBody=None), URL)
        self.assertEqual(document["extraction_method"], "trafilatura")
        self.assertIn("fictional central bank", document["text"])

    def test_explicit_restriction_is_not_extracted(self):
        document, status = ex.extract_document(html(isAccessibleForFree=False), URL)
        self.assertIsNone(document)
        self.assertEqual(status, "restricted_content")

    def test_restricted_haspart_is_not_extracted(self):
        _, status = ex.extract_document(html(hasPart={"isAccessibleForFree": False}), URL)
        self.assertEqual(status, "restricted_content")

    def test_challenge_is_not_a_news_article(self):
        _, status = ex.extract_document(b"<html><title>Access denied</title></html>", URL)
        self.assertEqual(status, "access_challenge")

    def test_naive_timestamp_is_not_silently_assigned_utc(self):
        document, _ = ex.extract_document(html(datePublished="2026-04-15T12:00:00"), URL)
        self.assertIsNone(document["published_at_utc"])
        self.assertFalse(document["timezone_known"])

    def test_invalid_date_remains_missing(self):
        document, _ = ex.extract_document(html(datePublished="not a date"), URL)
        self.assertIsNone(document["published_at"])
        self.assertEqual(document["date_source"], "invalid")

    def test_quality_period_preserves_pilot_cutoff(self):
        document, _ = ex.extract_document(html(datePublished="2026-10-21T12:00:00Z"), URL)
        self.assertEqual(ex.quality_status(document, date(2026, 1, 1), date(2026, 10, 15), 100), "outside_period")

    def test_local_canonical_source_is_labeled_inferred(self):
        document, _ = ex.extract_document(html(), None)
        self.assertEqual(document["editorial_source"], "Reuters")
        self.assertEqual(document["source_confidence"], "domain_inferred")


class FetcherTests(OfflineCase):
    def fetcher(self, *extra):
        records = []
        fetcher = ex.Fetcher(args(None, *extra), records.append)
        self.addCleanup(fetcher.session.close)
        return fetcher, records

    def test_tls_error_is_distinct_from_policy(self):
        fetcher, records = self.fetcher()
        with patch.object(fetcher.session, "get", side_effect=requests.exceptions.SSLError("Synthetic TLS failure")):
            self.assertEqual(fetcher.follow(URL).result, "robots_tls_error")
        self.assertEqual(records[0]["result"], "tls_error")

    def test_robots_rule_denies_without_requesting_article(self):
        fetcher, _ = self.fetcher()
        with patch.object(fetcher.session, "get", return_value=response(HOME + "/robots.txt", content=b"User-agent: *\nDisallow: /", **{"Content-Type": "text/plain"})) as get:
            self.assertEqual(fetcher.follow(URL).result, "robots_disallowed")
            self.assertEqual(fetcher.follow(HOME + "/markets/").result, "robots_disallowed")
        self.assertEqual(get.call_count, 1)

    def test_default_policy_observes_robots(self):
        self.assertEqual(ex.build_parser().parse_args([]).robots_policy, "observe")

    def test_observe_policy_requests_article_after_disallow(self):
        fetcher, records = self.fetcher("--robots-policy", "observe")
        responses = [response(HOME + "/robots.txt", content=b"User-agent: *\nDisallow: /", **{"Content-Type": "text/plain"}),
                     response(URL, content=html())]
        with patch.object(fetcher.session, "get", side_effect=responses) as get:
            self.assertEqual(fetcher.follow(URL).result, "ok")
        self.assertEqual(get.call_count, 2)
        decision = next(r for r in records if r["stage"] == "robots_decision")
        self.assertEqual(decision["result"], "robots_disallowed")
        self.assertTrue(decision["continued"])

    def test_observe_policy_does_not_override_http_denial(self):
        fetcher, _ = self.fetcher("--robots-policy", "observe")
        responses = [response(HOME + "/robots.txt", content=b"User-agent: *\nDisallow: /", **{"Content-Type": "text/plain"}),
                     response(URL, 403)]
        with patch.object(fetcher.session, "get", side_effect=responses) as get:
            self.assertEqual(fetcher.follow(URL).result, "access_denied")
        self.assertEqual(get.call_count, 2)

    def test_observe_policy_still_rejects_invalid_robots(self):
        fetcher, _ = self.fetcher("--robots-policy", "observe")
        with patch.object(fetcher.session, "get", return_value=response(HOME + "/robots.txt", content=b"<html>Login</html>")) as get:
            self.assertEqual(fetcher.follow(URL).result, "robots_invalid")
        self.assertEqual(get.call_count, 1)

    def test_datadome_401_is_classified_as_challenge(self):
        fetcher, records = self.fetcher()
        denial = response(URL, 401, content=b'<html><script src="https://geo.captcha-delivery.com/test"></script></html>',
                          **{"x-datadome": "protected"})
        with patch.object(fetcher.session, "get", return_value=denial) as get:
            self.assertEqual(fetcher.request(URL, "article").result, "access_challenge")
        self.assertTrue(records[0]["datadome_challenge"])
        self.assertFalse(records[0]["www_authenticate_present"])
        self.assertEqual(get.call_count, 1)

    def test_normal_authentication_401_is_not_a_datadome_challenge(self):
        fetcher, records = self.fetcher()
        denial = response(URL, 401, **{"WWW-Authenticate": 'Basic realm="Synthetic"'})
        with patch.object(fetcher.session, "get", return_value=denial):
            self.assertEqual(fetcher.request(URL, "article").result, "authentication_required")
        self.assertFalse(records[0]["datadome_challenge"])
        self.assertTrue(records[0]["www_authenticate_present"])

    def test_html_robots_response_does_not_grant_access(self):
        fetcher, _ = self.fetcher()
        with patch.object(fetcher.session, "get", return_value=response(HOME + "/robots.txt", content=b"<html>Login</html>")) as get:
            self.assertEqual(fetcher.follow(URL).result, "robots_invalid")
        self.assertEqual(get.call_count, 1)

    def test_redirect_destination_checked_before_download(self):
        fetcher, _ = self.fetcher()
        target = HOME + "/restricted"
        with patch.object(fetcher, "permitted", side_effect=["allowed", "robots_disallowed"]), patch.object(fetcher.session, "get", return_value=response(URL, 302, Location=target)) as get:
            self.assertEqual(fetcher.follow(URL).result, "robots_disallowed")
        self.assertEqual(get.call_count, 1)

    def test_external_redirect_not_followed(self):
        fetcher, _ = self.fetcher()
        with patch.object(fetcher, "permitted", return_value="allowed"), patch.object(fetcher.session, "get", return_value=response(URL, 302, Location="https://outside.test/x")) as get:
            self.assertEqual(fetcher.follow(URL).result, "redirect_outside_scope")
        self.assertEqual(get.call_count, 1)

    def test_redirect_loop(self):
        fetcher, _ = self.fetcher()
        with patch.object(fetcher, "permitted", return_value="allowed"), patch.object(fetcher.session, "get", return_value=response(URL, 302, Location=URL)):
            self.assertEqual(fetcher.follow(URL).result, "redirect_loop")

    def test_transient_server_error_retried(self):
        fetcher, records = self.fetcher("--retries", "1")
        with patch.object(fetcher.session, "get", side_effect=[response(URL, 503), response(URL)]), patch.object(ex.time, "sleep"):
            self.assertEqual(fetcher.request(URL, "article").result, "ok")
        self.assertEqual([r["http_status"] for r in records], [503, 200])

    def test_long_retry_after_defers_without_early_retry(self):
        fetcher, _ = self.fetcher("--retries", "2")
        with patch.object(fetcher.session, "get", return_value=response(URL, 429, **{"Retry-After": "3600"})) as get, patch.object(ex.time, "sleep") as sleep:
            self.assertEqual(fetcher.request(URL, "article").result, "rate_limited")
        self.assertEqual(get.call_count, 1)
        self.assertTrue(all(call.args[0] < 1 for call in sleep.call_args_list))

    def test_rate_limit_cooldown_applies_to_other_urls_on_same_host(self):
        fetcher, _ = self.fetcher()
        with patch.object(fetcher.session, "get", return_value=response(URL, 429, **{"Retry-After": "3600"})) as get:
            first = fetcher.request(URL, "article")
            second = fetcher.request(HOME + "/world/other-2026-04-15/", "article")
        self.assertIsNotNone(first.retry_at)
        self.assertEqual(second.result, "rate_limit_deferred")
        self.assertEqual(get.call_count, 1)

    def test_retry_after_http_date(self):
        future = format_datetime(datetime.now(timezone.utc) + timedelta(hours=1))
        self.assertGreater(ex.retry_after_seconds(future), 3500)
        self.assertLess(ex.retry_after_seconds(future), 3700)

    def test_all_requests_share_delay_including_robots(self):
        fetcher, _ = self.fetcher("--delay", "3")
        responses = [response(HOME + "/robots.txt", content=b"User-agent: *\nAllow: /", **{"Content-Type": "text/plain"}), response(URL)]
        with patch.object(fetcher.session, "get", side_effect=responses), patch.object(ex.time, "monotonic", return_value=100), patch.object(ex.time, "sleep") as sleep:
            self.assertEqual(fetcher.follow(URL).result, "ok")
        self.assertIn(3, [call.args[0] for call in sleep.call_args_list])

    def test_request_budget_includes_robots(self):
        fetcher, _ = self.fetcher("--max-requests", "1")
        with patch.object(fetcher.session, "get", return_value=response(HOME + "/robots.txt", content=b"User-agent: *\nAllow: /", **{"Content-Type": "text/plain"})) as get:
            self.assertEqual(fetcher.follow(URL).result, "request_budget_exhausted")
        self.assertEqual(get.call_count, 1)

    def test_response_size_limit(self):
        fetcher, _ = self.fetcher()
        with patch.object(fetcher.session, "get", return_value=response(URL, content=b"0123456789")), patch.object(ex, "MAX_BYTES", 5):
            self.assertEqual(fetcher.request(URL, "article").result, "response_too_large")


class BrowserTests(OfflineCase):
    def fetcher(self, *extra):
        records = []
        fetcher = ex.BrowserFetcher(args(None, "--transport", "browser", "--browser-wait", "0", *extra), records.append)
        self.addCleanup(fetcher.close)
        fetcher.context = MagicMock()
        fetcher.page = MagicMock()
        fetcher.page.url = URL
        fetcher.page.title.return_value = "Synthetic report"
        fetcher.page.content.return_value = html().decode()
        fetcher.page.locator.return_value.first.is_visible.return_value = False
        def navigate(*a, **k):
            fetcher.requests_made += 1
            fetcher.last_response = SimpleNamespace(status=200, headers={"content-type": "text/html"})
        fetcher.page.goto.side_effect = navigate
        return fetcher, records

    def test_rendered_dom_is_returned_without_cookie_export(self):
        fetcher, records = self.fetcher()
        result = fetcher.request(URL, "article")
        self.assertEqual(result.result, "ok")
        self.assertEqual(result.content, html())
        self.assertEqual(records[-1]["representation"], "rendered_dom")
        fetcher.context.cookies.assert_not_called()
        fetcher.context.storage_state.assert_not_called()

    def test_visible_challenge_is_not_extracted(self):
        fetcher, _ = self.fetcher()
        def navigate(*a, **k):
            fetcher.last_response = SimpleNamespace(status=401, headers={"x-datadome": "protected"})
            fetcher.page.content.return_value = "<html>captcha-delivery</html>"
        fetcher.page.goto.side_effect = navigate
        result = fetcher.request(URL, "article")
        self.assertEqual(result.result, "access_challenge")
        self.assertEqual(result.content, b"")
        fetcher.page.click.assert_not_called()
        fetcher.page.evaluate.assert_not_called()

    def test_human_can_complete_verification_without_script_interaction(self):
        fetcher, records = self.fetcher("--browser-wait", "10")
        def navigate(*a, **k):
            fetcher.last_response = SimpleNamespace(status=401, headers={"x-datadome": "protected"})
            fetcher.page.content.return_value = "<html>captcha-delivery</html>"
        def wait(milliseconds):
            if milliseconds == 1000:
                fetcher.last_response = SimpleNamespace(status=200, headers={})
                fetcher.page.content.return_value = html().decode()
        fetcher.page.goto.side_effect = navigate
        fetcher.page.wait_for_timeout.side_effect = wait
        result = fetcher.request(URL, "article")
        self.assertEqual(result.result, "ok")
        self.assertTrue(any(r["stage"] == "human_verification_wait" for r in records))
        fetcher.page.click.assert_not_called()
        fetcher.page.evaluate.assert_not_called()

    def test_browser_navigation_stays_in_reuters_scope(self):
        fetcher, _ = self.fetcher()
        route = MagicMock()
        route.request.url = "https://outside.test/private"
        route.request.frame = fetcher.page.main_frame
        route.request.is_navigation_request.return_value = True
        fetcher.guard_navigation(route)
        route.abort.assert_called_once()
        route.continue_.assert_not_called()

    def test_browser_navigation_respects_enforced_robots(self):
        fetcher, _ = self.fetcher()
        route = MagicMock()
        route.request.url = URL
        route.request.frame = fetcher.page.main_frame
        route.request.is_navigation_request.return_value = True
        with patch.object(fetcher, "permitted", return_value="robots_disallowed"):
            fetcher.guard_navigation(route)
        route.abort.assert_called_once()
        self.assertEqual(fetcher.requests_made, 0)

    def test_browser_redirect_obeys_request_limit(self):
        fetcher, _ = self.fetcher("--max-requests", "1")
        fetcher.requests_made = 1
        route = MagicMock()
        route.request.url = URL
        route.request.frame = fetcher.page.main_frame
        route.request.is_navigation_request.return_value = True
        with patch.object(fetcher, "permitted", return_value="allowed"):
            fetcher.guard_navigation(route)
        route.abort.assert_called_once()
        self.assertEqual(fetcher.navigation_error, "request_budget_exhausted")

    @unittest.skipUnless(importlib.util.find_spec("playwright"), "Requiere el extra browser")
    def test_existing_personal_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory)
            (profile / "Preferences").write_text("do not read personal data")
            fetcher = ex.BrowserFetcher(args(None, "--browser-profile", directory), lambda record: None)
            self.addCleanup(fetcher.close)
            with self.assertRaises(ValueError):
                fetcher.open_browser()
            self.assertIsNone(fetcher.driver)

    @unittest.skipUnless(importlib.util.find_spec("playwright"), "Requiere el extra browser")
    def test_launch_is_visible_and_uses_a_separate_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            fetcher = ex.BrowserFetcher(args(None, "--browser-profile", directory), lambda record: None)
            with patch("playwright.sync_api.sync_playwright") as playwright:
                driver = playwright.return_value.start.return_value
                driver.chromium.launch_persistent_context.return_value.pages = [MagicMock()]
                try:
                    fetcher.open_browser()
                    options = driver.chromium.launch_persistent_context.call_args.kwargs
                    self.assertFalse(options["headless"])
                    self.assertFalse(options["ignore_https_errors"])
                    for name in ("args", "user_agent", "proxy", "http_credentials"):
                        self.assertNotIn(name, options)
                finally:
                    fetcher.close()


class PipelineTests(OfflineCase):
    def temp_dir(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def test_local_extraction_exports_and_resumes_without_duplicates(self):
        root = self.temp_dir()
        source = root / "fixture.html"
        source.write_bytes(html())
        config = args(root / "out", "--html", str(source))
        self.assertEqual(ex.run(config), 0)
        self.assertEqual(ex.run(config), 0)
        documents = list((config.output / "documents").glob("*.json"))
        self.assertEqual(len(documents), 1)
        self.assertEqual(len((config.output / "articles.jsonl").read_text(encoding="utf-8").splitlines()), 1)
        summary = json.loads((config.output / "summary.json").read_text())
        self.assertEqual(summary["http_requests_this_run"], 0)
        self.assertEqual(summary["attempts_this_run"], {})
        self.assertFalse((config.output / ".extraction.lock").exists())

    def test_outside_period_document_preserved_but_not_exported_as_success(self):
        root = self.temp_dir()
        source = root / "fixture.html"
        source.write_bytes(html(datePublished="2026-10-21T12:00:00Z"))
        config = args(root / "out", "--html", str(source))
        self.assertEqual(ex.run(config), 2)
        self.assertEqual(len(list((config.output / "documents").glob("*.json"))), 1)
        self.assertEqual((config.output / "articles.jsonl").read_text(), "")

    def test_changed_configuration_rejected_without_removing_checkpoint(self):
        root = self.temp_dir()
        source = root / "fixture.html"
        source.write_bytes(html())
        config = args(root / "out", "--html", str(source))
        ex.run(config)
        previous = (config.output / "checkpoint.json").read_bytes()
        config.end = date(2026, 10, 21)
        with self.assertRaises(ValueError):
            ex.run(config)
        self.assertEqual((config.output / "checkpoint.json").read_bytes(), previous)

    def test_modified_local_input_requires_a_new_output(self):
        root = self.temp_dir()
        source = root / "fixture.html"
        source.write_bytes(html())
        config = args(root / "out", "--html", str(source))
        ex.run(config)
        source.write_bytes(html(headline="A different version"))
        with self.assertRaises(ValueError):
            ex.run(config)

    def test_existing_foreign_output_is_not_overwritten(self):
        root = self.temp_dir()
        (root / "summary.json").write_text("original")
        with self.assertRaises(ValueError):
            ex.run(args(root))
        self.assertEqual((root / "summary.json").read_text(), "original")

    def test_full_mock_http_pipeline(self):
        root = self.temp_dir()
        config = args(root / "out", "--seed", HOME + "/business/")
        def get(session, url, **kwargs):
            self.assertFalse(kwargs["allow_redirects"])
            if url.endswith("robots.txt"):
                return response(url, content=b"User-agent: *\nAllow: /", **{"Content-Type": "text/plain"})
            if url == HOME + "/business/":
                return response(url, content=f'<a href="{URL}">Synthetic</a>'.encode())
            return response(url, content=html())
        with patch.object(requests.Session, "get", autospec=True, side_effect=get) as get_mock:
            self.assertEqual(ex.run(config), 0)
        self.assertEqual(get_mock.call_count, 3)
        summary = json.loads((config.output / "summary.json").read_text())
        self.assertEqual(summary["attempts_this_run"], {"discovery_ok": 1, "success": 1})

    def test_manifest_is_saved_before_first_remote_attempt(self):
        root = self.temp_dir()
        config = args(root / "out", "--url", URL)
        def check_manifest(url, stage):
            manifests = list((config.output / "runs").glob("*/manifest.json"))
            self.assertEqual(len(manifests), 1)
            manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
            self.assertEqual(manifest["state"], "running")
            self.assertIn("dependencies", manifest)
            return ex.FetchResult(url, "timeout")
        with patch.object(ex.Fetcher, "follow", side_effect=check_manifest):
            self.assertEqual(ex.run(config), 2)
        manifest = json.loads(next((config.output / "runs").glob("*/manifest.json")).read_text(encoding="utf-8"))
        self.assertEqual(manifest["state"], "finalized")

    def test_full_pipeline_observes_disallow_and_exports_article(self):
        root = self.temp_dir()
        config = args(root / "out", "--seed", HOME + "/business/", "--robots-policy", "observe")
        def get(session, url, **kwargs):
            if url.endswith("robots.txt"):
                return response(url, content=b"User-agent: *\nDisallow: /", **{"Content-Type": "text/plain"})
            if url == HOME + "/business/":
                return response(url, content=f'<a href="{URL}">Synthetic</a>'.encode())
            return response(url, content=html())
        with patch.object(requests.Session, "get", autospec=True, side_effect=get) as get_mock:
            self.assertEqual(ex.run(config), 0)
        self.assertEqual(get_mock.call_count, 3)
        summary = json.loads((config.output / "summary.json").read_text())
        self.assertEqual(summary["robots_policy"], "observe")
        self.assertEqual(summary["robots_decisions_this_run"], {"robots_disallowed": 2})
        records = [json.loads(line) for line in (config.output / "articles.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["text"], BODY)

    def test_pending_candidates_resume_after_limit(self):
        root = self.temp_dir()
        first = URL
        second = URL.replace("synthetic-report", "synthetic-other")
        config = args(root / "out", "--url", first, "--url", second, "--max-articles", "1")
        with patch.object(ex.Fetcher, "follow", side_effect=lambda url, stage: ex.FetchResult(url, "ok", 200, html(), "text/html", ex.utc_now())) as get:
            self.assertEqual(ex.run(config), 0)
            self.assertEqual(ex.run(config), 0)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(len(list((config.output / "documents").glob("*.json"))), 2)

    def test_failed_request_is_pending_and_retried_on_next_invocation(self):
        root = self.temp_dir()
        config = args(root / "out", "--url", URL)
        with patch.object(ex.Fetcher, "follow", side_effect=[ex.FetchResult(URL, "timeout"), ex.FetchResult(URL, "ok", 200, html(), "text/html", ex.utc_now())]):
            self.assertEqual(ex.run(config), 2)
            self.assertEqual(ex.run(config), 0)

    def test_resume_respects_retry_after_deadline(self):
        root = self.temp_dir()
        config = args(root / "out", "--url", URL)
        deadline = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        with patch.object(ex.Fetcher, "follow", return_value=ex.FetchResult(URL, "rate_limited", 429, retry_at=deadline)) as get:
            self.assertEqual(ex.run(config), 2)
            self.assertEqual(ex.run(config), 2)
        self.assertEqual(get.call_count, 1)

    def test_invalid_cli_never_starts_network(self):
        for arguments in [["--timeout", "0"], ["--retries", "9"], ["--html", "x.html", "--url", URL]]:
            with self.subTest(arguments=arguments), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exit:
                ex.main(arguments)
            self.assertEqual(exit.exception.code, 2)


def add_http_case(code, expected):
    def test(self):
        fetcher, _ = self.fetcher()
        with patch.object(fetcher.session, "get", return_value=response(URL, code)):
            self.assertEqual(fetcher.request(URL, "article").result, expected)
    setattr(FetcherTests, f"test_http_{code}", test)


for code, expected in [(401, "authentication_required"), (403, "access_denied"),
                       (429, "rate_limited"), (404, "http_error"), (500, "http_error")]:
    add_http_case(code, expected)


if __name__ == "__main__":
    unittest.main()
