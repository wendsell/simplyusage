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

"""Read per-filament usage from a Bambu sliced .3mf (Metadata/slice_info.config)."""
from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass


@dataclass
class FilamentUse:
    id: int          # 1-based project filament index
    used_g: float
    used_m: float
    type: str = ""
    color: str = ""


def plate_from_param(param: str | None) -> int:
    """'Metadata/plate_3.gcode' -> 3. Defaults to 1."""
    m = re.search(r"plate_(\d+)\.gcode", param or "")
    return int(m.group(1)) if m else 1


def parse_slice_info(xml_text: str, plate: int = 1) -> list[FilamentUse]:
    root = ET.fromstring(xml_text)
    plates = root.findall("plate")
    chosen = None
    for p in plates:
        idx = next((m.get("value") for m in p.findall("metadata") if m.get("key") == "index"), None)
        if idx is not None and int(idx) == plate:
            chosen = p
            break
    if chosen is None:
        if len(plates) == 1:
            chosen = plates[0]
        else:
            raise ValueError(f"plate {plate} not found in slice_info ({len(plates)} plates)")
    out = []
    for f in chosen.findall("filament"):
        out.append(FilamentUse(
            id=int(f.get("id", "0")),
            used_g=float(f.get("used_g", "0") or 0),
            used_m=float(f.get("used_m", "0") or 0),
            type=f.get("type", ""),
            color=f.get("color", ""),
        ))
    return out


def parse_3mf(data: bytes, plate: int = 1) -> list[FilamentUse]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml_text = z.read("Metadata/slice_info.config").decode("utf-8")
    return parse_slice_info(xml_text, plate)
