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

"""Turn sliced filament usage + AMS mapping into per-slot grams."""
from __future__ import annotations

from dataclasses import dataclass

from .threemf import FilamentUse
from .tracker import Job

EXTERNAL_TRAYS = {254, 255}


@dataclass
class SlotUse:
    filament_id: int
    tray: int | None      # Bambu tray number (0-15 AMS, 254/255 external); None = unknown
    grams: float
    meters: float
    note: str = ""


def map_usage(job: Job, filaments: list[FilamentUse], fraction: float) -> list[SlotUse]:
    used = [f for f in filaments if f.used_g > 0]
    out: list[SlotUse] = []
    for f in used:
        tray: int | None = None
        note = ""
        m = job.ams_mapping
        if job.use_ams is False:
            tray, note = 254, "external spool (use_ams=false)"
        elif m and 0 < f.id <= len(m) and m[f.id - 1] >= 0:
            tray, note = m[f.id - 1], "ams_mapping"
        elif len(used) == 1 and len(job.trays_seen) == 1:
            tray, note = int(job.trays_seen[0]), "single filament, single tray seen"
        else:
            note = f"no mapping for filament {f.id} (mapping={m}, trays_seen={job.trays_seen})"
        out.append(SlotUse(f.id, tray, round(f.used_g * fraction, 2), round(f.used_m * fraction, 3), note))
    return out


def tray_to_extruder(tray: int, external_ext: int | None) -> int | None:
    """SimplyPrint extruder index for a Bambu tray. AMS tray n -> extruder n."""
    if tray in EXTERNAL_TRAYS:
        return external_ext
    return tray if 0 <= tray < 16 else None
