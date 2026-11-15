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

import os
import queue
import tempfile
import unittest
from pathlib import Path

from simplyusage.logtail import BridgeLogWatcher, parse_line
from simplyusage.tracker import PrinterTracker

SERIAL = "00M00A000000000"
PFX = "2026-11-15 07:03:08.024 | DEBUG | printer.00000000-0000-0000-0000-000000000000.mqtt | "


def line(payload: str) -> str:
    return f"{PFX}device/{SERIAL}/report: {payload}\n"


PROJECT = line('{"print":{"command":"project_file","ams_mapping":[2],"file":"a.gcode.3mf",'
               '"param":"Metadata/plate_1.gcode","use_ams":true,"result":"success"}}')
RUN = line('{"print":{"command":"push_status","gcode_state":"RUNNING","mc_percent":10}}')
FIN = line('{"print":{"command":"push_status","gcode_state":"FINISH","mc_percent":100}}')


class ParseLine(unittest.TestCase):
    def test_report_line(self):
        serial, p = parse_line(PROJECT)
        self.assertEqual(serial, SERIAL)
        self.assertEqual(p["print"]["ams_mapping"], [2])

    def test_ignores_other_lines(self):
        self.assertIsNone(parse_line(PFX + "Connected to Bambu device."))
        self.assertIsNone(parse_line(PFX + "Sent command b'{}' on topic device/X/request"))


class Watcher(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "uuid1").mkdir()
        self.log = self.dir / "uuid1" / "mqtt.log"
        self.log.write_text(FIN)  # old history: must not be replayed
        self.q = queue.Queue()
        self.w = BridgeLogWatcher(self.dir, {SERIAL: PrinterTracker(SERIAL)}, self.q)

    def tearDown(self):
        for f in self.w.followers.values():
            f.close()
        self.tmp.cleanup()

    def append(self, text):
        with self.log.open("a", encoding="utf-8") as f:
            f.write(text)

    def test_follows_new_lines_only(self):
        self.w.poll_once()
        self.append(PROJECT + RUN)
        self.w.poll_once()
        self.assertTrue(self.q.empty())
        self.append(FIN)
        self.w.poll_once()
        end = self.q.get_nowait()
        self.assertEqual(end.job.ams_mapping, [2])

    def test_partial_line_waits_for_newline(self):
        self.w.poll_once()
        self.append(PROJECT + RUN + FIN[:40])
        self.w.poll_once()
        self.assertTrue(self.q.empty())
        self.append(FIN[40:])
        self.w.poll_once()
        self.assertFalse(self.q.empty())

    def test_truncation(self):
        self.w.poll_once()
        self.append(PROJECT + RUN)
        self.w.poll_once()
        self.log.write_text("")  # truncated by rotation
        self.w.poll_once()
        self.append(FIN)
        self.w.poll_once()
        self.assertFalse(self.q.empty())

    def test_new_printer_dir_read_from_start(self):
        self.w.poll_once()
        (self.dir / "uuid2").mkdir()
        (self.dir / "uuid2" / "mqtt.log").write_text(PROJECT + RUN + FIN)
        self.w.poll_once()
        self.assertFalse(self.q.empty())


if __name__ == "__main__":
    unittest.main()
