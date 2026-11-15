"""HTTP lokal. GET tidak mengubah antrean; JSON POST membawa kunci replay."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, unquote, urlsplit

from .validation import AppError, parse_json, require

WEB = Path(__file__).resolve().parent.parent / "web"
ASSETS = {"/": ("index.html", "text/html; charset=utf-8"), "/display/": ("display.html", "text/html; charset=utf-8"),
          "/styles.css": ("styles.css", "text/css; charset=utf-8"), "/operator.mjs": ("operator.mjs", "text/javascript; charset=utf-8"),
          "/display.mjs": ("display.mjs", "text/javascript; charset=utf-8"), "/outbox.mjs": ("outbox.mjs", "text/javascript; charset=utf-8"), "/icon.svg": ("icon.svg", "image/svg+xml")}


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store):
        self.store = store
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "LoketKecil/1.0"

    def log_message(self, format, *args):
        pass  # Alias dan payload tidak ditulis ke log akses.

    def send(self, status, body, content_type="application/json; charset=utf-8", extra=None):
        self.send_response(status)
        for key, value in {"Content-Type": content_type, "Content-Length": str(len(body)), "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'", **(extra or {})}.items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # Klien boleh retry setelah jawaban yang hilang.

    def json(self, status, value, extra=None):
        self.send(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), extra=extra)

    def route_error(self, exc):
        if isinstance(exc, AppError):
            self.json(exc.status, {"error": str(exc)})
        elif isinstance(exc, (sqlite3.Error, OSError)):
            self.json(503, {"error": "Database atau berkas belum dapat diakses. Coba muat ulang; jangan hapus data."})
        else:
            self.json(500, {"error": "Permintaan belum dapat diselesaikan. Periksa status sebelum mencoba ulang."})

    @staticmethod
    def selected(query):
        values = parse_qs(query, keep_blank_values=True)
        require(set(values) <= {"session_id"}, "Parameter URL tidak dikenal.")
        if not values:
            return None
        raw = values["session_id"]
        require(len(raw) == 1 and raw[0].isascii() and raw[0].isdigit() and 0 < int(raw[0]) <= 2147483647, "session_id tidak valid.")
        return int(raw[0])

    def do_GET(self):
        try:
            url = urlsplit(self.path)
            path = unquote(url.path)
            if path == "/api/state":
                self.json(200, self.server.store.state(self.selected(url.query)))
            elif path == "/api/display":
                require(not url.query, "Layar memakai sesi aktif tanpa parameter.")
                self.json(200, self.server.store.display())
            elif path == "/api/report.csv":
                self.send(200, self.server.store.csv(self.selected(url.query)), "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="loketkecil-laporan.csv"'})
            elif path == "/api/backup.sqlite3":
                require(not url.query, "Cadangan tidak memakai parameter.")
                self.send(200, self.server.store.backup(), "application/vnd.sqlite3", {"Content-Disposition": 'attachment; filename="loketkecil-cadangan.sqlite3"'})
            elif path in ASSETS:
                name, content_type = ASSETS[path]
                self.send(200, (WEB / name).read_bytes(), content_type)
            else:
                raise AppError("Halaman atau berkas tidak ditemukan.", 404)
        except Exception as exc:
            self.route_error(exc)

    def do_POST(self):
        try:
            require(self.path == "/api/mutate", "Endpoint tidak ditemukan.", 404)
            port = self.server.server_port
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            require(self.headers.get("Host") in hosts, "Host permintaan tidak diizinkan.", 403)
            origin = self.headers.get("Origin")
            require(origin is None or origin in {"http://" + h for h in hosts}, "Permintaan lintas situs ditolak.", 403)
            require(self.headers.get_content_type() == "application/json", "Gunakan Content-Type application/json.", 415)
            length = self.headers.get("Content-Length", "")
            require(length.isascii() and length.isdigit() and 0 < int(length) <= 8192, "Ukuran permintaan harus 1–8192 byte.", 413)
            self.connection.settimeout(5)
            raw = self.rfile.read(int(length))
            require(len(raw) == int(length), "Isi permintaan belum lengkap.")
            result, replay = self.server.store.mutate(parse_json(raw), self.headers.get("Idempotency-Key"))
            self.json(200, {"result": result, "replayed": replay}, {"Idempotency-Replayed": str(replay).lower()})
        except Exception as exc:
            self.route_error(exc)
