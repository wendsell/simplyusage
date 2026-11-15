# Setup guide

This walks through a complete install, in the order that avoids the traps.
It assumes you can SSH into a Linux box and run Docker Compose.

## What you need

- **Bambu Lab printer(s) in LAN-only mode.** Tested on a P1S (with AMS) and an
  A1 (with AMS lite).
- **A SimplyPrint account with API access.** Writing spool weights uses the
  `filament/AdjustWeight` endpoint. It may need a paid plan; simplyusage was
  built and tested on one.
- **The SimplyPrint bridge** (`simplyprint/simplyprint-client`) running in
  Docker on a machine on the same network as the printers. simplyusage runs
  next to it on the same machine.
- **Your spools in SimplyPrint's filament manager**, assigned to the printer
  and slot they're loaded in.

> [!NOTE]
> The image runs on `linux/amd64`, `linux/arm64` and `linux/arm/v7`, so a
> Raspberry Pi running the bridge works too.

## How it works

1. When a print starts, the printer announces which AMS slot feeds each
   filament in the file (`ams_mapping`).
2. When the print ends, simplyusage downloads the job's `.3mf` from the
   printer's SD card and reads the slicer's grams per filament.
3. It waits a minute and checks SimplyPrint's job history. If SimplyPrint
   already counted the job (prints it started itself), it stops there.
4. Otherwise it lowers the remaining weight of the spool assigned to each slot
   that was used. Failed and cancelled prints are scaled by how far they got.

Every handled job is written to `data/ledger.jsonl`, so a job is never
deducted twice, even across restarts.

## Step 1: Make the bridge keep its printer list

> [!CAUTION]
> **Do this before anything else, and before adding printers to the bridge.**
> The bridge stores its printer list in `/root/.local/share/SimplyPrint` inside
> the container. The stock compose file doesn't put that on a volume, so *any*
> change that recreates the container (editing its compose file, updating the
> image) wipes your printer setup. SimplyPrint keeps the printers and spool
> assignments on its side, so you can re-add them, but it's annoying.

The same edit also exposes the bridge's logs, which simplyusage reads. Your
bridge's `compose.yaml` should look like this (the folder name is up to you;
this guide uses `~/simplyprint`):

```yaml
services:
  simplyprint-client:
    image: simplyprint/simplyprint-client
    container_name: simplyprint-client
    network_mode: host
    restart: always
    volumes:
      - simplyprint_data:/root/.config/SimplyPrint
      # Printer list and state DB. Without this, recreating the container wipes them.
      - simplyprint_share:/root/.local/share/SimplyPrint
      # Printer reports, read by simplyusage
      - ./logs:/root/.local/state/SimplyPrint/log

volumes:
  simplyprint_data:
  simplyprint_share:
```

Apply it:

```sh
cd ~/simplyprint
mkdir -p logs
docker compose up -d
```

## Step 2: Add printers and assign spools

1. Open the bridge's web UI (`http://<bridge host>:8000`) and add your
   printers. If you already had them in SimplyPrint, link to the existing
   printers so their job history and spool assignments carry over.
2. After a minute, each printer gets its own folder in `~/simplyprint/logs/`,
   containing an `mqtt.log`. That's what simplyusage will read.
3. In SimplyPrint's filament manager, assign each spool to the printer and slot
   it's loaded in. The extruder number is the AMS slot, counted from 0 (slot 1
   on the printer is extruder 0).

> [!IMPORTANT]
> simplyusage deducts from whatever spool SimplyPrint has in that slot.
> When you swap a spool in the AMS, update the assignment in SimplyPrint too.

## Step 3: Collect your details

| What | Where to find it |
|---|---|
| SimplyPrint API key | simplyprint.io → Account settings → API (`/panel/user_settings/api`) |
| SimplyPrint company ID | On the same API settings page. It's the number used in API URLs (`https://api.simplyprint.io/<company id>/...`) |
| Printer IP address | Printer screen → network settings, or your router |
| Printer serial number | Printer screen → device info, or Bambu Studio → Device |
| Printer access code | Printer screen → network settings, next to the LAN-only switch |

## Step 4: Configure simplyusage

Put simplyusage in a folder next to the bridge's:

```sh
mkdir -p ~/simplyusage && cd ~/simplyusage
curl -fsSLO https://raw.githubusercontent.com/wendsell/simplyusage/main/compose.yaml
curl -fsSL https://raw.githubusercontent.com/wendsell/simplyusage/main/secrets.example.env -o secrets.env
chmod 600 secrets.env
```

If your bridge folder isn't `~/simplyprint`, fix the `../simplyprint/logs`
path in `compose.yaml`.

Edit `secrets.env`. Each printer gets a short prefix of your choice, listed in
`PRINTERS`:

```sh
SIMPLYPRINT_API_KEY=your-api-key
SIMPLYPRINT_COMPANY_ID=12345

P1S_HOST=192.168.1.50
P1S_SERIAL=01P00A000000000
P1S_ACCESS_CODE=12345678
P1S_SIMPLYPRINT_ID=        # filled in during step 5
P1S_SOURCE=bridge-log

A1_HOST=192.168.1.51
A1_SERIAL=03900A000000000
A1_ACCESS_CODE=abcd1234
A1_SIMPLYPRINT_ID=
A1_SOURCE=bridge-log

PRINTERS=P1S,A1
DRY_RUN=true               # start safe; switch to false after a test print
DEDUP_DELAY=60
```

### `bridge-log` or `mqtt`?

Use **`bridge-log`** unless you have a reason not to. It reads the printer's
reports from the bridge's logs and opens no connection to the printer at all.

`mqtt` gives simplyusage its own connection to the printer, but Bambu
printers only accept a few LAN MQTT clients at once, and the bridge and your
slicers already use some:

- The **A1** refused a connection outright while the bridge and two slicers
  were connected.
- With one extra client on the **P1S**, Bambu Studio failed to connect with
  "unsubscribed device".

`mqtt` is still there for setups without the bridge's logs. Note that
`bridge-log` depends on the bridge's debug log format, so a bridge update
could break it; that would show up as jobs no longer being detected.

## Step 5: Find your SimplyPrint printer IDs

```sh
docker compose run --rm simplyusage list-printers
```

```text
10423  Bambu Lab A1  (online)
    slot 0: spool 50311  eSUN 3D PLA+ Yellow  827.4 g left
    slot 1: spool 50308  eSUN 3D PLA+ Pine Green  839.7 g left
10424  Bambu Lab P1S  (online)
    slot 0: spool 50291  eSUN 3D PLA-Basic Blue  900 g left
```

Put each number into `<PRINTER>_SIMPLYPRINT_ID`. This is also a good check
that your API key, company ID and spool assignments are right.

## Step 6: Start it

```sh
docker compose up -d
docker compose logs -f
```

You should see something like:

```text
INFO simplyusage: simplyusage 1.0.0
INFO simplyusage.logtail: following bridge logs in /bridge-logs for P1S, A1
INFO simplyusage.logtail: tailing /bridge-logs/<uuid>/mqtt.log
INFO simplyusage: watching P1S via bridge-log, A1 via bridge-log (dry_run=True)
```

## Step 7: Test print

Send a small print from Bambu Studio or Orca. In the logs:

1. At the start: `job queued <file> (ams_mapping=[0])`.
2. At the end: `job ended <file> state=FINISH`.
3. About a minute later, the result, with the spool, the grams and the before
   and after weights:

```text
A1: Color_Test.gcode.3mf -> ok {"deductions": [{"filament": 1, "tray": 0, "grams": 1.06,
  "spool": 50311, "color": "Yellow", "before": 829.06, "after": 828.0, "result": "dry-run"}]}
```

If that looks right, set `DRY_RUN=false` in `secrets.env` and run
`docker compose up -d` to apply it. From then on, `"result": "deducted"`
means the spool was updated in SimplyPrint.

> [!TIP]
> To try a job by hand without printing, point `simulate` at a file that's
> already on the printer's SD card (dry run unless you add `--apply`):
>
> `docker compose run --rm simplyusage simulate A1 "file.gcode.3mf" --mapping 0,1`

## Updating

```sh
cd ~/simplyusage
docker compose pull
docker compose up -d
```

The `:1` tag in `compose.yaml` follows the latest 1.x release. Pin an exact
version (for example `:1.0.0`) if you'd rather update by hand.

## Troubleshooting

### The bridge lost all its printers

Its container was recreated without the state volume from step 1. Add the
volume, recreate it once more, and re-add the printers in the bridge UI,
linking them to the existing SimplyPrint printers.

### Bambu Studio says it can't connect, "unsubscribed device"

Too many LAN MQTT clients on that printer. Switch every printer to
`bridge-log` so simplyusage holds no connections. If it still fails, connect
the printer in Studio over LAN with its access code, rather than through your
Bambu cloud account (the cloud can't reach printers in LAN-only mode).

### A printer's MQTT port times out (`mqtt` source)

The printer is out of connection slots. Use `bridge-log` for it.

### Jobs aren't detected (`bridge-log` source)

- Check that `~/simplyprint/logs/<uuid>/mqtt.log` exists and is still being
  written.
- Check that the path in simplyusage's `compose.yaml` points at that folder.
- If the bridge was updated and the log lines changed format, open an issue.

### "SimplyPrint rejected the API key or company ID"

One of the two is wrong. `list-printers` gives the same error, so it's a quick
way to test a fix.

### A job ended with `no spool assigned to extruder N`

SimplyPrint has no spool on that printer and slot. Assign one, and remember
the slot is counted from 0.

### A job ended with `unmapped`

The printer didn't report which slot fed which filament. That happens with
multi-color prints started from the printer's screen, and with the external
spool holder (see below).

## Limits and accuracy

- **Grams come from the slicer** and include color-change flushing and the
  prime tower. They leave out the printer's start-up purge line and filament
  loading, which in testing was about 0.1–0.2 g per color.
- **Failed or cancelled prints** scale every color by the same progress, even
  when some colors were only used in later layers.
- **The external spool holder** isn't mapped by default. If you've assigned a
  spool to it in SimplyPrint, set `<PRINTER>_EXTERNAL_EXT` to that extruder
  number.
- **Multi-color prints started from the printer's screen** can't be mapped to
  slots. Single-color ones work, using the slot the printer actually fed from.
- **Tested with one AMS (or AMS lite) per printer.** With several AMS units,
  slot numbers continue across units (the second unit starts at 4); this
  hasn't been tested.
