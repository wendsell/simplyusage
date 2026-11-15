"""Entry point.

  python -m simplyusage                 run the service
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

from . import config
from .processor import Processor
from .tracker import Job, JobEnd, PrinterTracker

log = logging.getLogger("simplyusage")


def _setup(argv_env: str | None) -> config.Config:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    env = dict(os.environ)
    if argv_env:
        env = {**config.load_env_file(argv_env), **{k: v for k, v in os.environ.items() if k in ("DRY_RUN", "DATA_DIR", "DEDUP_DELAY", "LOG_LEVEL")}}
    return config.load(env)


def run(cfg: config.Config) -> None:
    from .logtail import BridgeLogWatcher
    from .mqtt import PrinterWatcher  # paho only needed for the service

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
    ap.add_argument("--env-file", help="load settings from this KEY=VALUE file")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("simulate", help="process one job by hand")
    s.add_argument("printer")
    s.add_argument("file", help="file name on the printer SD card")
    s.add_argument("--plate", type=int, default=1)
    s.add_argument("--mapping", help="AMS tray per project filament, e.g. 0,2")
    s.add_argument("--fraction", type=float, default=1.0)
    s.add_argument("--apply", action="store_true", help="actually write to SimplyPrint")
    args = ap.parse_args(argv)
    cfg = _setup(args.env_file)
    if args.cmd == "simulate":
        simulate(cfg, args)
    else:
        run(cfg)


if __name__ == "__main__":
    main(sys.argv[1:])
