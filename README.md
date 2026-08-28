# Cala Montgó Window — Webcam Archiver 1

Archiving public webcam frames of Cala Montgó, Costa Brava.

Archives a public webcam feed of Cala Montgó (Costa Brava, Spain) every ~5
minutes, via a scheduled GitHub Actions workflow. This is Phase 1 of a
longer-term project (a physical display showing this feed at home); the
display itself is out of scope here.

Source: `https://webcamscostabrava.com/webcams/webcam-montgo.php`
(operated by Hotel Can Miquel, part of the webcamscostabrava.com network).
This endpoint returns the raw JPEG directly (confirmed via header
inspection: `Content-Type: image/jpeg`, `Cache-Control: max-age=0,no-store`
— no cache-busting query param needed, no `User-Agent` strictly required,
though the script sends one anyway out of politeness).

## Repo layout

```
images/YYYY/MM/DD/HHMMSS.jpg   one file per successful capture (UTC-based path)
metadata.jsonl                  one JSON line per successful capture
failures.jsonl                  one JSON line per failed capture attempt
scripts/capture.py               the capture script
.github/workflows/capture.yml    the scheduled workflow
```

Each `metadata.jsonl` line looks like:

```json
{"timestamp_utc": "2026-08-28T14:20:03Z", "timestamp_local": "2026-08-28T16:20:03+02:00", "path": "images/2026/08/28/142003.jpg", "size_bytes": 84213, "sha256": "...", "http_status": 200, "source_url": "..."}
```

A failed attempt (bad status, wrong content-type, or too-small body) is
logged to `failures.jsonl` instead — no image or metadata entry is written,
and the workflow still exits successfully (no red X for a flaky source).

## Setup

**This repo must be public.** GitHub Actions on public repos gets free,
unlimited minutes on standard hosted runners; private repos only get a
capped monthly quota that a 5-minute cron would burn through in about a
week. To check/set: Settings → General → Danger Zone → Change repository
visibility.

Also check **Settings → Actions → General → Workflow permissions** and make
sure "Read and write permissions" is selected (or rely on the
`permissions: contents: write` set in the workflow file itself — but if
pushes still fail with a permissions error, this setting is the first
place to look).

## Changing the schedule

Edit the `cron` line in `.github/workflows/capture.yml`:

```yaml
schedule:
  - cron: '*/5 * * * *'   # every 5 minutes
```

GitHub Actions cron is best-effort — expect a few minutes of drift,
especially during busy periods. That's expected and not worth chasing.

## If commits stop appearing

1. **Actions tab** — check if the workflow run is red/failing, and read the
   log.
2. **Permissions** — see the Workflow permissions setting above.
3. **60-day inactivity disabling** — GitHub auto-disables scheduled
   workflows in repos with no activity for 60 days. Since this workflow
   itself commits every run, this shouldn't happen while it's working, but
   if it's ever been broken for a couple of months, check Actions tab for a
   "workflow disabled" banner and manually re-enable it.
4. **Manual test** — run the workflow manually via the "Run workflow" button
   (`workflow_dispatch`) to isolate scheduling issues from script issues.

## Known, accepted tradeoffs

- Repo size grows over time (~30-80 MB/day) — no pruning yet, that's future
  work.
- No deduplication of identical consecutive frames yet — every successful
  fetch is saved regardless of whether the source image changed.
- No timelapse/video generation yet — the data is there for it later.
