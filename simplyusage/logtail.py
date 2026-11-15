"""Follow the SimplyPrint bridge's per-printer mqtt.log files.

Used for printers (like the A1) that only allow one LAN MQTT connection,
which the bridge already holds. The bridge logs every report at DEBUG as:

  <ts> | DEBUG | printer.<uuid>.mqtt | device/<SERIAL>/report: {json}
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
from pathlib import Path

from .tracker import PrinterTracker

log = logging.getLogger(__name__)

LINE_RE = re.compile(r"\|\s*printer\.[^|]+\.mqtt\s*\|\s*device/(?P<serial>[A-Za-z0-9]+)/report: (?P<json>\{.*\})\s*$")


def parse_line(line: str) -> tuple[str, dict] | None:
    m = LINE_RE.search(line)
    if not m:
        return None
    try:
        return m.group("serial"), json.loads(m.group("json"))
    except ValueError:
        return None


class _Follower:
    """Tail one file, surviving truncation and rotation."""

    def __init__(self, path: Path, from_end: bool):
        self.path = path
        self.f = path.open("r", encoding="utf-8", errors="replace")
        self.ino = os.fstat(self.f.fileno()).st_ino
        if from_end:
            self.f.seek(0, os.SEEK_END)
        self.buf = ""

    def read_lines(self) -> list[str]:
        try:
            st = self.path.stat()
        except FileNotFoundError:
            st = None
        if st is not None and (st.st_ino != self.ino or st.st_size < self.f.tell()):
            # Rotated or truncated: drain the old handle, then start the new file from the top.
            lines = self._drain()
            self.f.close()
            self.f = self.path.open("r", encoding="utf-8", errors="replace")
            self.ino = st.st_ino
            return lines + self._drain()
        return self._drain()

    def _drain(self) -> list[str]:
        chunk = self.f.read()
        if not chunk:
            return []
        self.buf += chunk
        *lines, self.buf = self.buf.split("\n")
        return lines

    def close(self) -> None:
        self.f.close()


class BridgeLogWatcher:
    """One watcher for the whole bridge log dir; routes lines by serial."""

    def __init__(self, log_dir: Path, trackers: dict[str, PrinterTracker], out: queue.Queue,
                 names: dict[str, str] | None = None, poll: float = 1.0):
        self.log_dir = log_dir
        self.trackers = trackers
        self.names = names or {}
        self.out = out
        self.poll = poll
        self.followers: dict[Path, _Follower] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="bridge-log", daemon=True)
        self._first_scan = True

    def start(self) -> None:
        log.info("following bridge logs in %s for %s", self.log_dir,
                 ", ".join(self.names.get(s, s) for s in self.trackers))
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        for f in self.followers.values():
            f.close()

    def _scan(self) -> None:
        if not self.log_dir.is_dir():
            if self._first_scan:
                log.error("bridge log dir %s not found", self.log_dir)
            self._first_scan = False
            return
        for path in self.log_dir.glob("*/mqtt.log"):
            if path not in self.followers:
                # Existing files at startup: start at the end (no replay of old history).
                # Files appearing later (printer re-added): read from the start.
                self.followers[path] = _Follower(path, from_end=self._first_scan)
                log.info("tailing %s", path)
        self._first_scan = False

    def poll_once(self) -> None:
        self._scan()
        for fol in list(self.followers.values()):
            for line in fol.read_lines():
                parsed = parse_line(line)
                if not parsed:
                    continue
                serial, payload = parsed
                tracker = self.trackers.get(serial)
                if tracker is None:
                    continue
                try:
                    end = tracker.handle(payload)
                except Exception:
                    log.exception("%s: tracker error", self.names.get(serial, serial))
                    continue
                if end:
                    self.out.put(end)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:
                log.exception("bridge log poll failed")
            self._stop.wait(self.poll)
