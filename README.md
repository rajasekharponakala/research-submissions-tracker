# GSMArena Phone Finder

A static, no-backend phone finder: search, filter, sort, and compare phones
using specs scraped from [GSMArena](https://www.gsmarena.com/). Same pattern
as before (plain HTML/CSS/JS + a data file, deployed via GitHub Pages) — just
a different dataset and a much richer UI.

**Live:** `https://rajasekharponakala.github.io/research-submissions-tracker/`

> Renaming the actual GitHub repository (Settings → General → Repository name)
> is a manual step only the repo owner can do — I can't do it from here. This
> commit rebrands all the content (title, README, UI copy); once you rename
> the repo on GitHub, update the "Live" URL above and repoint GitHub Pages if
> needed. Suggested name: `gsmarena-phone-finder`.

## What's here

- `index.html` — the site. Search-as-you-type, filters (brand, RAM, storage,
  battery, price, release year), sort, grid/table view toggle, and a
  compare tray (pick up to 3 phones, see them side by side).
- `data/phones.json` — the dataset the site reads. Ships with a small
  hand-curated seed set so the site works out of the box; replace it by
  running the scraper.
- `scraper/scrape_gsmarena.py` — the scraper. See below.
- `.github/workflows/scrape.yml` — optional scheduled job that re-runs the
  scraper and commits an updated `data/phones.json`.
- `.github/workflows/pages.yml` — deploys `index.html` + `data/phones.json`
  to GitHub Pages on push to `main`.

## Scraper

```
cd scraper
pip install -r requirements.txt
python scrape_gsmarena.py --brands samsung,apple,google --max-per-brand 20
```

Two backends:

- **Direct** (default): plain `requests` + BeautifulSoup against
  `gsmarena.com`. Checks `robots.txt` before fetching, rate-limits requests
  (`--delay`, default 2s), and caches fetched pages under `.cache/` so a
  re-run is resumable and doesn't re-hit pages you already have.
- **Firecrawl** (`--backend firecrawl`, requires `FIRECRAWL_API_KEY`): routes
  fetches through the [Firecrawl](https://firecrawl.dev) API instead of
  fetching gsmarena.com directly. Useful if you're running somewhere with
  restricted egress to gsmarena.com but can still reach `api.firecrawl.dev`
  (e.g. this sandbox — direct access to gsmarena.com is blocked here, so the
  script itself was written and reviewed but not run against the live site
  from this session; test a small `--max-per-brand` run yourself before
  trusting a full crawl).

Full options: `python scrape_gsmarena.py --help`.

### Be a good citizen about this

GSMArena is a business, not a public dataset. This scraper is for personal/
educational use:

- It checks `robots.txt` and refuses to fetch disallowed paths.
- Default rate limit is conservative (2s between requests) — don't lower it
  for a full-site crawl.
- Don't redistribute scraped images; `data/phones.json` doesn't store image
  URLs by default for exactly this reason (the UI renders a placeholder
  avatar instead). If you add images yourself, keep the source `url` field
  on each phone so it always links back and credits GSMArena.
- Re-scraping the whole site on every push is wasteful; that's why the
  scheduled workflow runs weekly, not on every commit.

## Contribute

Data comes from the scraper, not hand edits — if a phone's specs look wrong,
open an issue with the GSMArena URL rather than editing `data/phones.json`
directly (a manual edit will just get overwritten by the next scrape).

## Deploy

Pushes to `main` touching `index.html` or `data/phones.json` auto-deploy via
`.github/workflows/pages.yml` (Settings → Pages → Source: GitHub Actions).
