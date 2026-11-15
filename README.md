# simplyusage

Deducts filament usage from SimplyPrint spools for Bambu Lab prints started
outside SimplyPrint (Bambu Studio / Orca LAN send, printer screen).

The SimplyPrint bridge reports external jobs (start, progress, finish) but
sends no filament usage, so SimplyPrint never deducts from spools for them.

## How it works

1. **Job events.** Each printer's MQTT report stream is followed, either over
   its own LAN connection (`<PRINTER>_SOURCE=mqtt`) or by tailing the
   SimplyPrint bridge's per-printer `mqtt.log` (`bridge-log`). Use
   `bridge-log` for printers that limit LAN MQTT connections (the A1 allows
   very few; the bridge already holds one). On print start the printer echoes
   the `project_file` command, which includes `ams_mapping` (project filament
   to AMS tray).
2. **Usage.** When a job ends (FINISH / FAILED), the `.3mf` is downloaded from
   the printer's SD card over implicit FTPS (port 990), and per-filament grams
   are read from `Metadata/slice_info.config`. These include color-change
   flush and prime tower, but not the start-up purge line. Failed or cancelled
   prints are scaled by the progress reached.
3. **Dedup.** After `DEDUP_DELAY` seconds, the job is skipped if SimplyPrint
   already recorded usage for it (jobs it started itself).
4. **Deduct.** For each filament, the spool assigned in SimplyPrint to that
   printer and extruder (= AMS tray index) is found and `grams_remaining` is
   lowered via `filament/AdjustWeight`.
5. **Ledger.** Every handled job is appended to `data/ledger.jsonl`, which
   also guards against double deduction. Per-printer job state is persisted,
   so a restart mid-print keeps the AMS mapping.

Not handled: multi-color prints started from the printer screen (no
mapping is reported), and external-spool prints unless `<PRINTER>_EXTERNAL_EXT`
says which SimplyPrint extruder index the external spool uses.

## Setup

```sh
cp secrets.example.env secrets.env   # then fill it in
docker compose up -d --build
```

For `bridge-log`, the bridge's log dir must be bind-mounted out of its
container. Its state dir must also persist, or recreating the container wipes
its printer list:

```yaml
# SimplyPrint bridge compose.yaml
services:
  simplyprint-client:
    image: simplyprint/simplyprint-client
    network_mode: host
    restart: always
    volumes:
      - simplyprint_data:/root/.config/SimplyPrint
      - simplyprint_share:/root/.local/share/SimplyPrint   # printer list / state DB
      - ./logs:/root/.local/state/SimplyPrint/log          # read by simplyusage
volumes:
  simplyprint_data:
  simplyprint_share:
```

simplyusage's `compose.yaml` expects that log dir at `../simplyprint/logs`.

## Commands

```sh
# Process one job by hand (dry run unless --apply)
python -m simplyusage --env-file secrets.env simulate A1 "file.gcode.3mf" --mapping 0,1

# Tests
python -m unittest discover -s tests -t .
```
