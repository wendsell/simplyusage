# simplyusage

Deducts filament usage from SimplyPrint spools for Bambu Lab prints that were
started outside SimplyPrint (Bambu Studio / Orca LAN send, printer screen).

The SimplyPrint bridge already reports external jobs (start, progress, finish)
but sends no filament usage, so SimplyPrint never deducts from spools for them.
simplyusage fills that gap:

1. Watches each printer's LAN MQTT for jobs ending (FINISH / FAILED).
2. Pulls the job's `.3mf` from the printer via FTPS and reads per-filament
   grams from the slicer metadata, mapped to AMS slots (scaled by progress
   for failed/cancelled prints).
3. Skips jobs SimplyPrint already recorded usage for (no double counting).
4. Lowers `grams_remaining` on the spool assigned to that printer/slot via the
   SimplyPrint API.

## Setup

```sh
cp secrets.example.env secrets.env   # then fill it in
```

Runs as a container on the same LAN as the printers.
