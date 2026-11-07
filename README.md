# MGIMO Leaders Corpus — historical 2026 only

An academic public-source corpus for Donald Trump, Vladimir Putin and Volodymyr Zelenskyy. **Historical period: 2026-01-01 to the UTC date of manual execution, inclusive.** No 2025 material, no continuous polling, no scheduled jobs and no GPU required.

## What gets collected

| Leader | Primary data source | Text type | Authorship caution |
|---|---|---|---|
| Trump | [CNN's Truth Social JSON archive](https://ix.cnn.io/data/truth-social/truth_archive.json) | Social posts | Secondary archive; repost flags may be incomplete |
| Putin | [Kremlin transcripts](https://kremlin.ru/events/president/transcripts) + [Telegram press service](https://t.me/s/news_kremlin) | Speeches/interviews, institutional posts | Putin turns separated where possible; Telegram is **press-office text**, not personal speech |
| Zelenskyy | [president.gov.ua speeches](https://www.president.gov.ua/news/speeches) + [Telegram public channel](https://t.me/s/V_Zelenskiy_official) | Official speeches and channel posts | Channel authorship is unverified at the individual-post level |

Data includes original URLs, source, speaker/attribution class, date and full extracted text. For Putin and Zelenskyy, the one-off loader attempts both official archives and publicly previewable Telegram channels. Actual coverage and document count are **unknown until a successful run**. It must not be described as a complete corpus before an independent archive audit.

## Run locally (one-off)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements-dev.txt
pytest -q
python -m corpus2026.cli backfill --source all --since 2026-01-01 --until $(date -u +%F)
python -m corpus2026.cli build-site
python -m http.server 8000 --directory docs
```

Open <http://localhost:8000>. `--until` must not be in the future. Start with `--max-pages 2` for an inexpensive smoke test; **that is not a complete backfill**. A full attempt can take a while because pages are fetched conservatively. Running `build-site` does not access external sites.

## GitHub repository / GitHub Pages

This project lives in the **root of the default `main` branch** of `2001092236/Emotional-tone-of-the-text` because the connected GitHub integration did not allow creating a separate repository. The complete original `main` was saved *before any replacement* in `archive/emotional-tone-original-main-2026-11-08` (commit `6aefbf4c61d85331dbb2ee150afd4d40fcd56b6c`). Do not delete the archive branch. Renaming or migrating to a dedicated repo later is recommended.

### Hosting (one-time action in GitHub Settings)

The ready-to-serve website is under `docs/`. GitHub Pages **must be enabled in Settings → Pages** by a repository administrator; the GitHub connector cannot change that setting. The simplest way:

1. Open **Settings → Pages → Build and deployment**.
2. Choose **Deploy from a branch → main → /docs → Save**. The HTML/CSS/JS site will publish without any compute server or GPU. It initially shows zero documents, honestly, until the one-off loader completes.
3. Alternatively choose **GitHub Actions** as the publishing source: `.github/workflows/pages.yml` is already installed at repository root, triggers on pushes to `docs/` and can be rerun manually. The workflow uses the Pages artifact action.

Do **not** claim that the public URL works until GitHub reports a successful Pages deployment. GitHub Pages can expose the site publicly even if a repository is private.

### One-time backfill (no schedules)

1. Open **Actions → One-time 2026 historical backfill → Run workflow**.
2. Start with `source=trump` or `source=all` and `max_pages=2` to validate external connectivity; that is a small smoke test, not a full corpus.
3. For full historical collection run again with `source=all`, `max_pages=110`. It downloads only dated documents from 2026-01-01 to current UTC date and writes `data/2026/*.jsonl`, `docs/data/*.json` and `data/2026/run_report.json` to `main`.
4. Check `run_report.json` for errors and missing pages. No source is considered *complete* until audited; CI reports partial results explicitly. A completed backfill triggers a Pages workflow, but GitHub still needs Pages to be enabled once in Settings.

No external server, cron, GPU process, paid API or token is needed for this first version. Nothing runs daily or in real time.

### Data as a database

`data/2026/{trump,putin,zelenskyy}.jsonl` is versioned, UTF-8, deduplicated by `source:external_id`, and restricted by the 2026 date gate. This lightweight append/merge approach is suited to a first pilot. GitHub stores every historical version in commits; the generated `docs/data/` files only power the static viewer. **No GPU host required.** Avoid storing sessions, API keys, private material or any non-public dataset in a public repository.

## Caveats and errors

- **Site access is not fully validated yet.** If an archive is blocked by `robots.txt`, unavailable to GitHub's IP ranges, anti-bot protected, or rate-limited, the pipeline stops or reports the individual source as `error`/`partial`; it never evades access controls.
- `robots.txt` is checked once per origin; HTTP 401/403/429 is treated as an access denial. Telegram public `/s/` pagination is **best effort**, with missing/media-only posts and rate limits possible; its coverage must be audited before analysis.
- Every article without a usable publication date is skipped; we never guess 2026 from the search page.
- The `run_report.json` indicates whether source coverage was verified; by default this is false even when the collector returns no error (pagination and editorial completeness need independent validation).
- Authors and speechwriters may differ; a prepared institutional speech should not be treated as spontaneous personal expression.
- Licenses, site terms, copyright and applicable law must be reviewed before sharing or using the scraped full texts for ML. If broad republication is not permitted, keep just metadata + original URLs public, and maintain texts in authorized restricted storage.

## Tests

`pytest -q` runs offline parsing and date-guard tests. **Network tests, complete 2026 backfill and live GitHub Pages deployment are separate operational steps.**
