# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 wendsell
#
# This file is part of simplyusage.
#
# simplyusage is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# simplyusage is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# simplyusage. If not, see <https://www.gnu.org/licenses/>.

"""Follow a printer's MQTT report stream and emit a JobEnd when a print ends.

Pure state machine, no I/O except optional state persistence, so it can be
unit-tested by feeding it report payloads.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

ACTIVE_STATES = {"PREPARE", "RUNNING", "PAUSE", "SLICING"}
END_STATES = {"FINISH", "FAILED"}
NO_TRAY = {"255", ""}


@dataclass
class Job:
    file: str = ""
    param: str = ""                    # e.g. Metadata/plate_1.gcode
    url: str = ""
    md5: str = ""
    subtask: str = ""
    ams_mapping: list[int] | None = None  # index = project filament - 1, value = tray
    use_ams: bool | None = None
    source: str = "project_file"       # or "report" if we never saw the start command
    created: float = field(default_factory=time.time)
    started: float | None = None       # first time we saw an active state
    max_percent: int = 0
    trays_seen: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{int(self.started or self.created)}:{self.md5 or self.file or self.subtask}"


@dataclass
class JobEnd:
    serial: str
    job: Job
    state: str          # FINISH or FAILED
    fraction: float     # share of the sliced filament considered used
    ended: float


class PrinterTracker:
    def __init__(self, serial: str, state_file: Path | None = None):
        self.serial = serial
        self.state_file = state_file
        self.gcode_state: str | None = None
        self.job: Job | None = None
        self._saved_percent = -1
        self._load()

    # --- persistence (so a restart mid-print keeps the AMS mapping) ---
    def _load(self) -> None:
        if self.state_file and self.state_file.exists():
            try:
                d = json.loads(self.state_file.read_text())
                self.gcode_state = d.get("gcode_state")
                if d.get("job"):
                    self.job = Job(**d["job"])
            except Exception as e:  # corrupt state is not fatal
                log.warning("%s: ignoring bad state file: %s", self.serial, e)

    def _save(self) -> None:
        if not self.state_file:
            return
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"gcode_state": self.gcode_state,
                                   "job": asdict(self.job) if self.job else None}))
        tmp.replace(self.state_file)

    # --- main entry ---
    def handle(self, payload: dict, now: float | None = None) -> JobEnd | None:
        now = time.time() if now is None else now
        p = payload.get("print")
        if not isinstance(p, dict):
            return None

        if p.get("command") == "project_file":
            if p.get("result", "success") == "success":
                mapping = p.get("ams_mapping")
                self.job = Job(
                    file=p.get("file") or "",
                    param=p.get("param") or "",
                    url=p.get("url") or "",
                    md5=p.get("md5") or "",
                    subtask=p.get("subtask_name") or "",
                    ams_mapping=[int(x) for x in mapping] if isinstance(mapping, list) else None,
                    use_ams=p.get("use_ams"),
                    created=now,
                )
                log.info("%s: job queued %s (ams_mapping=%s)", self.serial, self.job.file, self.job.ams_mapping)
                self._save()
            return None

        if p.get("command") != "push_status":
            return None

        state = p.get("gcode_state")
        prev = self.gcode_state
        if state:
            self.gcode_state = state

        # Started without us seeing project_file (printer screen, or we restarted).
        if state in ACTIVE_STATES and self.job is None and prev not in ACTIVE_STATES:
            self.job = Job(file=p.get("gcode_file") or "", subtask=p.get("subtask_name") or "",
                           source="report", created=now)
            log.info("%s: job detected from status only: %s", self.serial, self.job.file or self.job.subtask)

        job = self.job
        if job is None:
            if state and state != prev:
                self._save()
            return None

        changed = False
        if self.gcode_state in ACTIVE_STATES:
            if job.started is None:
                job.started = now
                changed = True
            if not job.file and p.get("gcode_file"):
                job.file = p["gcode_file"]
            if not job.subtask and p.get("subtask_name"):
                job.subtask = p["subtask_name"]
            pct = p.get("mc_percent")
            if isinstance(pct, (int, float)) and pct > job.max_percent:
                job.max_percent = int(pct)
            ams = p.get("ams")
            tray = str(ams.get("tray_now", "")) if isinstance(ams, dict) else ""
            if self.gcode_state == "RUNNING" and tray and tray not in NO_TRAY and tray not in job.trays_seen:
                job.trays_seen.append(tray)
                changed = True

        if state in END_STATES and job.started is not None:
            fraction = 1.0 if state == "FINISH" else job.max_percent / 100.0
            self.job = None
            self._save()
            log.info("%s: job ended %s state=%s progress=%d%%", self.serial,
                     job.file or job.subtask, state, job.max_percent)
            return JobEnd(self.serial, job, state, fraction, now)

        if changed or state != prev or job.max_percent != self._saved_percent:
            self._saved_percent = job.max_percent
            self._save()
        return None
