"""Download files from a Bambu printer's SD card over implicit FTPS (port 990)."""
from __future__ import annotations

import ftplib
import io
import logging
import posixpath
import ssl
from urllib.parse import unquote, urlparse

log = logging.getLogger(__name__)


class ImplicitFTPS(ftplib.FTP_TLS):
    """ftplib only does explicit TLS; Bambu printers speak implicit TLS."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._sock = None

    @property
    def sock(self):
        return self._sock

    @sock.setter
    def sock(self, value):
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value)
        self._sock = value

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        # Printer requires TLS session reuse on the data channel.
        conn = self.context.wrap_socket(conn, server_hostname=self.host, session=self.sock.session)
        return conn, size


def _connect(host: str, access_code: str, timeout: float = 20) -> ImplicitFTPS:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # self-signed printer cert
    ftp = ImplicitFTPS(context=ctx, timeout=timeout, encoding="utf-8")
    ftp.connect(host, 990)
    ftp.login("bblp", access_code)
    ftp.prot_p()
    return ftp


def candidate_paths(file: str, url: str | None = None) -> list[str]:
    """Where a job's .3mf might live on the SD card."""
    paths: list[str] = []
    if url:
        u = urlparse(url)
        p = unquote(u.path or "")
        if u.scheme in ("file", "ftp") and p:
            p = p.removeprefix("/sdcard").removeprefix("/mnt/sdcard")
            paths.append(p if p.startswith("/") else "/" + p)
    if file:
        name = posixpath.basename(file)
        if file.startswith("/"):
            paths.append(file)
        paths += [f"/{name}", f"/cache/{name}"]
    seen, out = set(), []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def fetch_job_file(host: str, access_code: str, file: str, url: str | None = None,
                   subtask: str | None = None) -> tuple[str, bytes]:
    """Return (path, bytes) of the job's .3mf. Raises FileNotFoundError."""
    ftp = _connect(host, access_code)
    try:
        tried = candidate_paths(file, url)
        for path in tried:
            buf = io.BytesIO()
            try:
                ftp.retrbinary(f"RETR {path}", buf.write)
                return path, buf.getvalue()
            except ftplib.error_perm:
                continue
        # Fall back to a directory search by name / subtask name.
        wanted = {posixpath.basename(file)} if file else set()
        if subtask:
            wanted |= {f"{subtask}.gcode.3mf", f"{subtask}.3mf"}
        for d in ("/", "/cache"):
            try:
                names = ftp.nlst(d)
            except ftplib.error_perm:
                continue
            for n in names:
                if posixpath.basename(n) in wanted:
                    path = n if n.startswith("/") else posixpath.join(d, n)
                    buf = io.BytesIO()
                    ftp.retrbinary(f"RETR {path}", buf.write)
                    return path, buf.getvalue()
        raise FileNotFoundError(f"job file not found on printer (tried {tried} and search for {sorted(wanted)})")
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()
