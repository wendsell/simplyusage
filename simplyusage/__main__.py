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

"""Entry point.

  python -m simplyusage                 run the service
  python -m simplyusage list-printers   show SimplyPrint printer IDs and assigned spools
  python -m simplyusage simulate PRINTER FILE [--mapping 0,1] [--fraction 1.0] [--apply]
                                        process one job by hand (dry-run unless --apply)
"""
from __future__ import annotations

import argparse
import logging
import os
import queue
import signal
import sys
import threading
import time

from . import __version__, config
from .processor import Processor
from .simplyprint import SimplyPrint, SimplyPrintError
from .tracker import Job, JobEnd, PrinterTracker

log = logging.getLogger("simplyusage")


def _setup(argv_env: str | None, require_printers: bool = True) -> config.Config:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    env = dict(os.environ)
    if argv_env:
        env = {**config.load_env_file(argv_env), **{k: v for k, v in os.environ.items() if k in ("DRY_RUN", "DATA_DIR", "DEDUP_DELAY", "LOG_LEVEL")}}
    return config.load(env, require_printers=require_printers)


def list_printers(cfg: config.Config) -> None:
    sp = SimplyPrint(cfg.api_key, cfg.company_id)
    sp.check()
    spools = sp.spools()
    printers = sp.printers()
    if not printers:
        print("No printers in this SimplyPrint account.")
    for p in printers:
        info = p.get("printer") or {}
        print(f"{p.get('id')}  {info.get('name', '?')}  ({'online' if info.get('online') else 'offline'})")
        assigned = sorted((s.get("extruder") if s.get("extruder") is not None else -1, s)
                          for s in spools.values() if s.get("printer") == p.get("id"))
        for ext, s in assigned:
            kind = (s.get("type") or {}).get("name", "")
            print(f"    slot {ext}: spool {s.get('id')}  {kind} {s.get('colorName') or ''}  "
                  f"{s.get('leftGrams')} g left")
        if not assigned:
            print("    (no spools assigned)")
    print("\nUse the number at the start of each line as <PRINTER>_SIMPLYPRINT_ID.")


def run(cfg: config.Config) -> None:
    from .logtail import BridgeLogWatcher
    from .mqtt import PrinterWatcher  # paho only needed for the service

    log.info("simplyusage %s", __version__)
    try:
        SimplyPrint(cfg.api_key, cfg.company_id).check()
    except SimplyPrintError as e:
        log.error("%s", e)
        raise SystemExit(2)
    proc = Processor(cfg)
    q: queue.Queue[JobEnd] = queue.Queue()
    watchers = []
    from_logs: dict[str, PrinterTracker] = {}
    for p in cfg.printers:
        tracker = PrinterTracker(p.serial, cfg.data_dir / f"state_{p.serial}.json")
        if p.source == "bridge-log":
            from_logs[p.serial] = tracker
            continue
        w = PrinterWatcher(p, tracker, q)
        w.start()
        watchers.append(w)
    if from_logs:
        w = BridgeLogWatcher(cfg.bridge_log_dir, from_logs, q,
                             names={p.serial: p.name for p in cfg.printers})
        w.start()
        watchers.append(w)
    log.info("watching %s (dry_run=%s)",
             ", ".join(f"{p.name} via {p.source}" for p in cfg.printers), cfg.dry_run)

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    while not stop.is_set():
        try:
            end = q.get(timeout=1)
        except queue.Empty:
            continue
        try:
            proc.handle(end)
        except Exception:
            log.exception("failed to process job end")
    for w in watchers:
        w.stop()


def simulate(cfg: config.Config, args) -> None:
    printer = next((p for p in cfg.printers if p.name == args.printer), None)
    if not printer:
        raise SystemExit(f"unknown printer {args.printer}")
    cfg.dry_run = not args.apply
    cfg.dedup_delay = 0
    now = time.time()
    job = Job(file=args.file, param=f"Metadata/plate_{args.plate}.gcode",
              ams_mapping=[int(x) for x in args.mapping.split(",")] if args.mapping else None,
              created=now, started=now, max_percent=int(args.fraction * 100), source="simulate")
    rec = Processor(cfg).handle(JobEnd(printer.serial, job, "FINISH" if args.fraction >= 1 else "FAILED",
                                       args.fraction, now))
    import json
    print(json.dumps({k: v for k, v in rec.items() if k != "job"}, indent=2, default=str))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="simplyusage")
    ap.add_argument("--version", action="version", version=f"simplyusage {__version__}")
    ap.add_argument("--env-file", help="load settings from this KEY=VALUE file")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list-printers", help="show SimplyPrint printer IDs and assigned spools")
    s = sub.add_parser("simulate", help="process one job by hand")
    s.add_argument("printer")
    s.add_argument("file", help="file name on the printer SD card")
    s.add_argument("--plate", type=int, default=1)
    s.add_argument("--mapping", help="AMS tray per project filament, e.g. 0,2")
    s.add_argument("--fraction", type=float, default=1.0)
    s.add_argument("--apply", action="store_true", help="actually write to SimplyPrint")
    args = ap.parse_args(argv)
    cfg = _setup(args.env_file, require_printers=args.cmd != "list-printers")
    if args.cmd == "list-printers":
        try:
            list_printers(cfg)
        except SimplyPrintError as e:
            raise SystemExit(str(e))
    elif args.cmd == "simulate":
        simulate(cfg, args)
    else:
        run(cfg)


if __name__ == "__main__":
    main(sys.argv[1:])
