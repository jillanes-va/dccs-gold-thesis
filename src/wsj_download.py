"""Adquisición WSJ para notebooks/descarga_wsj.ipynb; sin decisiones econométricas."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
import uuid

from bs4 import BeautifulSoup
from dateutil.parser import isoparse
import pandas as pd
import requests
import trafilatura


VERSION = "1.0"
AGENT = "DCCSNewsResearch/1.0"
STAGES = {"day": pd.DateOffset(days=1), "week": pd.DateOffset(weeks=1),
          "month": pd.DateOffset(months=1), "year": pd.DateOffset(years=1)}
WSJ_HOSTS = {"wsj.com", "www.wsj.com", "online.wsj.com", "blogs.wsj.com", "graphics.wsj.com"}
ARCHIVE_HOSTS = {"archive.org", "web.archive.org"}


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def append_json(path, value):
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")


def normalize_url(value, *, archive=False):
    parts = urlsplit(str(value).strip())
    hosts = WSJ_HOSTS | ARCHIVE_HOSTS if archive else WSJ_HOSTS
    if (parts.scheme not in {"http", "https"} or parts.hostname not in hosts
            or parts.username or parts.password or parts.port not in {None, 80, 443}):
        raise ValueError("URL vacía, inválida o fuera de los dominios admitidos")
    # Solo cambia HTTP a HTTPS; no añade parámetros de acceso ni de suscripción.
    return urlunsplit(("https", parts.hostname, parts.path or "/", parts.query, ""))


def identity(value):
    parts = urlsplit(normalize_url(value))
    host = "www.wsj.com" if parts.hostname in {"wsj.com", "online.wsj.com"} else parts.hostname
    return urlunsplit(("https", host, parts.path.rstrip("/"), parts.query, ""))


def same_article(left, right):
    if identity(left) == identity(right):
        return True
    # Los slugs pueden cambiar; el identificador numérico histórico permanece.
    a = re.search(r"-(\d{10,})(?:\.html)?$", urlsplit(left).path)
    b = re.search(r"-(\d{10,})(?:\.html)?$", urlsplit(right).path)
    return bool(a and b and a[1] == b[1])


def unwrap_archive_url(value):
    """Wayback reescribe también canonical/og:url: recuperar la URL editorial."""
    parts = urlsplit(value)
    if parts.hostname == "web.archive.org":
        match = re.match(r"^/web/\d{14}(?:[a-z_]+)?/(https?://.+)$", parts.path)
        if not match:
            raise ValueError("Metadato de archivo inválido")
        return match[1] + ("?" + parts.query if parts.query else "")
    return value


def load_input(path):
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    missing = {"date", "headlines", "desk", "url"} - set(frame.columns)
    if missing:
        raise ValueError(f"Faltan columnas: {sorted(missing)}")
    frame["source_row"] = range(2, len(frame) + 2)
    frame["csv_date"] = pd.to_datetime(frame["date"], format="%d/%m/%Y", errors="coerce")
    frame["input_status"] = "ok"
    frame.loc[frame.csv_date.isna(), "input_status"] = "invalid_date"
    keys = []
    for index, row in frame.iterrows():
        try:
            key = identity(row.url)
        except (ValueError, TypeError):
            key = f"invalid:{row.source_row}:{row.url}"
            frame.loc[index, "input_status"] = "invalid_url" if row.input_status == "ok" else "invalid_date_and_url"
        keys.append(sha(key.encode()))
    frame["article_id"] = keys
    return frame


def select_period(frame, start, stage):
    start = pd.Timestamp(start).normalize()
    if start.tzinfo is not None:
        raise ValueError("Usar una fecha de calendario sin zona horaria, igual que el CSV")
    end = start + STAGES[stage]
    return frame.loc[(frame.csv_date >= start) & (frame.csv_date < end)].copy(), end


def period_plan(frame, start):
    rows = []
    for stage in STAGES:
        subset, end = select_period(frame, start, stage)
        rows.append({"stage": stage, "start_inclusive": str(pd.Timestamp(start).date()),
                     "end_exclusive": str(end.date()), "csv_rows": len(subset),
                     "unique_articles": subset.article_id.nunique(),
                     "invalid_rows": int((subset.input_status != "ok").sum())})
    return pd.DataFrame(rows)


def json_nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from json_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from json_nodes(child)


def extract_html(content, expected_url, min_words=80):
    """Extrae cuerpos candidatos. No certifica texto íntegro por longitud."""
    soup = BeautifulSoup(content, "html.parser")
    nodes = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            nodes.extend(json_nodes(json.loads(script.string or script.get_text())))
        except (ValueError, TypeError):
            pass
    articles = [node for node in nodes if any(str(t).endswith("Article") for t in
                (node.get("@type") if isinstance(node.get("@type"), list) else [node.get("@type", "")]))]
    def meta(*names):
        for name in names:
            tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
            if tag and tag.get("content"):
                return tag["content"]
        return None
    node = next((n for n in articles if n.get("articleBody")), articles[0] if articles else {})
    title = node.get("headline") or meta("og:title", "twitter:title")
    page_title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
    visible = soup.get_text(" ", strip=True)
    challenge = any(x in page_title for x in ("access denied", "just a moment", "verify you are human", "robot check"))
    challenge |= bool(soup.select('iframe[src*="captcha"], script[src*="captcha-delivery"]'))
    restricted = any(n.get("isAccessibleForFree") in (False, "false", "False") for n in nodes)
    restricted |= str(meta("article.access") or "").lower() in {"paid", "premium", "subscriber"}
    restricted |= bool(soup.select('[data-testid="paywall"], #cx-paywall, .snippet-promotion'))
    restricted |= any(s in visible.lower() for s in ("subscribe to read the full story", "subscribe to continue reading",
                                                     "to read the full story", "already a subscriber?"))
    canonical = soup.find("link", rel="canonical")
    canonical_url = canonical.get("href") if canonical else meta("og:url")
    canonical_status = "missing"
    if canonical_url:
        try:
            canonical_url = normalize_url(unwrap_archive_url(urljoin(expected_url, canonical_url)))
            canonical_status = "matches" if same_article(canonical_url, expected_url) else "mismatch"
        except ValueError:
            canonical_status = "outside_scope"
    entity_url = node.get("mainEntityOfPage") or node.get("url")
    if isinstance(entity_url, dict):
        entity_url = entity_url.get("@id") or entity_url.get("url")
    if isinstance(entity_url, str) and entity_url.startswith(("http://", "https://")):
        try:
            if not same_article(unwrap_archive_url(entity_url), expected_url):
                canonical_status = "mismatch"
        except ValueError:
            canonical_status = "outside_scope"
    published_raw = node.get("datePublished") or meta("article:published_time", "datePublished", "article.published")
    published_utc, published_timezone = None, None
    try:
        parsed_date = isoparse(published_raw) if published_raw else None
        if parsed_date and parsed_date.utcoffset() is not None:
            published_utc = parsed_date.astimezone(timezone.utc).isoformat()
            published_timezone = str(parsed_date.tzinfo)
    except (ValueError, TypeError, OverflowError):
        pass
    result = {"title": title, "canonical_url": canonical_url, "canonical_status": canonical_status,
              "language": soup.html.get("lang") if soup.html else None,
              "published_at_raw": published_raw, "published_at_utc": published_utc, "published_timezone": published_timezone,
              "publication_date_source": "jsonld" if node.get("datePublished") else "meta" if published_raw else "missing",
              "modified_at_raw": node.get("dateModified") or meta("article.updated"), "author": node.get("author") or meta("author"),
              "publisher_metadata": node.get("publisher"), "document_type": node.get("@type"),
              "text": "", "word_count": 0, "full_text_verified": False,
              "completeness": "unverified", "extraction_method": None}
    if challenge or restricted or canonical_status in {"mismatch", "outside_scope"}:
        result["status"] = "access_challenge" if challenge else "restricted_content" if restricted else "identity_mismatch"
        return result
    candidates = []
    if isinstance(node.get("articleBody"), str):
        candidates.append((BeautifulSoup(node["articleBody"], "html.parser").get_text("\n", strip=True), "jsonld.articleBody"))
    containers = soup.select('[itemprop="articleBody"], .article-content, .wsj-snippet-body, .articleBody, .article__body')
    for container in containers:
        paragraphs = container.find_all("p")
        text = "\n\n".join(p.get_text(" ", strip=True) for p in paragraphs) if paragraphs else container.get_text("\n", strip=True)
        candidates.append((text, "dom.article_body"))
    if articles or containers or meta("og:type") == "article":
        try:
            text = trafilatura.extract(content, include_comments=False, include_tables=False, favor_precision=True)
            if text:
                candidates.append((text, "trafilatura"))
        except (ValueError, TypeError):
            pass
    # JSON-LD explícito primero; DOM y trafilatura como respaldo, sin mezclar textos.
    nonempty = [(t.strip(), method) for t, method in candidates if t.strip()]
    adequate = [(t, m) for t, m in nonempty if len(t.split()) >= min_words]
    text, method = next(iter(adequate or nonempty), ("", None))
    result.update(text=text, word_count=len(text.split()), extraction_method=method,
                  text_sha256=sha(text.encode()) if text else None)
    result["status"] = "candidate_unverified" if len(text.split()) >= min_words else "short_or_partial" if text else "no_body"
    return result


@dataclass
class Config:
    delay: float = 3.0
    timeout: float = 25.0
    retries: int = 2
    max_requests: int = 500
    min_words: int = 80
    wayback: bool = True
    browser: bool = False
    browser_channel: str = "msedge"
    local_html: str | None = None


class BudgetExhausted(Exception):
    pass


class Fetcher:
    def __init__(self, config, output, run_dir, state, session=None):
        self.config, self.output, self.run_dir, self.state = config, Path(output), Path(run_dir), state
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": AGENT})
        self.count = 0
        self.robots = {}

    def log(self, **record):
        append_json(self.run_dir / "http.jsonl", {"at_utc": now(), **record})

    def save_state(self):
        write_json(self.output / "checkpoint.json", self.state)

    def pace(self, url):
        if self.count >= self.config.max_requests:
            raise BudgetExhausted
        host = urlsplit(url).hostname
        until = self.state.setdefault("host_next_request", {}).get(host, 0)
        wait = until - time.time()
        if wait > 60:
            return False
        if wait > 0:
            time.sleep(wait)
        self.count += 1
        self.state["host_next_request"][host] = time.time() + self.config.delay
        self.save_state()
        return True

    def raw(self, content):
        key = sha(content)
        path = self.output / "raw" / (key + ".bin")
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(content)
        return str(path.relative_to(self.output))

    def request(self, url, stage):
        for retry in range(self.config.retries + 1):
            if not self.pace(url):
                self.log(stage=stage, url=url, status="retry_after_deferred", request_sent=False)
                return {"status": "retry_after_deferred", "url": url}
            started = time.monotonic()
            record = {"stage": stage, "url": url, "retry": retry, "request_sent": True}
            response = None
            try:
                response = self.session.get(url, timeout=self.config.timeout, allow_redirects=False, stream=True)
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 10_000_000:
                        raise ValueError("response_too_large")
                    chunks.append(chunk)
                content = b"".join(chunks)
                status = {200: "ok", 401: "authentication_required", 403: "access_denied", 404: "not_found",
                          410: "gone", 429: "rate_limited", 451: "unavailable_legal"}.get(response.status_code, "http_error")
                if response.status_code in {301, 302, 303, 307, 308}:
                    status = "redirect"
                if response.status_code in {401, 403} and any(marker in content.lower() for marker in
                        (b"captcha-delivery.com", b"challenges.cloudflare.com", b"verify you are human")):
                    status = "access_challenge"
                record.update(http_status=response.status_code, status=status, bytes=len(content),
                              raw_path=self.raw(content), content_sha256=sha(content),
                              content_type=response.headers.get("Content-Type", ""), location=response.headers.get("Location"),
                              retry_after=response.headers.get("Retry-After"), representation="http_body_decoded")
                if response.status_code in {429, 503}:
                    value = response.headers.get("Retry-After", "")
                    try:
                        seconds = float(value)
                    except ValueError:
                        try:
                            seconds = parsedate_to_datetime(value).timestamp() - time.time()
                        except (ValueError, TypeError, OverflowError):
                            seconds = 60.0
                    self.state["host_next_request"][urlsplit(url).hostname] = time.time() + max(seconds, self.config.delay)
                    self.save_state()
            except requests.exceptions.SSLError as exc:
                record.update(status="tls_error", error_type=type(exc).__name__)
                content = b""
            except requests.exceptions.Timeout as exc:
                record.update(status="timeout", error_type=type(exc).__name__)
                content = b""
            except requests.exceptions.RequestException as exc:
                record.update(status="network_error", error_type=type(exc).__name__)
                content = b""
            except ValueError as exc:
                record.update(status="response_too_large", error_type=type(exc).__name__)
                content = b""
            except KeyboardInterrupt:
                record.update(status="interrupted", elapsed_seconds=round(time.monotonic() - started, 3))
                self.log(**record)
                raise
            finally:
                if response is not None:
                    response.close()
            record["elapsed_seconds"] = round(time.monotonic() - started, 3)
            self.log(**record)
            if (record["status"] in {"network_error", "timeout"} or record.get("http_status") in {429, 500, 502, 503, 504}) and retry < self.config.retries:
                self.state["host_next_request"][urlsplit(url).hostname] = max(
                    self.state["host_next_request"].get(urlsplit(url).hostname, 0), time.time() + 2 ** (retry + 1))
                self.save_state()
                continue
            return {**record, "content": content}

    def permission(self, url):
        origin = urlunsplit((*urlsplit(url)[:2], "", "", ""))
        if origin not in self.robots:
            response = self.follow(origin + "/robots.txt", "robots", check_robots=False)
            parser = RobotFileParser()
            status = response["status"]
            if response.get("http_status") in {404, 410}:
                parser.parse(["User-agent: *", "Allow: /"])
                status = "valid"
            elif status == "ok":
                text = response["content"].decode("utf-8-sig", errors="replace")
                if re.search(r"(?im)^\s*user-agent\s*:", text) and "<html" not in text.lower():
                    parser.parse(text.splitlines())
                    status = "valid"
                else:
                    status = "invalid"
            self.robots[origin] = parser, status
        parser, status = self.robots[origin]
        if status != "valid":
            return "robots_" + status
        crawl_delay = parser.crawl_delay(AGENT) or 0
        rate = parser.request_rate(AGENT)
        pause = max(self.config.delay, crawl_delay, rate.seconds / rate.requests if rate else 0)
        if pause > self.config.delay:
            host = urlsplit(url).hostname
            self.state["host_next_request"][host] = max(self.state["host_next_request"].get(host, 0), time.time() + pause)
            self.save_state()
        return "allowed" if parser.can_fetch(AGENT, url) else "robots_disallowed"

    def follow(self, url, stage="article", check_robots=True):
        seen = set()
        for _ in range(6):
            try:
                url = normalize_url(url, archive=True)
            except ValueError:
                return {"status": "redirect_outside_scope", "url": url}
            if url in seen:
                return {"status": "redirect_loop", "url": url}
            seen.add(url)
            if check_robots:
                permission = self.permission(url)
                self.log(stage="robots_decision", url=url, status=permission, request_sent=False)
                if permission != "allowed":
                    return {"status": permission, "url": url}
            response = self.request(url, stage)
            if response["status"] != "redirect":
                return response
            url = urljoin(url, response.get("location") or "")
        return {"status": "too_many_redirects", "url": url}

    def render(self, url):
        """Navegador convencional en proceso CLI separado de Jupyter; sin perfil personal."""
        from playwright.sync_api import sync_playwright
        if self.permission(url) != "allowed":
            return {"status": "browser_robots_disallowed", "url": url}
        failure = []
        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel=self.config.browser_channel, headless=True)
            try:
                context = browser.new_context(service_workers="block", user_agent=AGENT)
                page = context.new_page()
                def route_request(route):
                    request = route.request
                    host = urlsplit(request.url).hostname or ""
                    main = request.is_navigation_request() and request.frame == page.main_frame
                    allowed_host = host in WSJ_HOSTS if main else (host.endswith(".wsj.com") or host.endswith(".wsj.net") or host in {"wsj.com", "wsj.net"})
                    if not allowed_host or not request.url.startswith("https://") or request.resource_type in {"image", "media", "font"}:
                        route.abort()
                        if main:
                            failure.append("browser_navigation_outside_scope")
                        return
                    if main and self.permission(request.url) != "allowed":
                        failure.append("browser_robots_disallowed")
                        route.abort()
                        return
                    try:
                        ready = self.pace(request.url)
                    except BudgetExhausted:
                        ready = False
                        failure.append("request_budget_exhausted")
                    if not ready:
                        route.abort()
                        failure.append("retry_after_deferred")
                        return
                    self.log(stage="browser_resource", url=request.url, request_sent=True, status="sent")
                    route.continue_()
                context.route("**/*", route_request)
                page.on("response", lambda response: self.log(stage="browser_response", url=response.url,
                        http_status=response.status, request_sent=False, status="response"))
                response = page.goto(url, wait_until="domcontentloaded", timeout=self.config.timeout * 1000)
                page.wait_for_timeout(1500)
                content = page.content().encode()
                status = "ok" if response and response.status == 200 else "browser_http_denied"
                raw_path = self.raw(content)
                self.log(stage="browser_dom", url=page.url, status=status, raw_path=raw_path,
                         representation="rendered_dom", request_sent=False)
                return {"status": failure[0] if failure else status, "url": page.url, "content": content,
                        "raw_path": raw_path, "http_status": response.status if response else None,
                        "representation": "rendered_dom"}
            finally:
                browser.close()


def validate_snapshot(snapshot, source_url):
    if not snapshot.get("available") or str(snapshot.get("status")) != "200":
        raise ValueError("archive_unavailable")
    url = normalize_url(snapshot["url"], archive=True)
    match = re.match(r"^/web/(\d{14})/(https?://.+)$", urlsplit(url).path)
    if urlsplit(url).hostname != "web.archive.org" or not match:
        raise ValueError("archive_invalid_snapshot")
    if not same_article(match[2], source_url):
        raise ValueError("archive_identity_mismatch")
    return url, match[1]


def acquire(row, fetcher):
    url = normalize_url(row["url"])
    tries = []
    best = {"status": "no_body", "text": "", "word_count": 0, "full_text_verified": False}
    def consume(response, platform_name, expected=url, **extra):
        nonlocal best
        parsed = {"status": response["status"], "text": "", "word_count": 0, "full_text_verified": False}
        if response["status"] == "ok":
            try:
                final_url = response.get("url", expected)
                if platform_name == "internet_archive_wayback":
                    validate_snapshot({"available": True, "status": "200", "url": final_url}, expected)
                elif not same_article(final_url, expected):
                    raise ValueError("identity_mismatch")
                parsed = extract_html(response.get("content", b""), expected, fetcher.config.min_words)
            except ValueError:
                parsed["status"] = "identity_mismatch"
        parsed.update(acquisition_platform=platform_name, retrieved_at_utc=now(), fetched_url=response.get("url"),
                      raw_path=response.get("raw_path"), http_status=response.get("http_status"), **extra)
        tries.append({k: v for k, v in parsed.items() if k != "text"})
        if parsed.get("word_count", 0) > best.get("word_count", 0) or not best.get("text"):
            best = parsed
        return parsed
    # Un HTML local previamente obtenido puede proceder de una exportación autorizada.
    if fetcher.config.local_html:
        local = Path(fetcher.config.local_html) / (row["article_id"] + ".html")
        if local.exists():
            content = local.read_bytes()
            parsed = consume({"status": "ok", "content": content, "url": url,
                              "raw_path": fetcher.raw(content)}, "local_authorized_html")
            if parsed["status"] == "candidate_unverified":
                return {**parsed, "routes": tries}
    response = fetcher.follow(url)
    parsed = consume(response, "wsj_http")
    if parsed["status"] == "candidate_unverified":
        return {**parsed, "routes": tries}
    # Migración del dominio histórico: solo ante URL desaparecida, nunca ante una denegación.
    if urlsplit(url).hostname in {"online.wsj.com", "wsj.com"} and response["status"] in {"not_found", "gone"}:
        response = fetcher.follow(identity(url))
        parsed = consume(response, "wsj_http_modern_domain")
        if parsed["status"] == "candidate_unverified":
            return {**parsed, "routes": tries}
    # Renderizar solo HTML accesible sin señales de restricciones; no reintentar un bloqueo con navegador.
    if fetcher.config.browser and response["status"] == "ok" and parsed["status"] in {"no_body", "short_or_partial"}:
        try:
            parsed = consume(fetcher.render(response["url"]), "wsj_browser")
        except Exception as exc:
            if isinstance(exc, BudgetExhausted):
                raise
            parsed = consume({"status": "browser_error", "url": url}, "wsj_browser", error_type=type(exc).__name__)
        if parsed["status"] == "candidate_unverified":
            return {**parsed, "routes": tries}
    if fetcher.config.wayback:
        api = "https://archive.org/wayback/available?" + urlencode({"url": row["url"],
                    "timestamp": pd.Timestamp(row["csv_date"]).strftime("%Y%m%d")})
        availability = fetcher.follow(api, "archive_availability")
        if availability["status"] == "ok":
            try:
                payload = json.loads(availability["content"])
                snapshot = payload.get("archived_snapshots", {}).get("closest", {})
                replay, timestamp = validate_snapshot(snapshot, url)
                consume(fetcher.follow(replay, "archive_snapshot"), "internet_archive_wayback", capture_timestamp=timestamp)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                tries.append({"acquisition_platform": "internet_archive_wayback", "status": "archive_unavailable_or_invalid",
                              "error_type": type(exc).__name__})
        else:
            tries.append({"acquisition_platform": "internet_archive_wayback", "status": availability["status"]})
    return {**best, "routes": tries}


def run_stage(csv_path, output, start, stage, config=None, max_articles=None, retry_failed=False):
    config = config or Config()
    if config.delay < 0 or config.timeout <= 0 or config.max_requests < 1 or config.retries < 0 or config.min_words < 1:
        raise ValueError("Configuración de límites inválida")
    if max_articles is not None and max_articles < 1:
        raise ValueError("max_articles debe ser positivo")
    csv_path, output = Path(csv_path).resolve(), Path(output).resolve()
    frame = load_input(csv_path)
    subset, end = select_period(frame, start, stage)
    output.mkdir(parents=True, exist_ok=True)
    lock = output / ".download.lock"
    # Una segunda ejecución no debe modificar los mismos checkpoints.
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(now())
    try:
        return _run_locked(csv_path, output, subset, start, end, stage, config, max_articles, retry_failed)
    finally:
        lock.unlink()


def _run_locked(csv_path, output, subset, start, end, stage, config, max_articles, retry_failed):
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:8]
    run_dir = output / "runs" / run_id
    run_dir.mkdir(parents=True)
    for name in ("http.jsonl", "attempts.jsonl"):
        (run_dir / name).touch()
    code_sha = sha(Path(__file__).read_bytes())
    csv_sha = sha(csv_path.read_bytes())
    profile = asdict(config)
    for transient in ("max_requests", "delay", "timeout", "retries"):
        profile.pop(transient)
    signature = sha(json.dumps({"config": profile, "code": code_sha, "csv": csv_sha}, sort_keys=True).encode())
    checkpoint_path = output / "checkpoint.json"
    state = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.exists() else {"documents": {}}
    packages = {}
    for package in ("pandas", "requests", "beautifulsoup4", "trafilatura", "playwright", "truststore"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = None
    git = subprocess.run(["git", "-C", str(Path(__file__).resolve().parents[1]), "-c",
                          f"safe.directory={Path(__file__).resolve().parents[1].as_posix()}",
                          "rev-parse", "HEAD"], capture_output=True, text=True, check=False) if shutil.which("git") else None
    manifest = {"run_id": run_id, "started_at_utc": now(), "schema_version": VERSION,
                "csv_path": str(csv_path), "csv_sha256": csv_sha, "code_sha256": code_sha,
                "git_head": git.stdout.strip() if git and git.returncode == 0 else None,
                "python": platform.python_version(), "platform": platform.platform(), "packages": packages,
                "config": asdict(config), "profile_signature": signature, "stage": stage,
                "start_inclusive": str(pd.Timestamp(start).date()), "end_exclusive": str(end.date()),
                "csv_rows_in_period": len(subset), "unique_articles_in_period": subset.article_id.nunique(),
                "max_articles": max_articles, "retry_failed": retry_failed,
                "date_basis": "CSV calendar date, timezone unknown", "completeness": "always requires review"}
    write_json(run_dir / "manifest.json", manifest)
    fetcher = Fetcher(config, output, run_dir, state)
    result_by_id, skipped, attempted = {}, 0, 0
    interrupted, exhausted = False, False
    unique = subset.drop_duplicates("article_id")
    try:
        for _, row in unique.iterrows():
            article_id = row.article_id
            key = signature + ":" + article_id
            previous = state["documents"].get(key)
            cached = json.loads((output / previous).read_text(encoding="utf-8")) if previous else None
            if cached and (not retry_failed or cached["status"] == "candidate_unverified"):
                result_by_id[article_id] = cached
                skipped += 1
                continue
            if max_articles is not None and attempted >= max_articles:
                continue
            attempted += 1
            try:
                result = acquire(row.to_dict(), fetcher) if row.input_status == "ok" else {
                    "status": row.input_status, "text": "", "word_count": 0, "full_text_verified": False, "routes": []}
            except BudgetExhausted:
                exhausted = True
                break
            except Exception as exc:
                # Un parser defectuoso no elimina una fila ni detiene el resto del lote.
                result = {"status": "processing_error", "text": "", "word_count": 0,
                          "full_text_verified": False, "error_type": type(exc).__name__, "routes": []}
            record = {**result, "article_id": article_id, "run_id": run_id, "original_url": row.url,
                      "csv_date_raw": row.date, "csv_date": str(row.csv_date.date()),
                      "csv_title": row.headlines, "csv_desk": row.desk, "editorial_source": "The Wall Street Journal",
                      "editorial_source_confidence": "csv_attribution_unverified" if row.input_status != "ok" else "domain_inferred",
                      "published_timezone": result.get("published_timezone"), "schema_version": VERSION, "code_sha256": code_sha}
            relative = Path("documents") / article_id / (run_id + ".json")
            write_json(output / relative, record)
            state["documents"][key] = str(relative)
            fetcher.save_state()
            result_by_id[article_id] = record
            append_json(run_dir / "attempts.jsonl", {k: v for k, v in record.items() if k != "text"})
            print(f"[{attempted}] {row.date}: {record['status']} ({record.get('word_count', 0)} palabras)", flush=True)
    except KeyboardInterrupt:
        interrupted = True
    finally:
        fetcher.session.close()
    records = []
    for _, row in subset.iterrows():
        result = result_by_id.get(row.article_id, {})
        records.append({"source_row": row.source_row, "date": row.date, "headlines": row.headlines,
                        "desk": row.desk, "url": row.url, "article_id": row.article_id,
                        "input_status": row.input_status, "status": result.get("status", "pending"),
                        "text": result.get("text", ""), "word_count": result.get("word_count", 0),
                        "full_text_verified": False, "acquisition_platform": result.get("acquisition_platform"),
                        "published_at_raw": result.get("published_at_raw"),
                        "capture_timestamp": result.get("capture_timestamp"),
                        "canonical_url": result.get("canonical_url"), "text_sha256": result.get("text_sha256"),
                        "document_run_id": result.get("run_id")})
    columns = ["source_row", "date", "headlines", "desk", "url", "article_id", "input_status", "status", "text", "word_count",
               "full_text_verified", "acquisition_platform", "published_at_raw", "capture_timestamp", "canonical_url",
               "text_sha256", "document_run_id"]
    export = pd.DataFrame(records, columns=columns)
    export.to_csv(run_dir / "all_rows.csv", index=False, encoding="utf-8-sig")
    export.loc[export.status == "candidate_unverified"].to_csv(run_dir / "articles_candidates.csv", index=False, encoding="utf-8-sig")
    counts = Counter(r["status"] for r in result_by_id.values())
    candidate_count = counts["candidate_unverified"]
    summary = {"run_id": run_id, "run_dir": str(run_dir), "finished_at_utc": now(),
               "csv_rows": len(subset), "unique_articles": len(unique), "cached_articles": skipped,
               "new_articles_started": attempted, "resolved_articles": len(result_by_id),
               "pending_articles": len(unique) - len(result_by_id), "requests_sent": fetcher.count,
               "status_counts_unique_articles": dict(counts), "candidate_articles": candidate_count,
               "candidate_fraction_of_period": candidate_count / len(unique) if len(unique) else None,
               "full_text_verified_count": 0, "request_budget_exhausted": exhausted, "interrupted": interrupted,
               "meaning": "candidates are not certified full articles; denominator is CSV, not WSJ publication universe"}
    write_json(run_dir / "summary.json", summary)
    write_json(output / "latest_run.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--stage", choices=STAGES, default="day")
    parser.add_argument("--max-articles", type=int)
    parser.add_argument("--max-requests", type=int, default=500)
    parser.add_argument("--delay", type=float, default=3)
    parser.add_argument("--timeout", type=float, default=25)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--min-words", type=int, default=80)
    parser.add_argument("--no-wayback", action="store_true")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--browser-channel", default="msedge")
    parser.add_argument("--local-html", type=Path)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--plan", action="store_true", help="Solo calcula tamaños; cero solicitudes remotas")
    args = parser.parse_args()
    if args.plan:
        print(period_plan(load_input(args.csv), args.start).to_string(index=False))
        return
    # Confianza del SO en este proceso, manteniendo verificación TLS.
    import truststore
    truststore.inject_into_ssl()
    config = Config(delay=args.delay, timeout=args.timeout, retries=args.retries, max_requests=args.max_requests,
                    min_words=args.min_words, wayback=not args.no_wayback, browser=args.browser,
                    browser_channel=args.browser_channel, local_html=str(args.local_html) if args.local_html else None)
    summary = run_stage(args.csv, args.output, args.start, args.stage, config, args.max_articles, args.retry_failed)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
