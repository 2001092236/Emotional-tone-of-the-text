# MGIMO Leaders Corpus — historical 2026 only

An academic public-source corpus for Donald Trump, Vladimir Putin and Volodymyr Zelenskyy. **Historical period: 2026-01-01 to the UTC date of manual execution, inclusive.** No 2025 material, no continuous polling, no scheduled jobs and no GPU required.

## What gets collected

| Leader | Primary data source | Text type | Authorship caution |
|---|---|---|---|
| Trump | [CNN's Truth Social JSON archive](https://ix.cnn.io/data/truth-social/truth_archive.json) | Social posts | Secondary archive; repost flags may be incomplete |
| Putin | [Kremlin transcripts](https://kremlin.ru/events/president/transcripts) | Speeches/interviews | Attempts to isolate Putin's turns; otherwise marks `mixed_unverified` |
| Zelenskyy | [president.gov.ua speeches](https://www.president.gov.ua/news/speeches) | Official speeches/addresses | Published prepared speeches, not necessarily individually authored |

Data includes original URLs, source, speaker/attribution class, date and full extracted text. Actual coverage and document count are **unknown until a successful run**. It must not be described as a complete corpus before an independent archive audit.

## Run locally (one-off)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements-dev.txt
pytest -q
python -m corpus2026.cli backfill --source all --since 2026-01-01 --until 2026-11-08
python -m corpus2026.cli build-site
python -m http.server 8000 --directory site
```

Open <http://localhost:8000>. `--until` must not be in the future. Start with `--max-pages 2` for an inexpensive smoke test; **that is not a complete backfill**. A full attempt can take a while because pages are fetched conservatively. Running `build-site` does not access external sites.

## Deploy through GitHub, with zero permanent server usage

1. Put these files at the root of a **new public GitHub repository** (not a subfolder of another project); keep the repository public only if rights permit republishing the full text.
2. **Actions → One-time 2026 historical backfill → Run workflow**. It downloads once and commits JSONL to `data/2026/`; source errors remain visible in `data/2026/run_report.json`. Use `max_pages=110` for a full attempt. No `schedule` triggers exist.
3. **Settings → Pages → Source → GitHub Actions**.
4. **Actions → Publish static 2026 corpus viewer (manual) → Run workflow**. GitHub Pages publishes the `site/` folder without Node, a database server or GPU. A repository permission setting may need adjustment if the Actions commit is refused.
5. The static site loads monthly JSON chunks directly from GitHub Pages. It never queries a local server.

### Data as a database

`data/2026/{trump,putin,zelenskyy}.jsonl` is versioned, UTF-8, deduplicated by `source:external_id`, and restricted by the 2026 date gate. This lightweight append/merge approach is suited to a first pilot. GitHub stores every historical version in commits; the generated `site/data/` files only power the static viewer. **No GPU host required.** Avoid storing sessions, API keys, private material or any non-public dataset in a public repository.

## Caveats and errors

- **Site access is not fully validated yet.** If an archive is blocked by `robots.txt`, unavailable to GitHub's IP ranges, anti-bot protected, or rate-limited, the pipeline stops or reports the individual source as `error`/`partial`; it never evades access controls.
- `robots.txt` is checked once per origin; HTTP 401/403/429 is treated as an access denial.
- Every article without a usable publication date is skipped; we never guess 2026 from the search page.
- The `run_report.json` indicates whether source coverage was verified; by default this is false even when the collector returns no error (pagination and editorial completeness need independent validation).
- Authors and speechwriters may differ; a prepared institutional speech should not be treated as spontaneous personal expression.
- Licenses, site terms, copyright and applicable law must be reviewed before sharing or using the scraped full texts for ML. If broad republication is not permitted, keep just metadata + original URLs public, and maintain texts in authorized restricted storage.

## Tests

`pytest -q` runs offline parsing and date-guard tests. **Network tests, complete 2026 backfill and live GitHub Pages deployment are separate operational steps.**
