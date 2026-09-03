# Deploying webcam-montgo to the MateBook

One-time setup to get this project running as a Docker container on the
MateBook, replacing the old GitHub Actions workflow. Do this on the
MateBook itself, in a normal PowerShell/terminal, with Docker Desktop
installed (WSL2 backend).

## 0. Recover the existing archive first

Before you clone the repo fresh, **the git history on GitHub still has
~6 days of real archived frames** (images + metadata) committed by the
old GitHub Actions workflow, up through this migration. Those files were
removed from the tip of the repo as part of this migration (still fully
recoverable from git history, just not in the current working tree), so
grab them before you forget:

```
git clone https://github.com/AugustetheAuguste/Montgo_Window.git /tmp/old-archive
cd /tmp/old-archive
git checkout <commit-before-this-migration> -- images metadata.jsonl failures.jsonl
```

Use the last commit before this migration's commit (check `git log
--oneline` for the one still titled "Capture webcam frame"). You'll copy
`images/`, `metadata.jsonl`, and `failures.jsonl` from there into
`data/webcam-montgo/` in step 3, so the new setup continues the archive
rather than starting over.

## 1. Create the server tree

```
mkdir -p ~/server/shared
mkdir -p ~/server/data/webcam-montgo
cd ~/server
git clone https://github.com/AugustetheAuguste/Montgo_Window.git webcam-montgo
```

Result:

```
~/server/
├── shared/
├── webcam-montgo/      ← the cloned repo
└── data/
    └── webcam-montgo/
```

## 2. Move the shared status helper out of the repo

It's currently delivered inside the repo only because
`~/server/shared/status.py` didn't exist anywhere yet. Move it up a
level, where every future project will import it from:

```
mv ~/server/webcam-montgo/shared/status.py ~/server/shared/status.py
rmdir ~/server/webcam-montgo/shared
```

## 3. Restore the existing archive (from step 0)

```
cp -r /tmp/old-archive/images ~/server/data/webcam-montgo/
cp /tmp/old-archive/metadata.jsonl ~/server/data/webcam-montgo/
cp /tmp/old-archive/failures.jsonl ~/server/data/webcam-montgo/
```

If you skipped step 0, that's fine too — the container will just start
its archive from zero, no crash either way (`shared/status.py` and
`capture.py` both tolerate a missing/empty `metadata.jsonl`).

## 4. Create the .env file

```
touch ~/server/.env
```

Empty is fine. `HEARTBEAT_URL` will be unset — the code handles that
silently (no Uptime Kuma deployed yet).

## 5. Create the .dockerignore

**Critical** — without this, every build ships the entire (and growing)
`data/` archive to the Docker daemon:

```
cat > ~/server/.dockerignore <<'EOF'
data/
.env
.git
EOF
```

## 6. Build and start

```
cd ~/server/webcam-montgo
docker compose up -d --build
```

## 7. Verify it's actually working

```
docker compose logs -f
```

You should see a `capture succeeded` line roughly every 5 minutes. Then
check the status file directly:

```
cat ../data/webcam-montgo/status.json
```

`state` should be `"starting"` immediately after boot, then `"ok"` after
the first successful cycle. `updated_utc` should be recent. Look at a
saved frame under `../data/webcam-montgo/images/...` to confirm it's a
real, viewable photo.

## Everyday operations

```
docker compose down          # stop (writes state: "stopped" first)
docker compose up -d          # start again
docker compose up -d --build  # rebuild after changing capture.py or shared/status.py
docker compose logs -f        # tail logs
```

Rebuilding is required after any change to `shared/status.py`, even for
other projects, since the build context bakes it into the image (see
README.md for why).

## If something looks wrong

See "What to check first when it looks wrong" in `README.md`.
