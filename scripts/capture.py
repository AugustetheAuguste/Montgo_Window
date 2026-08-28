#!/usr/bin/env python3
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

SOURCE_URL = "https://webcamscostabrava.com/webcams/webcam-montgo.php"
USER_AGENT = (
    "CalaMontgoWindowArchiver/1.0 "
    "(+https://github.com/; personal webcam archiver, contact via repo issues)"
)
MIN_BYTES = 1024
REQUEST_TIMEOUT = 30

REPO_ROOT = Path(__file__).resolve().parent.parent
IMAGES_DIR = REPO_ROOT / "images"
METADATA_PATH = REPO_ROOT / "metadata.jsonl"
FAILURES_PATH = REPO_ROOT / "failures.jsonl"

MADRID_TZ = ZoneInfo("Europe/Madrid")


def append_jsonl(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


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


def main() -> int:
    now_utc = datetime.now(timezone.utc)

    try:
        response = requests.get(
            SOURCE_URL,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        record_failure(now_utc, None, None, f"request exception: {exc}")
        return 0

    status = response.status_code
    content_type = response.headers.get("Content-Type", "")
    body = response.content

    if status != 200:
        record_failure(now_utc, status, content_type, f"unexpected HTTP status {status}")
        return 0

    if not content_type.startswith("image/"):
        record_failure(now_utc, status, content_type, f"unexpected Content-Type '{content_type}'")
        return 0

    if len(body) < MIN_BYTES:
        record_failure(now_utc, status, content_type, f"response body too small ({len(body)} bytes)")
        return 0

    sha256 = hashlib.sha256(body).hexdigest()

    dest_dir = IMAGES_DIR / now_utc.strftime("%Y") / now_utc.strftime("%m") / now_utc.strftime("%d")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{now_utc.strftime('%H%M%S')}.jpg"
    dest_path.write_bytes(body)

    now_local = now_utc.astimezone(MADRID_TZ)
    append_jsonl(
        METADATA_PATH,
        {
            "timestamp_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "timestamp_local": now_local.isoformat(),
            "path": dest_path.relative_to(REPO_ROOT).as_posix(),
            "size_bytes": len(body),
            "sha256": sha256,
            "http_status": status,
            "source_url": SOURCE_URL,
        },
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
