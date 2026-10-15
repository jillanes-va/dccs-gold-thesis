"""Piloto auditable de noticias 2026. Solo páginas públicas permitidas por robots.txt.

Uso: python pilot.py --max-per-source 15 --delay 3
"""
import argparse
import csv
import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.robotparser import RobotFileParser

import requests
import trafilatura
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

AGENT = "AcademicNewsPilot/0.1 (+research; respectful robots; contact: j.illanesv@udd.cl)"
SOURCES = {
    "yahoo": {
        "home": "https://es.finance.yahoo.com/",
        "seeds": ["https://es.finance.yahoo.com/sitemap/2026_01_15/",
                  "https://es.finance.yahoo.com/sitemap/2026_04_15/",
                  "https://es.finance.yahoo.com/sitemap/2026_07_15/",
                  "https://es.finance.yahoo.com/sitemap/2026_10_14/"],
        "patterns": [r"/news/", r"/noticias/"],
    },
    "reuters": {
        "home": "https://www.reuters.com/",
        "seeds": ["https://www.reuters.com/business/", "https://www.reuters.com/markets/"],
        "patterns": [r"/world/", r"/business/", r"/markets/", r"/sustainability/"],
    },
    "benzinga": {
        "home": "https://www.benzinga.com/",
        "seeds": ["https://www.benzinga.com/news", "https://www.benzinga.com/markets"],
        "patterns": [r"/news/", r"/markets/", r"/commodities/"],
    },
    "bloomberg": {
        "home": "https://www.bloomberg.com/",
        "seeds": ["https://www.bloomberg.com/markets", "https://www.bloomberg.com/economics"],
        "patterns": [r"/news/articles/", r"/news/features/"],
    },
}
FIELDS = ["platform", "discovery_url", "url", "http_status", "result", "published_at", "title", "author", "publisher", "language", "word_count", "text", "error"]

class Fetcher:
    def __init__(self, delay, timeout):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": AGENT, "Accept-Language": "en-US,en;q=0.8,es;q=0.6"})
        self.delay, self.timeout = delay, timeout
        self.robots = {}
        self.last = {}

    def permitted(self, url):
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False
        host = f"{p.scheme}://{p.netloc}"
        if host not in self.robots:
            rp = RobotFileParser()
            rp.set_url(host + "/robots.txt")
            try:
                r = self.session.get(host + "/robots.txt", timeout=self.timeout)
                if r.status_code != 200:
                    self.robots[host] = None  # fail closed
                else:
                    rp.parse(r.text.splitlines())
                    self.robots[host] = rp
            except requests.RequestException:
                self.robots[host] = None
        rp = self.robots[host]
        return rp is not None and rp.can_fetch(AGENT, url)

    def get(self, url):
        if not self.permitted(url):
            return None, "robots_disallowed_or_unavailable", None
        host = urlparse(url).netloc
        wait = max(0, self.delay - (time.monotonic() - self.last.get(host, -1e10)))
        if wait:
            time.sleep(wait)
        self.last[host] = time.monotonic()
        try:
            r = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            # check redirected target too: if forbidden, do not process body
            if r.url != url and not self.permitted(r.url):
                return None, "redirect_robots_disallowed", r.status_code
            if r.status_code in (401, 403, 429):
                return None, "blocked_or_rate_limited", r.status_code
            if r.status_code != 200:
                return None, "http_error", r.status_code
            if "html" not in r.headers.get("Content-Type", "").lower():
                return None, "not_html", r.status_code
            return r.text, "ok", r.status_code
        except requests.RequestException as exc:
            return None, "request_error:" + type(exc).__name__, None


def clean_url(url):
    url, _ = urldefrag(url)
    return url.split("?", 1)[0].rstrip("/")


def article_links(html, base, patterns, allowed_host):
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for a in soup.select("a[href]"):
        u = clean_url(urljoin(base, a["href"]))
        if urlparse(u).netloc != allowed_host:
            continue
        if any(re.search(p, urlparse(u).path) for p in patterns):
            if u != clean_url(base):
                found.append(u)
    return list(dict.fromkeys(found))


def jsonld_nodes(soup):
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(tag.string or tag.get_text())
        except (ValueError, TypeError):
            continue
        todo = [value]
        while todo:
            v = todo.pop()
            if isinstance(v, list):
                todo.extend(v)
            elif isinstance(v, dict):
                yield v
                todo.extend(v.get("@graph", []) if isinstance(v.get("@graph"), list) else [])


def get_meta(soup, *keys):
    for k in keys:
        node = soup.find("meta", attrs={"property": k}) or soup.find("meta", attrs={"name": k})
        if node and node.get("content"):
            return node["content"].strip()
    return ""


def parse_date(value):
    if not value:
        return ""
    try:
        return dateparser.parse(value).isoformat()
    except (ValueError, OverflowError, TypeError):
        return ""


def extract(html, url):
    soup = BeautifulSoup(html, "html.parser")
    article = next((x for x in jsonld_nodes(soup) if "Article" in str(x.get("@type", "")) or "NewsArticle" in str(x.get("@type", ""))), {})
    metadata = trafilatura.extract_metadata(html)
    body = trafilatura.extract(html, url=url, include_comments=False, include_tables=False, favor_precision=True) or ""
    title = (article.get("headline") or get_meta(soup, "og:title", "twitter:title") or (metadata.title if metadata else "") or "")
    published = parse_date(article.get("datePublished") or get_meta(soup, "article:published_time", "datePublished", "pubdate") or (metadata.date if metadata else ""))
    author = article.get("author", "")
    if isinstance(author, list):
        author = ", ".join(x.get("name", "") if isinstance(x, dict) else str(x) for x in author)
    elif isinstance(author, dict):
        author = author.get("name", "")
    publisher = article.get("publisher", "")
    if isinstance(publisher, dict):
        publisher = publisher.get("name", "")
    return {"published_at": published, "title": str(title), "author": str(author),
            "publisher": str(publisher or get_meta(soup, "article:publisher") or ""),
            "language": (soup.html.get("lang", "") if soup.html else ""),
            "word_count": len(body.split()), "text": body}


def within_2026(value):
    try:
        d = dateparser.parse(value).date()
        return date(2026, 1, 1) <= d <= date(2026, 10, 15)
    except (ValueError, TypeError, OverflowError):
        return False


def run(args):
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    fetcher = Fetcher(args.delay, args.timeout)
    all_rows = []
    seen = set()
    for platform in args.sources:
        config = SOURCES[platform]
        count = 0
        for seed in config["seeds"]:
            html, status, code = fetcher.get(seed)
            all_rows.append(dict(platform=platform, discovery_url=seed, url=seed,
                                 http_status=code or "", result="discovery_" + status))
            if not html:
                continue
            links = article_links(html, seed, config["patterns"], urlparse(config["home"]).netloc)
            print(f"{platform}: {seed} -> {len(links)} URLs candidatas")
            for url in links:
                if count >= args.max_per_source:
                    break
                if url in seen:
                    continue
                seen.add(url)
                count += 1
                body_html, result, http_code = fetcher.get(url)
                row = dict(platform=platform, discovery_url=seed, url=url, http_status=http_code or "", result=result)
                if body_html:
                    try:
                        row.update(extract(body_html, url))
                        if not row["published_at"]:
                            row["result"] = "missing_date"
                        elif not within_2026(row["published_at"]):
                            row["result"] = "outside_period"
                        elif row["word_count"] < args.min_words:
                            row["result"] = "short_or_empty"
                        else:
                            row["result"] = "success"
                    except Exception as exc:
                        row["result"] = "extraction_error"
                        row["error"] = type(exc).__name__ + ": " + str(exc)[:250]
                all_rows.append(row)
                print(f"  [{row['result']}] {url[:100]}")
            if count >= args.max_per_source:
                break
    with (out / "attempts.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)
    # Persist only successful texts in JSONL, all attempts remain auditable in CSV.
    with (out / "articles.jsonl").open("w", encoding="utf-8") as f:
        for r in all_rows:
            if r.get("result") == "success":
                rec = {k: r.get(k, "") for k in FIELDS if k != "error"}
                rec["text_sha256"] = hashlib.sha256(rec["text"].encode()).hexdigest()
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    summary = defaultdict(Counter)
    for r in all_rows:
        summary[r["platform"]][r["result"]] += 1
    with (out / "summary.json").open("w", encoding="utf-8") as f:
        json.dump({p: dict(counts) for p, counts in summary.items()}, f, indent=2, ensure_ascii=False)
    print("\nResumen:")
    for p, counts in summary.items():
        print(p, dict(counts))
    print("Archivos:", out.resolve())

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", nargs="+", choices=list(SOURCES), default=list(SOURCES))
    parser.add_argument("--max-per-source", type=int, default=12)
    parser.add_argument("--min-words", type=int, default=100)
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--output", default="output")
    run(parser.parse_args())
