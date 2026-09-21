# Research Submissions Tracker

Community countdowns for AI/NLP/Speech/Vision venue deadlines. Static site, no backend.

**Live:** `https://rajasekharponakala.github.io/research-submissions-tracker/`

## Contribute
Edit `deadlines.txt` (one pipe-separated row per venue) and open a PR:

```
Name|Location|ConfStart|PaperDeadline|Area|URL
```

`PaperDeadline` as `YYYY-MM-DD` (AoE) or `TBD (...)`. Keep the CFP link official.

## Deploy
Pushes to `main` touching `index.html`/`deadlines.txt` auto-deploy via `.github/workflows/pages.yml` (Settings → Pages → Source: GitHub Actions, one-time setup).

## Sources
Official CFPs + WikiCFP. Always verify against the linked CFP before submitting.
