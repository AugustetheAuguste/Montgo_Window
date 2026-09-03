# webcam-montgo

Archives a public webcam feed of Cala Montgó (Costa Brava, Spain) every 5
minutes as a Docker container on the home server. Runs continuously; no
GitHub Actions involved (see project history if curious why that was
dropped).

Source: `https://webcamscostabrava.com/webcams/webcam-montgo.php`
(operated by Hotel Can Miquel, part of the webcamscostabrava.com network).
Confirmed via header inspection: `Content-Type: image/jpeg`,
`Cache-Control: max-age=0,no-store` (no cache-busting param needed).
1280×720 JPEGs, ~80KB each.

## Where this repo lives

This project assumes a parent tree:

```
~/server/
├── shared/status.py             ← shared by every project on the box, not in this repo
├── webcam-montgo/                ← this repo
│   ├── compose.yml
│   ├── Dockerfile
│   ├── requirements.txt
│   └── scripts/capture.py
├── data/
│   └── webcam-montgo/            ← bind-mounted into the container as /data
└── .env                          ← HEARTBEAT_URL etc, never committed
```

**`shared/status.py` is delivered inside this repo for now** (at
`shared/status.py`) because it didn't exist anywhere yet. Move it to
`~/server/shared/status.py` when you set up the tree — it's meant to be
shared by every future project, not tracked inside this one.

The Docker build context is `~/server` (the parent directory), not this
project directory, specifically so `shared/status.py` can be copied into
the image. This means `docker compose build` must be run with `..` as
context — the provided `compose.yml` already does this — and a
`~/server/.dockerignore` excluding `data/`, `.env`, `.git` is required so
builds don't ship the growing archive to the Docker daemon.

## Start / stop

```
cd ~/server/webcam-montgo
docker compose up -d --build
docker compose logs -f       # tail logs (Dozzle will own this later)
docker compose down          # stop, writes state: "stopped" to status.json
```

## Where the data lives

`~/server/data/webcam-montgo/`:

- `images/YYYY/MM/DD/HHMMSS.jpg` — one file per successful capture, path
  derived from the UTC timestamp.
- `metadata.jsonl` — one line per successful capture.
- `failures.jsonl` — one line per failed attempt (bad status, wrong
  content-type, body too small). No image or metadata line is written for
  a failure; the loop continues.
- `status.json` — the schema-v1 status contract. See the task brief Part 2
  for the full field reference.

## What to check first when it looks wrong

1. `status.json`'s `state` field — `degraded`/`failing` means recent
   captures are failing; check `last_error`.
2. `updated_utc` — if this is stale (much older than `expected_interval_s`
   × 2), the process is wedged or dead even if the container shows
   "running".
3. `failures.jsonl` tail — the actual HTTP status/content-type causing
   failures.
4. `docker compose logs` — stdout only, timestamped; no file-based logging
   exists by design.

## `--once` mode

`python scripts/capture.py --once` runs a single capture and exits. Useful
for manual checks, and keeps a Windows Task Scheduler fallback available if
Docker Desktop doesn't come back up after an unattended reboot.

## Known, accepted tradeoffs

- No deduplication of identical consecutive frames — every successful fetch
  is saved regardless of whether the source image changed (by design, for
  a gap-free record).
- No timelapse/video generation, no storage pruning — future work, not in
  scope here.
- No published port, no `HEALTHCHECK` — liveness is defined by
  `status.json` freshness and the (not-yet-deployed) push heartbeat, not by
  container process state.
