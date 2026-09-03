#!/usr/bin/env python3
"""Capture one frame from the Cala Montgo webcam every 300s. See project README."""
import argparse
import hashlib
import json
import sys
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from status import StatusReporter  # noqa: E402

PROJECT = "webcam-montgo"
DISPLAY_NAME = "Cala Montgo webcam"
SOURCE_URL = "https://webcamscostabrava.com/webcams/webcam-montgo.php"
USER_AGENT = "CalaMontgoWindowArchiver/1.0 (personal webcam archiver)"
# Observed successful capture body size was 76828 bytes; 20000 is a loose
# floor well below normal variation, high enough to catch a truncated or
# non-image response.
MIN_BYTES = 20000
REQUEST_TIMEOUT = 30
EXPECTED_INTERVAL_S = 300
FRAMES_EXPECTED_PER_DAY = 86400 // EXPECTED_INTERVAL_S

DATA_DIR = Path("/data")
IMAGES_DIR = DATA_DIR / "images"
METADATA_PATH = DATA_DIR / "metadata.jsonl"
FAILURES_PATH = DATA_DIR / "failures.jsonl"

MADRID_TZ = ZoneInfo("Europe/Madrid")

# Read only the tail of metadata.jsonl for the 24h-distinct-hash metric,
# rather than the whole file (§3.3).
TAIL_LINES_24H = FRAMES_EXPECTED_PER_DAY + 20


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} {msg}", flush=True)


def append_jsonl(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def tail_lines(path: Path, n: int) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return deque(f, maxlen=n)


class ArchiveState:
    """Startup-computed running totals, updated incrementally (§3.3)."""

    def __init__(self) -> None:
        self.archive_bytes = 0
        self.frames_today = 0
        self.last_frame_path: str | None = None
        self._today_utc = datetime.now(timezone.utc).date()
        self._load()

    def _load(self) -> None:
        if not METADATA_PATH.exists():
            return
        with METADATA_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                self.archive_bytes += record["size_bytes"]
                self.last_frame_path = record["path"]
                ts = datetime.strptime(record["timestamp_utc"], "%Y-%m-%dT%H:%M:%SZ")
                if ts.date() == self._today_utc:
                    self.frames_today += 1

    def record_new_frame(self, size_bytes: int, path: str, timestamp_utc: datetime) -> None:
        if timestamp_utc.date() != self._today_utc:
            self._today_utc = timestamp_utc.date()
            self.frames_today = 0
        self.frames_today += 1
        self.archive_bytes += size_bytes
        self.last_frame_path = path

    def distinct_hashes_24h(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        hashes = set()
        for line in tail_lines(METADATA_PATH, TAIL_LINES_24H):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            ts = datetime.strptime(record["timestamp_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            if ts >= cutoff:
                hashes.add(record["sha256"])
        return len(hashes)

    def metrics(self) -> dict:
        return {
            "frames_today": self.frames_today,
            "frames_expected_today": FRAMES_EXPECTED_PER_DAY,
            "distinct_hashes_24h": self.distinct_hashes_24h(),
            "archive_bytes": self.archive_bytes,
            "last_frame_path": self.last_frame_path,
        }


def record_failure(now_utc: datetime, status, content_type, error_message) -> None:
    append_jsonl(
        FAILURES_PATH,
        {
            "timestamp_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "http_status": status,
            "content_type": content_type,
            "error": error_message,
            "source_url": SOURCE_URL,
        },
    )


def capture_once(state: ArchiveState) -> tuple[bool, str | None]:
    """Runs one capture cycle. Returns (success, error_message)."""
    now_utc = datetime.now(timezone.utc)

    try:
        response = requests.get(
            SOURCE_URL,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        error = f"request exception: {exc}"
        record_failure(now_utc, None, None, error)
        return False, error

    status = response.status_code
    content_type = response.headers.get("Content-Type", "")
    body = response.content

    if status != 200:
        error = f"unexpected HTTP status {status}"
        record_failure(now_utc, status, content_type, error)
        return False, error

    if not content_type.startswith("image/"):
        error = f"unexpected Content-Type '{content_type}'"
        record_failure(now_utc, status, content_type, error)
        return False, error

    if len(body) < MIN_BYTES:
        error = f"response body too small ({len(body)} bytes)"
        record_failure(now_utc, status, content_type, error)
        return False, error

    sha256 = hashlib.sha256(body).hexdigest()

    dest_dir = IMAGES_DIR / now_utc.strftime("%Y") / now_utc.strftime("%m") / now_utc.strftime("%d")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{now_utc.strftime('%H%M%S')}.jpg"
    dest_path.write_bytes(body)

    relative_path = dest_path.relative_to(DATA_DIR).as_posix()
    now_local = now_utc.astimezone(MADRID_TZ)
    append_jsonl(
        METADATA_PATH,
        {
            "timestamp_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "timestamp_local": now_local.isoformat(),
            "path": relative_path,
            "size_bytes": len(body),
            "sha256": sha256,
            "http_status": status,
            "source_url": SOURCE_URL,
        },
    )
    state.record_new_frame(len(body), relative_path, now_utc)
    return True, None


def next_slot(interval_s: int) -> datetime:
    """Next aligned UTC instant, so cumulative drift doesn't creep in (§3.3)."""
    now = datetime.now(timezone.utc)
    epoch = int(now.timestamp())
    next_epoch = (epoch // interval_s + 1) * interval_s
    return datetime.fromtimestamp(next_epoch, tz=timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="run a single capture and exit")
    args = parser.parse_args()

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    state = ArchiveState()
    reporter = StatusReporter(
        project=PROJECT,
        display_name=DISPLAY_NAME,
        data_dir=DATA_DIR,
        expected_interval_s=EXPECTED_INTERVAL_S,
    )

    if args.once:
        success, error = capture_once(state)
        if success:
            log("capture succeeded")
            reporter.report_success(next_run_utc=None, metrics=state.metrics())
        else:
            log(f"capture failed: {error}")
            reporter.report_failure(error=error, next_run_utc=None, metrics=state.metrics())
        return 0

    while True:
        success, error = capture_once(state)
        next_run = next_slot(EXPECTED_INTERVAL_S)
        if success:
            log("capture succeeded")
            reporter.report_success(next_run_utc=next_run.strftime("%Y-%m-%dT%H:%M:%SZ"), metrics=state.metrics())
        else:
            log(f"capture failed: {error}")
            reporter.report_failure(
                error=error, next_run_utc=next_run.strftime("%Y-%m-%dT%H:%M:%SZ"), metrics=state.metrics()
            )

        sleep_s = (next_run - datetime.now(timezone.utc)).total_seconds()
        if sleep_s > 0:
            time.sleep(sleep_s)
        # else: overran this slot, next_slot() on the next loop already skips ahead.


if __name__ == "__main__":
    sys.exit(main())
