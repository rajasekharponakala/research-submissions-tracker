#!/usr/bin/env python3
"""
GSMArena phone finder scraper.

Two fetch backends:
  --backend direct     plain HTTP requests to gsmarena.com (default)
  --backend firecrawl   routes fetches through the Firecrawl API
                         (https://firecrawl.dev), needs FIRECRAWL_API_KEY.
                         Useful when direct egress to gsmarena.com is blocked
                         but api.firecrawl.dev is reachable.

Usage:
  python scrape_gsmarena.py --brands samsung,apple --max-per-brand 20
  python scrape_gsmarena.py --brands all --delay 3 --output ../data/phones.json
  FIRECRAWL_API_KEY=... python scrape_gsmarena.py --backend firecrawl --brands google

This has been written and reviewed against GSMArena's documented page
structure but NOT run against the live site (this environment's egress to
gsmarena.com is blocked). Do a small `--max-per-brand 3` test run before
trusting a full crawl, and re-check robots.txt / page markup if it breaks.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.gsmarena.com/"
USER_AGENT = "gsmarena-phone-finder-bot/1.0 (personal/educational project; see repo README)"
CACHE_DIR = Path(__file__).parent / ".cache"


class RobotsGate:
    """Refuses to fetch any path robots.txt disallows for our user-agent."""

    def __init__(self, base_url, session):
        self.rp = urllib.robotparser.RobotFileParser()
        try:
            resp = session.get(urljoin(base_url, "/robots.txt"), timeout=15)
            self.rp.parse(resp.text.splitlines())
        except requests.RequestException:
            self.rp = None  # fail open on fetch error, fail closed on rule match

    def allowed(self, url):
        if self.rp is None:
            return True
        return self.rp.can_fetch(USER_AGENT, url)


class DirectFetcher:
    def __init__(self, delay, use_cache=True):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.delay = delay
        self.use_cache = use_cache
        self.robots = RobotsGate(BASE, self.session)
        if use_cache:
            CACHE_DIR.mkdir(exist_ok=True)

    def _cache_path(self, url):
        return CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".html")

    def get(self, url):
        if not self.robots.allowed(url):
            raise PermissionError(f"robots.txt disallows fetching {url}")
        cp = self._cache_path(url) if self.use_cache else None
        if cp and cp.exists():
            return cp.read_text(encoding="utf-8")
        time.sleep(self.delay)
        resp = self.session.get(url, timeout=20)
        resp.raise_for_status()
        if cp:
            cp.write_text(resp.text, encoding="utf-8")
        return resp.text


class FirecrawlFetcher:
    def __init__(self, delay, use_cache=True):
        self.api_key = os.environ.get("FIRECRAWL_API_KEY")
        if not self.api_key:
            sys.exit("FIRECRAWL_API_KEY is required for --backend firecrawl")
        self.delay = delay
        self.use_cache = use_cache
        if use_cache:
            CACHE_DIR.mkdir(exist_ok=True)

    def _cache_path(self, url):
        return CACHE_DIR / ("fc_" + hashlib.sha1(url.encode()).hexdigest() + ".html")

    def get(self, url):
        cp = self._cache_path(url) if self.use_cache else None
        if cp and cp.exists():
            return cp.read_text(encoding="utf-8")
        time.sleep(self.delay)
        resp = requests.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"url": url, "formats": ["html"]},
            timeout=60,
        )
        resp.raise_for_status()
        html = resp.json()["data"]["html"]
        if cp:
            cp.write_text(html, encoding="utf-8")
        return html


def get_brands(fetcher):
    """Returns [(brand_name, brand_url)] from the makers index."""
    html = fetcher.get(urljoin(BASE, "makers.php3"))
    soup = BeautifulSoup(html, "html.parser")
    brands = []
    for a in soup.select("div.st-text ul li a") or soup.select("table a"):
        name = a.get_text(strip=True)
        name = re.sub(r"\s*\d+\s*devices?$", "", name, flags=re.I).strip()
        href = a.get("href")
        if name and href:
            brands.append((name, urljoin(BASE, href)))
    return brands


def get_phone_links(fetcher, brand_url, max_phones):
    """Paginates a brand's phone list, returns up to max_phones detail URLs."""
    links, next_url, seen_pages = [], brand_url, set()
    while next_url and next_url not in seen_pages and len(links) < max_phones:
        seen_pages.add(next_url)
        html = fetcher.get(next_url)
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("div.makers ul li a"):
            href = a.get("href")
            if href and href not in links:
                links.append(urljoin(BASE, href))
            if len(links) >= max_phones:
                break
        nav = soup.select_one("div.nav-pages a.pages-next, a.pages-next")
        next_url = urljoin(BASE, nav["href"]) if nav and nav.get("href") else None
    return links[:max_phones]


def parse_specs_table(soup):
    """Flattens GSMArena's #specs-list tables into {category: {label: value}}."""
    specs = {}
    for table in soup.select("#specs-list table"):
        category = None
        cat_th = table.select_one("th")
        if cat_th:
            category = cat_th.get_text(strip=True)
        for row in table.select("tr"):
            label_el = row.select_one("td.ttl")
            value_el = row.select_one("td.nfo")
            if not label_el or not value_el:
                continue
            label = label_el.get_text(strip=True) or category or "?"
            value = value_el.get_text(" ", strip=True)
            specs.setdefault(category or "Misc", {})[label] = value
    return specs


def first_int(text):
    m = re.search(r"\d+", (text or "").replace(",", ""))
    return int(m.group()) if m else None


def parse_ram_storage(memory_specs):
    """'Internal' rows look like '256GB 12GB RAM, 512GB 16GB RAM, ...'."""
    raw = memory_specs.get("Internal", "")
    rams, storages = set(), set()
    for chunk in raw.split(","):
        storage_m = re.search(r"(\d+)\s*GB(?!\s*RAM)", chunk)
        ram_m = re.search(r"(\d+)\s*GB\s*RAM", chunk)
        if storage_m:
            storages.add(int(storage_m.group(1)))
        if ram_m:
            rams.add(int(ram_m.group(1)))
    return sorted(rams), sorted(storages)


def normalize(url, name, raw_specs):
    launch = raw_specs.get("Launch", {})
    display = raw_specs.get("Display", {})
    platform = raw_specs.get("Platform", {})
    memory = raw_specs.get("Memory", {})
    battery = raw_specs.get("Battery", {})
    main_cam = raw_specs.get("Main Camera", {})
    selfie_cam = raw_specs.get("Selfie camera", {})
    body = raw_specs.get("Body", {})
    misc = raw_specs.get("Misc", {})

    year_m = re.search(r"20\d{2}", launch.get("Announced", "") or launch.get("Status", ""))
    size_m = re.search(r"([\d.]+)\s*inches", display.get("Size", ""))
    rams, storages = parse_ram_storage(memory)
    battery_mah = first_int(battery.get("Type", ""))
    charge_m = re.search(r"(\d+)W", battery.get("Charging", ""))
    weight_m = re.search(r"(\d+)\s*g", body.get("Weight", ""))
    price_m = re.search(r"\$\s?([\d,]+)", misc.get("Price", ""))
    brand, _, model = name.partition(" ")

    return {
        "id": re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"),
        "brand": brand,
        "model": model or name,
        "releaseYear": int(year_m.group()) if year_m else None,
        "url": url,
        "displayInches": float(size_m.group(1)) if size_m else None,
        "displayType": display.get("Type"),
        "chipset": platform.get("Chipset"),
        "ramGB": rams,
        "storageGB": storages,
        "batteryMah": battery_mah,
        "chargingW": int(charge_m.group(1)) if charge_m else None,
        "mainCameraMP": first_int(main_cam.get("Single") or main_cam.get("Triple") or main_cam.get("Quad") or main_cam.get("Dual")),
        "selfieCameraMP": first_int(selfie_cam.get("Single")),
        "weightG": int(weight_m.group(1)) if weight_m else None,
        "priceUSD": int(price_m.group(1).replace(",", "")) if price_m else None,
        "os": platform.get("OS"),
    }


def scrape_phone(fetcher, url):
    html = fetcher.get(url)
    soup = BeautifulSoup(html, "html.parser")
    name_el = soup.select_one("h1.specs-phone-name-title") or soup.select_one("h1")
    name = name_el.get_text(strip=True) if name_el else url
    raw_specs = parse_specs_table(soup)
    return normalize(url, name, raw_specs)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brands", default="samsung,apple,google", help="comma-separated brand names, or 'all'")
    ap.add_argument("--max-per-brand", type=int, default=20)
    ap.add_argument("--delay", type=float, default=2.0, help="seconds between requests")
    ap.add_argument("--backend", choices=["direct", "firecrawl"], default="direct")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--output", default=str(Path(__file__).parent.parent / "data" / "phones.json"))
    args = ap.parse_args()

    fetcher = (FirecrawlFetcher if args.backend == "firecrawl" else DirectFetcher)(
        delay=args.delay, use_cache=not args.no_cache
    )

    print("Fetching brand index...", file=sys.stderr)
    all_brands = get_brands(fetcher)
    if not all_brands:
        sys.exit("Could not find any brands — GSMArena's markup may have changed. See scraper docstring.")

    wanted = None if args.brands.strip().lower() == "all" else {b.strip().lower() for b in args.brands.split(",")}
    brands = [(n, u) for n, u in all_brands if wanted is None or n.lower() in wanted]
    if not brands:
        sys.exit(f"No brands matched --brands={args.brands!r}. Known brands include: "
                  + ", ".join(n for n, _ in all_brands[:15]) + " ...")

    phones = []
    for brand_name, brand_url in brands:
        print(f"Brand: {brand_name}", file=sys.stderr)
        try:
            links = get_phone_links(fetcher, brand_url, args.max_per_brand)
        except PermissionError as e:
            print(f"  skipped ({e})", file=sys.stderr)
            continue
        for url in links:
            try:
                phone = scrape_phone(fetcher, url)
                phones.append(phone)
                print(f"  + {phone['brand']} {phone['model']}", file=sys.stderr)
            except PermissionError as e:
                print(f"  skipped {url} ({e})", file=sys.stderr)
            except Exception as e:  # keep going on a single bad page
                print(f"  failed {url}: {e}", file=sys.stderr)

    out = {
        "scrapedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": BASE,
        "note": f"Scraped via --backend {args.backend}.",
        "phones": phones,
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(phones)} phones to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
