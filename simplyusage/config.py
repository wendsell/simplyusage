from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PrinterConfig:
    name: str
    host: str
    serial: str
    access_code: str
    simplyprint_id: int
    external_ext: int | None = None  # SimplyPrint extruder index for the external spool
    source: str = "mqtt"             # "mqtt" (own connection) or "bridge-log"


@dataclass
class Config:
    api_key: str
    company_id: str
    printers: list[PrinterConfig] = field(default_factory=list)
    data_dir: Path = Path("data")
    dry_run: bool = False
    dedup_delay: float = 60.0
    bridge_log_dir: Path = Path("/bridge-logs")


def load_env_file(path: str | os.PathLike) -> dict[str, str]:
    """Parse a simple KEY=VALUE file (comments and blank lines ignored)."""
    out: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def load(env: dict[str, str] | None = None) -> Config:
    env = dict(os.environ if env is None else env)
    missing: list[str] = []

    def req(key: str) -> str:
        v = env.get(key, "").strip()
        if not v:
            missing.append(key)
        return v

    cfg = Config(
        api_key=req("SIMPLYPRINT_API_KEY"),
        company_id=req("SIMPLYPRINT_COMPANY_ID"),
        data_dir=Path(env.get("DATA_DIR", "data")),
        dry_run=_truthy(env.get("DRY_RUN")),
        dedup_delay=float(env.get("DEDUP_DELAY", "60") or 60),
        bridge_log_dir=Path(env.get("BRIDGE_LOG_DIR", "/bridge-logs")),
    )
    for name in [p.strip() for p in env.get("PRINTERS", "").split(",") if p.strip()]:
        sp_id = req(f"{name}_SIMPLYPRINT_ID")
        ext = env.get(f"{name}_EXTERNAL_EXT", "").strip()
        cfg.printers.append(PrinterConfig(
            name=name,
            host=req(f"{name}_HOST"),
            serial=req(f"{name}_SERIAL"),
            access_code=req(f"{name}_ACCESS_CODE"),
            simplyprint_id=int(sp_id) if sp_id.isdigit() else 0,
            external_ext=int(ext) if ext.isdigit() else None,
            source=env.get(f"{name}_SOURCE", "mqtt").strip().lower() or "mqtt",
        ))
        if cfg.printers[-1].source not in ("mqtt", "bridge-log"):
            raise SystemExit(f"{name}_SOURCE must be mqtt or bridge-log")
    if not cfg.printers:
        missing.append("PRINTERS")
    if missing:
        raise SystemExit(f"Missing config: {', '.join(missing)}")
    return cfg
