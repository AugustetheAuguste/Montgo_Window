"""Shared status-contract helper (schema v1).

Every project on the box imports this instead of hand-rolling status logic,
so a future admin panel works for project #10 exactly as it does for #2.

NOT part of any single project. Lives at ~/server/shared/status.py and is
baked into every project's image via a build context of ~/server (see each
project's Dockerfile/compose.yml).
"""
from __future__ import annotations

import json
import os
import signal
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

# state thresholds, derived from consecutive_failures (§2.4)
DEGRADED_MAX_CONSECUTIVE_FAILURES = 2  # 1-2 failures -> degraded
# 3+ consecutive failures -> failing


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _derive_state(consecutive_failures: int, stopped: bool, started: bool) -> str:
    if stopped:
        return "stopped"
    if not started:
        return "starting"
    if consecutive_failures == 0:
        return "ok"
    if consecutive_failures <= DEGRADED_MAX_CONSECUTIVE_FAILURES:
        return "degraded"
    return "failing"


class StatusReporter:
    """Tracks and persists status.json for one project, per schema v1."""

    def __init__(
        self,
        project: str,
        display_name: str,
        data_dir: Path,
        expected_interval_s: int,
    ) -> None:
        self.project = project
        self.display_name = display_name
        self.data_dir = data_dir
        self.expected_interval_s = expected_interval_s
        self.host = os.environ.get("HOST_NAME", "unknown")
        self.status_path = data_dir / "status.json"

        self.process_started_utc = _now_iso()
        self._have_run_cycle = False
        self._stopped = False

        # Reload lifetime counters so a restart doesn't erase history (§2.2 rule 2).
        existing = self._read_existing()
        self.consecutive_failures = existing.get("consecutive_failures", 0)
        self.counters = existing.get("counters") or {"attempts": 0, "successes": 0, "failures": 0}
        self.last_success_utc = existing.get("last_success_utc")
        self.last_failure_utc = existing.get("last_failure_utc")
        self.last_error = existing.get("last_error")

        signal.signal(signal.SIGTERM, self._handle_sigterm)

    def _read_existing(self) -> dict[str, Any]:
        try:
            with self.status_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _handle_sigterm(self, signum, frame) -> None:
        self._stopped = True
        self._write(next_run_utc=None, metrics={})
        raise SystemExit(0)

    def report_success(self, next_run_utc: str | None, metrics: dict[str, Any]) -> None:
        now = _now_iso()
        self._have_run_cycle = True
        self.consecutive_failures = 0
        self.counters["attempts"] += 1
        self.counters["successes"] += 1
        self.last_success_utc = now
        self.last_error = None
        self._write(next_run_utc=next_run_utc, metrics=metrics, last_attempt_utc=now)
        self._ping_heartbeat()

    def report_failure(self, error: str, next_run_utc: str | None, metrics: dict[str, Any]) -> None:
        now = _now_iso()
        self._have_run_cycle = True
        self.consecutive_failures += 1
        self.counters["attempts"] += 1
        self.counters["failures"] += 1
        self.last_failure_utc = now
        self.last_error = error
        self._write(next_run_utc=next_run_utc, metrics=metrics, last_attempt_utc=now)

    def _write(
        self,
        next_run_utc: str | None,
        metrics: dict[str, Any],
        last_attempt_utc: str | None = None,
    ) -> None:
        now = _now_iso()
        state = _derive_state(self.consecutive_failures, self._stopped, self._have_run_cycle)
        record = {
            "schema": SCHEMA_VERSION,
            "project": self.project,
            "display_name": self.display_name,
            "host": self.host,
            "state": state,
            "process_started_utc": self.process_started_utc,
            "updated_utc": now,
            "last_attempt_utc": last_attempt_utc or now,
            "last_success_utc": self.last_success_utc,
            "last_failure_utc": self.last_failure_utc,
            "last_error": self.last_error,
            "next_run_utc": next_run_utc,
            "expected_interval_s": self.expected_interval_s,
            "consecutive_failures": self.consecutive_failures,
            "counters": self.counters,
            "metrics": metrics,
        }
        self._atomic_write(record)

    def _atomic_write(self, record: dict[str, Any]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=self.data_dir, prefix=".status.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.status_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _ping_heartbeat(self) -> None:
        url = os.environ.get("HEARTBEAT_URL")
        if not url:
            return
        try:
            with urllib.request.urlopen(url, timeout=10):
                pass
        except Exception:
            # A failed heartbeat must never crash the project or spam logs (§2.7).
            pass
