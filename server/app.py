#!/usr/bin/env python3
"""The compile service: static page, plus one endpoint that shells out to `stlc`.

    POST /api/compile   {"source": "..."}
      -> 200 {"ok": true,  "output": "..."}
      -> 200 {"ok": false, "error": "error"}     a rejected program is not an HTTP error
      -> 413                                     source too large
      -> 504                                     compiler took too long

Standard library only. The whole job is "write a temp file, run a binary, read stdout",
and a framework would be more dependency than program.

## Process per request

`stlc` is invoked as a subprocess for each request and shares nothing between them, so a
request cannot observe or corrupt another. It costs a fork and ~40ms, which is cheaper
than any state we would otherwise have to reason about.

## Why the compiler's stderr never reaches the user

The diagnostic is prefixed with the input path, and that path is a temp file we invented.
Echoing stderr would leak server-side paths for no benefit, so the exit code is the only
signal used and the user gets a flat "error". The compiler has no column numbers to offer
yet; when it does, this is the place that changes.
"""

import json
import os
import pathlib
import resource
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STLC = os.environ.get("STLC_BIN", "/usr/local/bin/stlc")
STATIC = pathlib.Path(__file__).resolve().parent.parent / "static"
PORT = int(os.environ.get("PORT", "8080"))

MAX_BODY = 64 * 1024          # a lambda term that does not fit is not a lambda term
DRAIN_CAP = 1024 * 1024       # how much of an over-long body we will read just to reply to it
COMPILE_TIMEOUT = 5           # seconds
MEMORY_CAP = 512 * 1024 * 1024

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".stlc": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
}


def _limit_child() -> None:
    """Cap the compiler's address space. Runs between fork and exec.

    The input is arbitrary text from the internet. The timeout covers a program that loops;
    this covers one that allocates. Without it a single request could take the container's
    whole memory allowance with it.
    """
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_CAP, MEMORY_CAP))


def compile_source(source: str) -> tuple[bool, str]:
    """Returns (ok, output-or-error-message)."""
    with tempfile.TemporaryDirectory() as d:
        path = pathlib.Path(d) / "input.stlc"
        path.write_text(source, encoding="utf-8")
        try:
            p = subprocess.run(
                [STLC, str(path)],
                capture_output=True,
                timeout=COMPILE_TIMEOUT,
                preexec_fn=_limit_child,
            )
        except subprocess.TimeoutExpired:
            return False, "timeout"
        if p.returncode != 0:
            return False, "error"
        return True, p.stdout.decode("utf-8", "replace")


class Handler(BaseHTTPRequestHandler):
    server_version = "lambdalab-web"

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    # --- reads ---------------------------------------------------------------------------

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        # `/api/health`, not the conventional `/healthz`: Cloud Run's frontend intercepts
        # that exact path and answers 404 itself, so the container never sees the request.
        # `/health` and `/healthz/` do arrive — it is only the bare spelling that is taken.
        if path == "/api/health":
            self._send_json(200, {"status": "ok"})
            return
        rel = "index.html" if path == "/" else path.lstrip("/")
        target = (STATIC / rel).resolve()
        # `resolve()` then containment check: without it, `GET /../server/app.py` escapes
        # the static directory.
        if not target.is_file() or STATIC not in target.parents:
            self._send(404, b"not found\n", "text/plain; charset=utf-8")
            return
        ctype = CONTENT_TYPES.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)

    # --- the one write -------------------------------------------------------------------

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/api/compile":
            self._send_json(404, {"ok": False, "error": "no such endpoint"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            # Answering without reading the body resets the connection mid-upload, and the
            # client sees a network error rather than the 413 — so drain first, bounded, and
            # close afterwards rather than leaving a partly-read body on a kept-alive socket.
            remaining = min(length, DRAIN_CAP)
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
            self.close_connection = True
            self._send_json(413, {"ok": False, "error": "source too large"})
            return

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            source = payload["source"]
            if not isinstance(source, str):
                raise TypeError
        except Exception:
            self._send_json(400, {"ok": False, "error": "expected {\"source\": \"...\"}"})
            return

        ok, result = compile_source(source)
        if ok:
            self._send_json(200, {"ok": True, "output": result})
        elif result == "timeout":
            self._send_json(504, {"ok": False, "error": "timeout"})
        else:
            # A rejected program is a normal answer, not a server failure — 200.
            self._send_json(200, {"ok": False, "error": result})

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} {fmt % args}", flush=True)


def main() -> None:
    print(f"serving on :{PORT}, compiler at {STLC}", flush=True)
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
