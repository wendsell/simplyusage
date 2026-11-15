# simplyusage

**Accurate SimplyPrint spool weights for Bambu Lab prints you send from Bambu Studio or Orca.**

SimplyPrint only deducts filament for prints it starts itself. Send a job
straight from your slicer and SimplyPrint logs the print but leaves your
spools untouched. simplyusage fills the gap: when a print ends, it reads the
real per-color usage from the print file and deducts it from the spool in each
AMS slot that was used.

[Website](https://wendsell.github.io/simplyusage/) ·
[Setup guide](docs/SETUP.md) ·
[Releases](https://github.com/wendsell/simplyusage/releases) ·
[Report a problem](https://github.com/wendsell/simplyusage/issues)

## Why you'd want this

You like SimplyPrint for what it does around the printer: remote monitoring,
print history, and a filament inventory that knows what's on each spool. But
you slice on the desktop. Bambu Studio or Orca is where your tuned profiles,
painted multi-color models and MakerWorld projects live, so you hit
**Print** there and send the job over LAN. SimplyPrint's web slicer and print
queue rarely get touched.

That's the catch: SimplyPrint only deducts filament for prints it starts. Every
job from your desktop slicer still shows up in SimplyPrint, but with 0 g used,
and your spool weights slowly drift from reality. The inventory says 600 g
left on a spool that's nearly empty, and you find out when the print runs out
halfway, or when you reorder the wrong colors.

simplyusage lets you keep both: slice and send however you like, and
SimplyPrint's spool weights still match what's actually on the spool.

**You don't need it** if you start all your prints from SimplyPrint, since it
already counts those.

## Features

- **Multi-color aware.** Each filament is matched to its AMS slot and deducted
  from that slot's spool.
- **Real numbers.** Grams come from the slicer data inside the job's `.3mf`
  (fetched from the printer's SD card), including color-change flush and prime
  tower.
- **Failed and cancelled prints** are deducted by how far they got.
- **No double counting.** Jobs SimplyPrint already counted are skipped, and a
  ledger makes sure each job is handled once, across restarts.
- **No extra printer connections.** It can read printer reports from the
  SimplyPrint bridge's logs, so it doesn't compete for the printer's few LAN
  connection slots.
- **Runs anywhere the bridge does:** `linux/amd64`, `linux/arm64`,
  `linux/arm/v7`.

## Quick start

```sh
docker pull ghcr.io/wendsell/simplyusage:1
```

Setup takes a few steps, one of which protects the SimplyPrint bridge from
losing its printer list. **Follow the [setup guide](docs/SETUP.md).**

## Commands

```sh
docker compose run --rm simplyusage list-printers      # SimplyPrint printer IDs + assigned spools
docker compose run --rm simplyusage simulate A1 "file.gcode.3mf" --mapping 0,1   # dry run one job
docker compose run --rm simplyusage --version
```

## Development

```sh
pip install -r requirements.txt
python -m unittest discover -s tests -t .
python -m simplyusage --env-file secrets.env list-printers
```

Releases: bump `__version__` in `simplyusage/__init__.py`, then push a tag
`vX.Y.Z`. The release workflow runs the tests, builds the multi-arch image,
pushes it to `ghcr.io/wendsell/simplyusage`, and publishes a GitHub Release.

## License

simplyusage is free software: you can redistribute it and/or modify it under
the terms of the [GNU General Public License](LICENSE) as published by the
Free Software Foundation, either version 3 of the License, or (at your option)
any later version.

It is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
A PARTICULAR PURPOSE. See the GNU General Public License for more details.

Copyright (C) 2026 wendsell.

The container image includes the complete source code, as Python files, along
with this license. Its one dependency, Eclipse Paho MQTT, is dual-licensed
under the EPL-2.0 and the Eclipse Distribution License 1.0 (BSD-3-Clause);
simplyusage uses it under the latter, which is GPL-compatible.

---

simplyusage is an independent project and is not affiliated with or endorsed
by SimplyPrint or Bambu Lab.
