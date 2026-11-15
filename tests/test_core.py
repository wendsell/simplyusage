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

import unittest
from pathlib import Path

from simplyusage.threemf import parse_slice_info, plate_from_param, FilamentUse
from simplyusage.tracker import PrinterTracker, Job
from simplyusage.usage import map_usage, tray_to_extruder
from simplyusage.ftps import candidate_paths

FIX = Path(__file__).parent / "fixtures"

MULTI_PLATE = """<?xml version="1.0"?><config>
<plate><metadata key="index" value="1"/><filament id="1" used_g="5" used_m="1.6"/></plate>
<plate><metadata key="index" value="2"/>
  <filament id="1" used_g="2.5" used_m="0.8"/><filament id="3" used_g="10" used_m="3.3"/>
  <filament id="2" used_g="0" used_m="0"/></plate>
</config>"""


def status(**kw):
    return {"print": {"command": "push_status", **kw}}


PROJECT_FILE = {"print": {"command": "project_file", "ams_mapping": [0],
                          "ams_mapping2": [{"ams_id": 0, "slot_id": 0}],
                          "file": "STOP_Wasting_Filament!_Color_Test_Layers_1-5.gcode.3mf",
                          "md5": "C54A", "param": "Metadata/plate_1.gcode",
                          "subtask_name": "STOP_Wasting_Filament!_Color_Test_Layers_1-5",
                          "use_ams": True, "result": "success"}}


class ThreeMF(unittest.TestCase):
    def test_real_a1_slice_info(self):
        f = parse_slice_info((FIX / "slice_info_a1_colortest.config").read_text(), 1)
        self.assertEqual([(x.id, x.used_g, x.used_m) for x in f], [(1, 0.94, 0.32)])

    def test_multi_plate_picks_right_plate(self):
        f = parse_slice_info(MULTI_PLATE, 2)
        self.assertEqual({x.id: x.used_g for x in f}, {1: 2.5, 3: 10.0, 2: 0.0})

    def test_plate_from_param(self):
        self.assertEqual(plate_from_param("Metadata/plate_7.gcode"), 7)
        self.assertEqual(plate_from_param(""), 1)


class Tracker(unittest.TestCase):
    def test_full_print_lifecycle(self):
        t = PrinterTracker("A1")
        self.assertIsNone(t.handle(status(gcode_state="FINISH")))  # leftover from last print
        self.assertIsNone(t.handle(PROJECT_FILE, now=100))
        self.assertIsNone(t.handle(status(gcode_state="PREPARE"), now=101))
        self.assertIsNone(t.handle(status(gcode_state="RUNNING", mc_percent=1,
                                          ams={"tray_now": "0"}), now=110))
        self.assertIsNone(t.handle(status(mc_percent=64), now=200))
        end = t.handle(status(gcode_state="FINISH", mc_percent=100), now=300)
        self.assertIsNotNone(end)
        self.assertEqual(end.state, "FINISH")
        self.assertEqual(end.fraction, 1.0)
        self.assertEqual(end.job.ams_mapping, [0])
        self.assertEqual(end.job.trays_seen, ["0"])
        self.assertIsNone(t.job)

    def test_cancelled_scales_by_progress(self):
        t = PrinterTracker("A1")
        t.handle(PROJECT_FILE)
        t.handle(status(gcode_state="RUNNING", mc_percent=40))
        end = t.handle(status(gcode_state="FAILED", mc_percent=0))
        self.assertAlmostEqual(end.fraction, 0.40)

    def test_project_file_without_start_does_not_end(self):
        t = PrinterTracker("A1")
        t.handle(status(gcode_state="IDLE"))
        t.handle(PROJECT_FILE)
        self.assertIsNone(t.handle(status(gcode_state="FAILED")))  # never started

    def test_job_detected_without_project_file(self):
        t = PrinterTracker("A1")
        t.handle(status(gcode_state="RUNNING", gcode_file="x.gcode.3mf", mc_percent=5,
                        ams={"tray_now": "2"}))
        end = t.handle(status(gcode_state="FINISH"))
        self.assertEqual(end.job.source, "report")
        self.assertIsNone(end.job.ams_mapping)
        self.assertEqual(end.job.trays_seen, ["2"])

    def test_state_survives_restart(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            sf = Path(d) / "state.json"
            t = PrinterTracker("A1", sf)
            t.handle(PROJECT_FILE)
            t.handle(status(gcode_state="RUNNING", mc_percent=30))
            t2 = PrinterTracker("A1", sf)  # restart
            t2.handle(status(mc_percent=60))
            end = t2.handle(status(gcode_state="FINISH"))
            self.assertEqual(end.job.ams_mapping, [0])
            self.assertEqual(end.job.max_percent, 60)


class Usage(unittest.TestCase):
    def test_mapping_by_project_index(self):
        job = Job(ams_mapping=[3, -1, 1])
        fil = [FilamentUse(1, 2.0, 0.6), FilamentUse(2, 0, 0), FilamentUse(3, 10.0, 3.0)]
        u = map_usage(job, fil, 0.5)
        self.assertEqual([(x.filament_id, x.tray, x.grams) for x in u], [(1, 3, 1.0), (3, 1, 5.0)])

    def test_fallback_single_tray(self):
        u = map_usage(Job(trays_seen=["2"]), [FilamentUse(1, 4.0, 1.0)], 1.0)
        self.assertEqual(u[0].tray, 2)

    def test_unmapped_multicolor_without_mapping(self):
        u = map_usage(Job(trays_seen=["0", "1"]), [FilamentUse(1, 1, 1), FilamentUse(2, 1, 1)], 1.0)
        self.assertTrue(all(x.tray is None for x in u))

    def test_external_spool(self):
        u = map_usage(Job(use_ams=False), [FilamentUse(1, 4.0, 1.0)], 1.0)
        self.assertEqual(u[0].tray, 254)
        self.assertIsNone(tray_to_extruder(254, None))
        self.assertEqual(tray_to_extruder(254, 4), 4)
        self.assertEqual(tray_to_extruder(5, None), 5)


class Paths(unittest.TestCase):
    def test_candidates(self):
        self.assertEqual(candidate_paths("a b.gcode.3mf", "file:///sdcard/cache/a%20b.gcode.3mf"),
                         ["/cache/a b.gcode.3mf", "/a b.gcode.3mf"])
        self.assertEqual(candidate_paths("x.3mf"), ["/x.3mf", "/cache/x.3mf"])


if __name__ == "__main__":
    unittest.main()
