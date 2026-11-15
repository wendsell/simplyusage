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

"""Handle a finished/failed job: dedup, fetch 3mf, deduct from SimplyPrint spools."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from . import ftps
from .config import Config, PrinterConfig
from .simplyprint import SimplyPrint
from .threemf import parse_3mf, plate_from_param
from .tracker import JobEnd
from .usage import map_usage, tray_to_extruder

log = logging.getLogger(__name__)


class Ledger:
    """Append-only record of handled jobs; also the double-deduction guard."""

    def __init__(self, path: Path):
        self.path = path
        self.keys: set[str] = set()
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    self.keys.add(json.loads(line)["key"])
                except Exception:
                    pass

    def seen(self, key: str) -> bool:
        return key in self.keys

    def add(self, key: str, record: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "at": datetime.now(timezone.utc).isoformat(), **record}) + "\n")
        self.keys.add(key)


def _parse_ts(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def current_grams(spool: dict) -> float:
    """Remaining grams. leftGrams is rounded to 0.1 g, so derive it from the
    exact mm counts when possible to avoid drift over many small prints."""
    left, total, total_g = spool.get("left"), spool.get("total"), spool.get("totalGrams")
    if left is not None and total and total_g:
        return round(float(total_g) * float(left) / float(total), 2)
    if spool.get("leftGrams") is None:
        raise RuntimeError("spool has no remaining-weight data")
    return float(spool["leftGrams"])


def simplyprint_already_counted(sp: SimplyPrint, printer_id: int, end: JobEnd) -> dict | None:
    """Return the SimplyPrint job if it already logged filament usage for this print."""
    started = end.job.started or end.job.created
    for j in sp.recent_jobs(printer_id):
        if j.get("printer") not in (printer_id, None):
            continue
        ts = _parse_ts(j.get("startDate"))
        if ts is None or abs(ts - started) > 15 * 60:
            continue
        if (j.get("filUsageGram") or 0) > 0 or (j.get("filUsage") or 0) > 0:
            return j
    return None


class Processor:
    def __init__(self, cfg: Config, sp: SimplyPrint | None = None):
        self.cfg = cfg
        self.sp = sp or SimplyPrint(cfg.api_key, cfg.company_id)
        self.ledger = Ledger(cfg.data_dir / "ledger.jsonl")
        self.by_serial = {p.serial: p for p in cfg.printers}

    def handle(self, end: JobEnd) -> dict:
        printer = self.by_serial[end.serial]
        job = end.job
        name = job.file or job.subtask
        record = {"printer": printer.name, "file": name, "state": end.state,
                  "progress": job.max_percent, "fraction": end.fraction, "job": asdict(job)}
        if self.ledger.seen(job.key):
            log.info("%s: %s already handled, skipping", printer.name, name)
            return {"result": "duplicate"}

        def done(result: str, **extra) -> dict:
            record.update(result=result, **extra)
            if not self.cfg.dry_run:
                self.ledger.add(job.key, record)
            log.info("%s: %s -> %s %s", printer.name, name, result,
                     json.dumps(extra, default=str) if extra else "")
            return record

        if end.fraction <= 0:
            return done("skipped", reason="no progress")

        # Give SimplyPrint time to close out its own job, then check it.
        if self.cfg.dedup_delay > 0:
            time.sleep(self.cfg.dedup_delay)
        try:
            sp_job = simplyprint_already_counted(self.sp, printer.simplyprint_id, end)
        except Exception as e:
            log.warning("%s: could not check SimplyPrint jobs (%s); continuing", printer.name, e)
            sp_job = None
        if sp_job:
            return done("skipped", reason="SimplyPrint already recorded usage",
                        simplyprint_job=sp_job.get("uid"), grams=sp_job.get("filUsageGram"))

        try:
            path, data = ftps.fetch_job_file(printer.host, printer.access_code, job.file, job.url, job.subtask)
            filaments = parse_3mf(data, plate_from_param(job.param))
        except Exception as e:
            return done("error", reason=f"could not read job file: {e}")

        uses = map_usage(job, filaments, end.fraction)
        deductions = []
        for u in uses:
            entry = {"filament": u.filament_id, "tray": u.tray, "grams": u.grams, "how": u.note}
            ext = tray_to_extruder(u.tray, printer.external_ext) if u.tray is not None else None
            if ext is None:
                entry["result"] = "unmapped"
                deductions.append(entry)
                continue
            try:
                found = self.sp.spool_for_slot(printer.simplyprint_id, ext)
                if not found:
                    entry["result"] = f"no spool assigned to extruder {ext}"
                    deductions.append(entry)
                    continue
                sid, spool = found
                current = current_grams(self.sp.spool(sid))
                new = round(max(float(current) - u.grams, 0.0), 2)
                entry.update(spool=sid, color=spool.get("colorName"), before=current, after=new)
                if self.cfg.dry_run:
                    entry["result"] = "dry-run"
                else:
                    self.sp.set_grams_remaining(sid, new)
                    entry["result"] = "deducted"
            except Exception as e:
                entry["result"] = f"error: {e}"
            deductions.append(entry)

        ok = all(d["result"] in ("deducted", "dry-run") for d in deductions)
        return done("ok" if ok else "partial", file_path=path, deductions=deductions)
