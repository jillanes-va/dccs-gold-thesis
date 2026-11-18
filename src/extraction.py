"""Scraper auditable de Reuters: URLs, páginas, sitemaps y HTML local.

    uv run python src/extraction.py --help

No garantiza cobertura histórica ni evita restricciones de acceso. Las salidas
predeterminadas viven en data/, fuera de Git. No modifica src/pilot.py.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import logging
import os
import re
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests
import trafilatura
from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_datetime


VERSION = "1.3"
AGENT = "AcademicReutersExtraction/1.0 (+research; contact: j.illanesv@udd.cl)"
HOSTS = {"www.reuters.com", "reuters.com"}
DEFAULT_SEEDS = ["https://www.reuters.com/business/", "https://www.reuters.com/markets/"]
MAX_BYTES = 8 * 1024 * 1024
LOG = logging.getLogger("extraction")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def digest(value: bytes):
    return hashlib.sha256(value).hexdigest()


def retry_after_seconds(value):
    if not value:
        return 0
    try:
        return max(0, float(value))
    except ValueError:
        try:
            return max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 0


def atomic_json(path: Path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def normalize_url(value: str, base: str = "") -> str:
    """Preserve meaningful queries; remove fragments and known tracking only."""
    parsed = urlsplit(urljoin(base, value.strip()))
    if (parsed.scheme != "https" or parsed.hostname not in HOSTS
            or parsed.username or parsed.password or parsed.netloc.lower() not in HOSTS):
        raise ValueError("Se requiere una URL HTTPS pública de reuters.com")
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit(("https", parsed.hostname, parsed.path or "/", urlencode(query), ""))


def is_article_url(url):
    # Heurística de descubrimiento, no criterio científico de relevancia.
    return bool(re.search(r"-\d{4}-\d{2}-\d{2}/?$", urlsplit(url).path))


def discover(content: bytes, base: str):
    """Return (kind, url) from HTML, sitemap indexes, URL sets, RSS or Atom."""
    found = {}
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        root = None
    if root is not None:
        root_type = root.tag.rsplit("}", 1)[-1]
        if root_type in {"sitemapindex", "urlset"}:
            for child in root:
                loc = next((n.text for n in child if n.tag.rsplit("}", 1)[-1] == "loc"), None)
                if loc:
                    try:
                        url = normalize_url(loc, base)
                    except ValueError:
                        continue
                    if root_type == "sitemapindex" or is_article_url(url):
                        found[url] = "discovery" if root_type == "sitemapindex" else "article"
            return [(kind, url) for url, kind in found.items()]
        if root_type in {"rss", "feed"}:
            for node in root.iter():
                if node.tag.rsplit("}", 1)[-1] == "link" and node.attrib.get("rel", "alternate") == "alternate":
                    try:
                        url = normalize_url(node.attrib.get("href") or node.text or "", base)
                    except ValueError:
                        continue
                    if is_article_url(url):
                        found[url] = "article"
            return [(kind, url) for url, kind in found.items()]
    soup = BeautifulSoup(content, "html.parser")
    for link in soup.select("a[href]"):
        try:
            url = normalize_url(link["href"], base)
        except ValueError:
            continue
        if is_article_url(url):
            found[url] = "article"
    return [(kind, url) for url, kind in found.items()]


def jsonld_nodes(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            pending = [json.loads(script.string or script.get_text())]
        except (ValueError, TypeError):
            continue
        while pending:
            item = pending.pop()
            if isinstance(item, list):
                pending.extend(reversed(item))
            elif isinstance(item, dict):
                yield item
                graph = item.get("@graph", [])
                if isinstance(graph, (dict, list)):
                    pending.append(graph)


def meta(soup, *names):
    for name in names:
        node = soup.find("meta", property=name) or soup.find("meta", attrs={"name": name})
        if node and node.get("content"):
            return node["content"].strip()
    return None


def names(value):
    if isinstance(value, dict):
        return str(value.get("name") or "")
    if isinstance(value, list):
        return ", ".join(filter(None, (names(v) for v in value)))
    return str(value or "")


def extract_document(content: bytes, url: str | None):
    soup = BeautifulSoup(content, "html.parser")
    node = next((item for item in jsonld_nodes(soup)
                 if any(str(t).endswith("Article") for t in
                        (item.get("@type") if isinstance(item.get("@type"), list) else [item.get("@type", "")]))), {})
    parts = node.get("hasPart") or []
    if not isinstance(parts, list):
        parts = [parts]
    if (node.get("isAccessibleForFree") in (False, "false", "False")
            or any(isinstance(part, dict) and part.get("isAccessibleForFree") in (False, "false", "False") for part in parts)):
        return None, "restricted_content"
    title = str(node.get("headline") or meta(soup, "og:title", "twitter:title") or "")
    page_title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
    if any(marker in page_title for marker in ("access denied", "just a moment", "robot or human", "captcha")):
        return None, "access_challenge"
    metadata = trafilatura.extract_metadata(content)
    text = node.get("articleBody")
    method = "jsonld_articleBody"
    if not isinstance(text, str) or not text.strip():
        text = trafilatura.extract(content, url=url, include_comments=False,
                                   include_tables=False, favor_precision=True) or ""
        method = "trafilatura"
    raw_date = node.get("datePublished") or meta(soup, "article:published_time", "datePublished", "pubdate")
    date_source = "jsonld" if node.get("datePublished") else "meta"
    if not raw_date:
        raw_date = metadata.date if metadata else None
        date_source = "trafilatura_inferred" if raw_date else "missing"
    published = published_utc = None
    try:
        parsed = parse_datetime(str(raw_date)) if raw_date else None
        if parsed:
            published = parsed.isoformat()
            if parsed.utcoffset() is not None:
                published_utc = parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError):
        date_source = "invalid"
    canonical = soup.find("link", rel="canonical")
    canonical_value = canonical.get("href") if canonical else meta(soup, "og:url")
    try:
        canonical_url = normalize_url(canonical_value or url or "", url or "")
    except ValueError:
        canonical_url = None
    publisher = names(node.get("publisher")) or None
    document = {
        "url": url, "canonical_url": canonical_url, "title": title or (metadata.title if metadata else None),
        "text": text.strip(), "text_sha256": digest(text.strip().encode("utf-8")),
        "word_count": len(text.split()), "author": names(node.get("author")) or None,
        "publisher": publisher, "editorial_source": "Reuters" if url or canonical_url else None,
        "source_confidence": "domain_inferred" if url or canonical_url else "unknown",
        "language": soup.html.get("lang") if soup.html else None,
        "published_at": published, "published_at_utc": published_utc,
        "published_at_raw": raw_date, "date_source": date_source,
        "timezone_known": published_utc is not None,
        "modified_at_raw": node.get("dateModified"), "document_type": node.get("@type"),
        "extraction_method": method, "schema_version": VERSION,
    }
    return document, "parsed"


def quality_status(document, start, end, min_words):
    if not document["published_at"]:
        return "missing_date"
    if not start <= parse_datetime(document["published_at"]).date() <= end:
        return "outside_period"
    if not document.get("title"):
        return "missing_title"
    if document["word_count"] < min_words:
        return "short_or_empty"
    return "success"


@dataclass
class FetchResult:
    url: str
    result: str
    http_status: int | None = None
    content: bytes = b""
    content_type: str = ""
    retrieved_at: str | None = None
    retry_at: str | None = None


class Fetcher:
    def __init__(self, args, audit):
        self.args, self.audit = args, audit
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": AGENT, "Accept-Language": "en-US,en;q=0.8"})
        self.last = {}
        self.robots = {}
        self.requests_made = 0
        self.cooldowns = {}
        self.robots_decisions = Counter()

    def close(self):
        self.session.close()

    def request(self, url, stage):
        """Single HTTP target, bounded response, finite transient retries."""
        host = urlsplit(url).netloc
        for attempt in range(self.args.retries + 1):
            deadline = self.cooldowns.get(host)
            if deadline and deadline > utc_now():
                return FetchResult(url, "rate_limit_deferred", retry_at=deadline)
            if self.requests_made >= self.args.max_requests:
                return FetchResult(url, "request_budget_exhausted")
            wait = max(0, self.args.delay - (time.monotonic() - self.last.get(host, -1e20)))
            time.sleep(wait)
            self.last[host] = time.monotonic()
            self.requests_made += 1
            record = {"at_utc": utc_now(), "url": url, "stage": stage, "attempt": attempt + 1}
            tick = time.monotonic()
            retry_after = None
            try:
                with self.session.get(url, timeout=self.args.timeout, allow_redirects=False, stream=True) as response:
                    record.update(http_status=response.status_code, location=response.headers.get("Location"),
                                  content_type=response.headers.get("Content-Type", ""),
                                  retry_after=response.headers.get("Retry-After"))
                    retry_after = response.headers.get("Retry-After")
                    if response.status_code in {301, 302, 303, 307, 308}:
                        record["result"] = "redirect"
                        result = FetchResult(url, "redirect", response.status_code,
                                             response.headers.get("Location", "").encode())
                    elif response.status_code != 200:
                        status = {401: "authentication_required", 403: "access_denied", 429: "rate_limited"}.get(response.status_code, "http_error")
                        if response.status_code in {401, 403}:
                            sample = next(response.iter_content(8192), b"")
                            challenge = (response.headers.get("x-datadome", "").lower() == "protected"
                                         and b"captcha-delivery" in sample.lower())
                            if challenge:
                                status = "access_challenge"
                            record.update(server=response.headers.get("Server"),
                                          www_authenticate_present=bool(response.headers.get("WWW-Authenticate")),
                                          datadome_challenge=challenge,
                                          error_sample_bytes=len(sample), error_sample_sha256=digest(sample))
                        record["result"] = status
                        result = FetchResult(url, status, response.status_code)
                    else:
                        chunks, size = [], 0
                        for chunk in response.iter_content(65536):
                            size += len(chunk)
                            if size > MAX_BYTES:
                                break
                            chunks.append(chunk)
                        record["result"] = "response_too_large" if size > MAX_BYTES else "ok"
                        result = FetchResult(url, record["result"], 200, b"" if size > MAX_BYTES else b"".join(chunks),
                                             record["content_type"], utc_now())
                        record.update(response_bytes=size, content_sha256=digest(result.content) if result.content else None)
                        if stage == "robots" and result.result == "ok":
                            record["robots_text"] = result.content.decode("utf-8-sig", errors="replace")
            except requests.RequestException as exc:
                status = "tls_error" if isinstance(exc, requests.exceptions.SSLError) else "timeout" if isinstance(exc, requests.exceptions.Timeout) else "connection_error"
                record.update(result=status, error_type=type(exc).__name__, error=str(exc)[:500])
                result = FetchResult(url, status)
            finally:
                record["elapsed_seconds"] = round(time.monotonic() - tick, 4)
                self.audit(record)
            if result.http_status in {429, 503} and retry_after:
                pause = retry_after_seconds(retry_after)
                if pause:
                    result.retry_at = (datetime.now(timezone.utc) + timedelta(seconds=pause)).isoformat()
                    self.cooldowns[host] = result.retry_at
            retryable = result.result in {"timeout", "connection_error"} or result.http_status in {429, 502, 503, 504}
            if not retryable or attempt == self.args.retries:
                return result
            pause = 2 ** (attempt + 1)
            pause = max(pause, retry_after_seconds(retry_after))
            # Defer long server-requested waits to a subsequent invocation.
            if pause > 60:
                return result
            time.sleep(pause)
            # The requested interval was slept in full. Clear the cache as
            # well so simulated clocks and tiny scheduling differences agree.
            self.cooldowns.pop(host, None)
        return result

    def permitted(self, url):
        origin = "https://" + urlsplit(url).netloc
        if origin not in self.robots:
            response = self.follow(origin + "/robots.txt", "robots", check_robots=False)
            parser = None
            status = "robots_" + response.result
            if response.result == "ok":
                text = response.content.decode("utf-8-sig", errors="replace")
                if ("html" not in response.content_type.lower()
                        and re.search(r"(?im)^\s*user-agent\s*:", text)
                        and not text.lstrip().startswith("<")):
                    parser = RobotFileParser()
                    parser.parse(text.splitlines())
                    status = "robots_valid"
                else:
                    status = "robots_invalid"
            self.robots[origin] = parser, status
        parser, status = self.robots[origin]
        if parser is None:
            return status
        return "allowed" if parser.can_fetch(AGENT, url) else "robots_disallowed"

    def follow(self, url, stage="article", check_robots=True):
        visited = set()
        for _ in range(6):
            try:
                url = normalize_url(url)
            except ValueError:
                return FetchResult(url, "redirect_outside_scope")
            if url in visited:
                return FetchResult(url, "redirect_loop")
            visited.add(url)
            if check_robots:
                permission = self.permitted(url)
                continued = permission == "allowed" or (
                    permission == "robots_disallowed" and self.args.robots_policy == "observe")
                self.robots_decisions[permission] += 1
                self.audit({"at_utc": utc_now(), "stage": "robots_decision", "url": url,
                            "result": permission, "policy": self.args.robots_policy,
                            "continued": continued})
                if not continued:
                    return FetchResult(url, permission)
            response = self.request(url, stage)
            if response.result != "redirect":
                return response
            if not response.content:
                return FetchResult(url, "redirect_missing_location", response.http_status)
            url = urljoin(url, response.content.decode())
        return FetchResult(url, "too_many_redirects")


class BrowserFetcher(Fetcher):
    """Visible browser; human verification only, dedicated profile, no stealth."""

    def __init__(self, args, audit):
        super().__init__(args, audit)
        self.driver = self.context = self.page = None
        self.last_response = None
        self.navigation_error = None
        self.browser_requests = 0

    def open_browser(self):
        if self.context is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ValueError("El modo navegador requiere: uv sync --extra browser") from exc
        profile = self.args.browser_profile.resolve()
        marker = profile / ".extraction-profile.json"
        profile.mkdir(parents=True, exist_ok=True)
        if not marker.exists():
            if any(profile.iterdir()):
                raise ValueError("Usa un perfil nuevo y vacío; no se abre tu perfil personal del navegador")
            atomic_json(marker, {"owner": "reuters_extraction", "created_at_utc": utc_now()})
        elif json.loads(marker.read_text(encoding="utf-8")).get("owner") != "reuters_extraction":
            raise ValueError("El perfil no pertenece a extraction")
        self.driver = sync_playwright().start()
        # Native browser settings: no fingerprint modifications, imported
        # cookies, proxy rotations, CAPTCHA solvers or disabled TLS validation.
        self.context = self.driver.chromium.launch_persistent_context(
            str(profile), channel=self.args.browser_channel, headless=False,
            ignore_https_errors=False, service_workers="block")
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.context.route("**/*", self.guard_navigation)
        self.context.on("request", self.count_browser_request)
        self.page.on("response", self.observe_response)
        self.audit({"at_utc": utc_now(), "stage": "browser_started", "channel": self.args.browser_channel,
                    "verification": "human_only", "profile": str(profile)})

    def count_browser_request(self, request):
        self.browser_requests += 1

    def observe_response(self, response):
        if response.request.is_navigation_request() and response.request.frame == self.page.main_frame:
            self.last_response = response
            self.audit({"at_utc": utc_now(), "stage": "browser_document", "url": response.url,
                        "http_status": response.status})

    def guard_navigation(self, route):
        request = route.request
        if not request.is_navigation_request() or request.frame != self.page.main_frame:
            route.continue_()
            return
        try:
            target = normalize_url(request.url)
        except ValueError:
            self.navigation_error = "redirect_outside_scope"
            route.abort()
            return
        permission = self.permitted(target)
        continued = permission == "allowed" or (
            permission == "robots_disallowed" and self.args.robots_policy == "observe")
        self.audit({"at_utc": utc_now(), "stage": "browser_navigation_permission", "url": target,
                    "result": permission, "continued": continued})
        if not continued:
            self.navigation_error = permission
            route.abort()
            return
        if self.requests_made >= self.args.max_requests:
            self.navigation_error = "request_budget_exhausted"
            route.abort()
            return
        host = urlsplit(target).netloc
        time.sleep(max(0, self.args.delay - (time.monotonic() - self.last.get(host, -1e20))))
        self.last[host] = time.monotonic()
        self.requests_made += 1
        route.continue_()

    def request(self, url, stage):
        # Robots and XML remain plain HTTP; only HTML acquisition uses a page.
        if (stage == "robots" or urlsplit(url).path.endswith((".xml", ".xml.gz"))
                or ("outputType", "xml") in parse_qsl(urlsplit(url).query)):
            return super().request(url, stage)
        if self.requests_made >= self.args.max_requests:
            return FetchResult(url, "request_budget_exhausted")
        deadline = self.cooldowns.get(urlsplit(url).netloc)
        if deadline and deadline > utc_now():
            return FetchResult(url, "rate_limit_deferred", retry_at=deadline)
        self.open_browser()
        self.last_response = None
        self.navigation_error = None
        started = time.monotonic()
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=self.args.timeout * 1000)
            self.page.wait_for_timeout(500)
            status, challenge = self.page_state()
            if challenge and self.args.browser_wait:
                LOG.warning("Completa la verificación normal en la ventana del navegador. Espera máxima: %ss", self.args.browser_wait)
                self.audit({"at_utc": utc_now(), "stage": "human_verification_wait", "url": url,
                            "initial_http_status": status, "max_wait_seconds": self.args.browser_wait})
                deadline = time.monotonic() + self.args.browser_wait
                while challenge and time.monotonic() < deadline:
                    self.page.wait_for_timeout(1000)
                    status, challenge = self.page_state()
            content = self.page.content().encode("utf-8")
            current = normalize_url(self.page.url)
            result = (self.navigation_error or "access_challenge") if challenge else {
                200: "ok", 401: "authentication_required", 403: "access_denied", 429: "rate_limited"
            }.get(status, "http_error")
            headers = self.last_response.headers if self.last_response else {}
            if status in {429, 503}:
                seconds = retry_after_seconds(headers.get("retry-after"))
                if seconds:
                    retry_at = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
                    self.cooldowns[urlsplit(current).netloc] = retry_at
                else:
                    retry_at = None
            else:
                retry_at = None
            if len(content) > MAX_BYTES:
                result, content = "response_too_large", b""
            self.audit({"at_utc": utc_now(), "stage": stage, "transport": "browser", "url": url,
                        "final_url": current, "http_status": status, "result": result,
                        "representation": "rendered_dom", "elapsed_seconds": round(time.monotonic() - started, 4)})
            return FetchResult(current, result, status, content if result == "ok" else b"",
                               "text/html; charset=utf-8", utc_now(), retry_at)
        except Exception as exc:
            result = self.navigation_error or "browser_error"
            self.audit({"at_utc": utc_now(), "stage": stage, "transport": "browser", "url": url,
                        "result": result, "error_type": type(exc).__name__, "error": str(exc)[:500]})
            return FetchResult(url, result)

    def page_state(self):
        status = self.last_response.status if self.last_response else None
        title = self.page.title().lower()
        challenge = any(term in title for term in ("access denied", "just a moment", "captcha", "robot or human"))
        if status in {401, 403}:
            headers = self.last_response.headers
            challenge = challenge or (headers.get("x-datadome", "").lower() == "protected"
                                      and "captcha-delivery" in self.page.content().lower())
        challenge = challenge or self.page.locator('iframe[src*="captcha-delivery"]').first.is_visible()
        return status, challenge

    def close(self):
        try:
            if self.context:
                self.context.close()
        finally:
            try:
                if self.driver:
                    self.driver.stop()
            finally:
                super().close()


def initial_items(args):
    if args.html:
        return [{"kind": "local", "url": str(path.resolve()), "discovered_from": "local_input", "done": False,
                 "input_sha256": digest(path.read_bytes()) if path.stat().st_size <= MAX_BYTES else "too_large"} for path in args.html]
    urls = list(args.url)
    if args.urls_file:
        urls.extend(line.strip() for line in args.urls_file.read_text(encoding="utf-8-sig").splitlines()
                    if line.strip() and not line.lstrip().startswith("#"))
    items = [{"kind": "article", "url": normalize_url(url), "discovered_from": "explicit_input", "done": False} for url in urls]
    seeds = args.seed + args.sitemap
    if not items and not seeds:
        seeds = DEFAULT_SEEDS
    items.extend({"kind": "discovery", "url": normalize_url(url), "discovered_from": "seed", "done": False} for url in seeds)
    return list({(item["kind"], item["url"]): item for item in items}.values())


def process_article(content, url, origin, args, output, run_id, retrieved_at):
    document, status = extract_document(content, url)
    if document is None:
        return status
    raw_sha = digest(content)
    document.update(run_id=run_id, retrieved_at_utc=retrieved_at, input_origin=origin,
                    acquisition_platform="reuters.com" if url else "local_html",
                    acquired_representation="rendered_dom" if url and args.transport == "browser" else "html",
                    raw_sha256=raw_sha)
    document["quality_status"] = quality_status(document, args.start, args.end, args.min_words)
    raw_path = output / "raw" / (raw_sha + ".html")
    if not raw_path.exists():
        raw_path.write_bytes(content)
    document["raw_path"] = raw_path.relative_to(output).as_posix()
    document_id = digest(((url or origin) + "\n" + raw_sha).encode())
    document["document_id"] = document_id
    target = output / "documents" / (document_id + ".json")
    if not target.exists():
        atomic_json(target, document)
    return document["quality_status"]


def run(args):
    items = initial_items(args)
    configuration = {"schema_version": VERSION, "code_sha256": digest(Path(__file__).read_bytes()),
                     "start": str(args.start), "end": str(args.end),
                     "min_words": args.min_words, "robots_policy": args.robots_policy, "transport": args.transport,
                     "browser_channel": args.browser_channel if args.transport == "browser" else None,
                     "browser_profile": str(args.browser_profile.resolve()) if args.transport == "browser" else None, "inputs": items}
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    lock = output / ".extraction.lock"
    # One writer prevents corrupt checkpoints and duplicate exports.
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))
    try:
        state_path = output / "checkpoint.json"
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if state["configuration"] != configuration:
                raise ValueError("La configuración cambió: usa otra carpeta de salida para conservar la trazabilidad")
        else:
            if any(path.name != lock.name for path in output.iterdir()):
                raise ValueError("La carpeta contiene salidas ajenas; usa una carpeta nueva")
            state = {"configuration": configuration, "items": [dict(item) for item in items], "cooldowns": {}}
        for folder in ("raw", "documents", "runs"):
            (output / folder).mkdir(exist_ok=True)
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:8]
        run_dir = output / "runs" / run_id
        run_dir.mkdir()
        manifest = {"run_id": run_id, "started_at_utc": utc_now(), "configuration": configuration,
                    "execution": {k: str(v) for k, v in vars(args).items()}, "python": sys.version,
                    "code_sha256": digest(Path(__file__).read_bytes()), "user_agent": AGENT,
                    "dependencies": {p: importlib.metadata.version(p) for p in
                                     ("requests", "beautifulsoup4", "trafilatura", "python-dateutil", "truststore")}}
        if args.transport == "browser" and not args.html:
            manifest["dependencies"]["playwright"] = importlib.metadata.version("playwright")
            manifest["article_user_agent"] = "native_browser"
        manifest["state"] = "running"
        atomic_json(run_dir / "manifest.json", manifest)
        counts = Counter()
        articles_tried = discoveries_tried = 0
        atomic_json(state_path, state)
        with (run_dir / "http.jsonl").open("w", encoding="utf-8") as http_log, (run_dir / "attempts.jsonl").open("w", encoding="utf-8") as attempts:
            def audit(record):
                http_log.write(json.dumps(record, ensure_ascii=False) + "\n")
                http_log.flush()
            fetcher = BrowserFetcher(args, audit) if args.transport == "browser" and not args.html else Fetcher(args, audit)
            fetcher.cooldowns.update(state.get("cooldowns", {}))
            known = {(item["kind"], item["url"]) for item in state["items"]}
            try:
                for item in state["items"]:
                    if item["done"]:
                        continue
                    if item.get("retry_at") and item["retry_at"] > utc_now():
                        continue
                    if fetcher.requests_made >= args.max_requests and item["kind"] != "local":
                        break
                    if item["kind"] == "discovery":
                        if discoveries_tried >= args.max_pages:
                            continue
                        discoveries_tried += 1
                    else:
                        if articles_tried >= args.max_articles:
                            continue
                        articles_tried += 1
                    attempted_at = utc_now()
                    response = None
                    status = "unprocessed"
                    error = None
                    try:
                        if item["kind"] == "local":
                            source = Path(item["url"])
                            if source.stat().st_size > MAX_BYTES:
                                status = "response_too_large"
                            else:
                                status = process_article(source.read_bytes(), None, item["url"], args, output, run_id, None)
                        else:
                            response = fetcher.follow(item["url"], item["kind"])
                            status = response.result
                            item["retry_at"] = response.retry_at
                            if status == "ok":
                                if item["kind"] == "discovery":
                                    for kind, url in discover(response.content, response.url):
                                        if (kind, url) not in known:
                                            state["items"].append({"kind": kind, "url": url, "discovered_from": response.url, "done": False})
                                            known.add((kind, url))
                                    status = "discovery_ok"
                                elif "html" not in response.content_type.lower():
                                    status = "not_html"
                                else:
                                    status = process_article(response.content, response.url, item["discovered_from"], args, output, run_id, response.retrieved_at)
                        # Failures remain pending for the next invocation; each is
                        # visited at most once during this invocation.
                        item["done"] = status in {"success", "missing_date", "outside_period", "missing_title", "short_or_empty", "discovery_ok"}
                    except (ValueError, OSError, TypeError) as exc:
                        status = "processing_error"
                        error = type(exc).__name__ + ": " + str(exc)[:500]
                        LOG.error("%s: %s", item["url"], exc)
                    item["last_result"] = status
                    state["cooldowns"] = fetcher.cooldowns
                    counts[status] += 1
                    record = {"at_utc": attempted_at, **item, "result": status,
                              "final_url": response.url if response else None,
                              "http_status": response.http_status if response else None, "error": error}
                    attempts.write(json.dumps(record, ensure_ascii=False) + "\n")
                    attempts.flush()
                    atomic_json(state_path, state)
                    LOG.info("[%s] %s", status, item["url"])
            finally:
                fetcher.close()
                state["cooldowns"] = fetcher.cooldowns
                manifest.update(state="finalized", finished_at_utc=utc_now(), http_requests=fetcher.requests_made)
                atomic_json(run_dir / "manifest.json", manifest)
                atomic_json(state_path, state)
                exported = Counter()
                temporary = output / "articles.jsonl.tmp"
                with temporary.open("w", encoding="utf-8") as stream:
                    for path in sorted((output / "documents").glob("*.json")):
                        document = json.loads(path.read_text(encoding="utf-8"))
                        exported[document["quality_status"]] += 1
                        if document["quality_status"] == "success":
                            stream.write(json.dumps(document, ensure_ascii=False) + "\n")
                os.replace(temporary, output / "articles.jsonl")
                summary = {"run_id": run_id, "attempts_this_run": dict(counts),
                           "http_requests_this_run": fetcher.requests_made,
                           "robots_policy": args.robots_policy,
                           "transport": args.transport,
                           "request_budget_scope": "robots_and_browser_documents" if args.transport == "browser" else "http_requests",
                           "browser_resource_requests": getattr(fetcher, "browser_requests", 0),
                           "robots_decisions_this_run": dict(fetcher.robots_decisions),
                           "documents_total": sum(exported.values()), "document_quality_totals": dict(exported),
                           "queued_total": len(state["items"]), "pending_total": sum(not i["done"] for i in state["items"])}
                atomic_json(run_dir / "summary.json", summary)
                atomic_json(output / "summary.json", summary)
                LOG.info("Resumen: %s", json.dumps(summary, ensure_ascii=False))
        return 0 if exported["success"] else 2
    finally:
        lock.unlink()


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", action="append", default=[], help="URL de artículo; repetible")
    parser.add_argument("--urls-file", type=Path, help="Archivo UTF-8 con una URL por línea")
    parser.add_argument("--seed", action="append", default=[], help="Página de descubrimiento; repetible")
    parser.add_argument("--sitemap", action="append", default=[], help="Sitemap/índice XML o feed; repetible")
    parser.add_argument("--html", action="append", type=Path, default=[], help="HTML local; repetible, no usa red")
    parser.add_argument("--output", type=Path, default=Path("data/reuters/extraction"))
    parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 10, 15))
    parser.add_argument("--min-words", type=int, default=100)
    parser.add_argument("--max-articles", type=int, default=12, help="Intentos de artículos por invocación")
    parser.add_argument("--max-pages", type=int, default=10, help="Páginas de descubrimiento por invocación")
    parser.add_argument("--max-requests", type=int, default=50, help="Incluye robots, redirecciones y reintentos")
    parser.add_argument("--delay", type=float, default=3)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--tls-trust", choices=("system", "requests"), default="system")
    parser.add_argument("--robots-policy", choices=("observe", "enforce"), default="observe",
                        help="observe: registra Disallow y continúa; enforce: detiene el acceso. Los errores de robots se mantienen")
    parser.add_argument("--transport", choices=("http", "browser"), default="http")
    parser.add_argument("--browser-channel", choices=("msedge", "chrome", "chromium"), default="msedge")
    parser.add_argument("--browser-profile", type=Path, default=Path("data/reuters/browser_profile"))
    parser.add_argument("--browser-wait", type=int, default=180, help="Segundos para verificación manual en navegador visible; 0 no espera")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.start > args.end or min(args.max_articles, args.max_pages, args.max_requests, args.min_words) < 1:
        parser.error("Revisa el período y utiliza límites enteros positivos")
    if args.delay < 0 or args.timeout <= 0 or not 0 <= args.retries <= 5:
        parser.error("delay >= 0, timeout > 0, retries entre 0 y 5")
    if not 0 <= args.browser_wait <= 600:
        parser.error("browser-wait debe estar entre 0 y 600 segundos")
    if args.transport == "browser" and not args.html:
        try:
            importlib.metadata.version("playwright")
        except importlib.metadata.PackageNotFoundError:
            parser.error("El modo navegador requiere: uv sync --extra browser")
    if args.html and (args.url or args.urls_file or args.seed or args.sitemap):
        parser.error("El modo --html no se combina con entradas remotas")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.tls_trust == "system" and not args.html:
        import truststore
        truststore.inject_into_ssl()
    try:
        return run(args)
    except KeyboardInterrupt:
        LOG.warning("Interrumpido; se conserva el checkpoint")
        return 130
    except (ValueError, OSError) as exc:
        LOG.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
