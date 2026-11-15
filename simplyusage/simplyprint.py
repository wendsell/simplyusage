"""Minimal SimplyPrint API client (X-API-KEY auth)."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class SimplyPrintError(RuntimeError):
    pass


class SimplyPrint:
    def __init__(self, api_key: str, company_id: str, timeout: float = 20):
        self.base = f"https://api.simplyprint.io/{company_id}/"
        self.api_key = api_key
        self.timeout = timeout

    def _call(self, method: str, path: str, params: dict | None = None, body: Any = None) -> dict:
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "simplyusage/0.1",
        })
        last: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    out = json.loads(r.read() or b"{}")
                break
            except urllib.error.HTTPError as e:
                text = e.read().decode(errors="replace")[:500]
                if e.code < 500 and e.code != 429:
                    raise SimplyPrintError(f"{method} {path}: HTTP {e.code}: {text}") from e
                last = SimplyPrintError(f"{method} {path}: HTTP {e.code}: {text}")
            except (urllib.error.URLError, TimeoutError) as e:
                last = e
            time.sleep(2 * (attempt + 1))
        else:
            raise SimplyPrintError(f"{method} {path} failed: {last}")
        if not out.get("status", False):
            raise SimplyPrintError(f"{method} {path}: {out.get('message')} {out.get('errors', '')}")
        return out

    def spools(self) -> dict[int, dict]:
        out = self._call("GET", "filament/GetFilament")
        return {int(k): v for k, v in (out.get("filament") or {}).items()}

    def spool(self, spool_id: int) -> dict:
        return self._call("GET", "filament/GetSpecific", params={"id": spool_id})["data"]

    def set_grams_remaining(self, spool_id: int, grams: float) -> dict:
        out = self._call("POST", "filament/AdjustWeight", params={"fid": spool_id},
                         body={"grams_remaining": round(max(grams, 0.0), 2)})
        return out.get("spool") or {}

    def recent_jobs(self, printer_id: int, page_size: int = 10) -> list[dict]:
        out = self._call("POST", "jobs/GetPaginatedPrintJobs",
                         body={"page": 1, "page_size": page_size, "printer_ids": [printer_id]})
        return out.get("data") or []

    def spool_for_slot(self, printer_id: int, ext: int) -> tuple[int, dict] | None:
        for sid, s in self.spools().items():
            if s.get("printer") == printer_id and s.get("extruder") == ext and not s.get("deleted"):
                return sid, s
        return None
