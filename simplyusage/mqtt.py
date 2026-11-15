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

"""LAN MQTT connection to a Bambu printer (read-only report stream)."""
from __future__ import annotations

import json
import logging
import queue
import ssl

import paho.mqtt.client as mqtt

from .config import PrinterConfig
from .tracker import PrinterTracker

log = logging.getLogger(__name__)


class PrinterWatcher:
    def __init__(self, printer: PrinterConfig, tracker: PrinterTracker, out: queue.Queue):
        self.printer = printer
        self.tracker = tracker
        self.out = out
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"simplyusage-{printer.serial}")
        c.username_pw_set("bblp", printer.access_code)
        c.tls_set(cert_reqs=ssl.CERT_NONE)
        c.tls_insecure_set(True)  # printer uses a self-signed cert
        c.reconnect_delay_set(min_delay=2, max_delay=60)
        c.on_connect = self._on_connect
        c.on_disconnect = self._on_disconnect
        c.on_message = self._on_message
        self.client = c

    @property
    def report_topic(self) -> str:
        return f"device/{self.printer.serial}/report"

    def start(self) -> None:
        self.client.connect_async(self.printer.host, 8883, keepalive=60)
        self.client.loop_start()

    def stop(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("%s: MQTT connect failed: %s", self.printer.name, reason_code)
            return
        log.info("%s: MQTT connected (%s)", self.printer.name, self.printer.host)
        client.subscribe(self.report_topic)
        # Ask for a full status snapshot; harmless if the firmware ignores it.
        client.publish(f"device/{self.printer.serial}/request",
                       json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}}))

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        log.warning("%s: MQTT disconnected (%s), will reconnect", self.printer.name, reason_code)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload)
        except ValueError:
            return
        try:
            end = self.tracker.handle(payload)
        except Exception:
            log.exception("%s: tracker error", self.printer.name)
            return
        if end:
            self.out.put(end)
