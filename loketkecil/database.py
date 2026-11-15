"""Transaksi antrean, replay permintaan, snapshot, dan cadangan SQLite."""

from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import csv
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile

from .validation import AppError, require, command, request_key, positive

STATUSES = ("waiting", "serving", "done", "skipped", "cancelled")
WITA = timezone(timedelta(hours=8))


def code(number):
    return f"A{number:03d}"


def utc_now():
    return datetime.now(timezone.utc)


class Store:
    def __init__(self, path, clock=utc_now):
        self.path = Path(path).resolve()
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            require(version in (0, 1), "Versi database belum didukung; data tidak dihapus.", 503)
            if version == 0:
                existing = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                require(not existing, "Database berisi skema lain; gunakan berkas database LoketKecil.", 503)
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=3, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=3000")
        try:
            yield db
        finally:
            db.close()

    def now(self):
        return self.clock().astimezone(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def event(db, sid, kind, message, now, tid=None):
        db.execute("INSERT INTO events(session_id,kind,ticket_id,message,created_at) VALUES(?,?,?,?,?)", (sid, kind, tid, message, now))

    @staticmethod
    def session(db, sid):
        row = db.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        require(row is not None, "Sesi tidak ditemukan.", 404)
        require(row["closed_at"] is None, "Sesi sudah ditutup; catatan tetap tersedia di laporan.", 409)
        return row

    def create(self, db, data, now, synthetic=False):
        require(db.execute("SELECT 1 FROM sessions WHERE closed_at IS NULL").fetchone() is None, "Tutup sesi aktif sebelum membuka sesi lain.", 409)
        require(db.execute("SELECT 1 FROM sessions WHERE day=?", (data["day"],)).fetchone() is None, "Tanggal ini sudah memiliki sesi. Buka catatannya di arsip.", 409)
        sid = db.execute("INSERT INTO sessions(title,day,created_at,synthetic) VALUES(?,?,?,?)", (data["title"], data["day"], now, int(synthetic))).lastrowid
        for label in data["counters"]:
            db.execute("INSERT INTO counters(session_id,label) VALUES(?,?)", (sid, label))
        self.event(db, sid, "create", "Sesi layanan dibuka.", now)
        return {"session_id": sid}

    def issue(self, db, data, now):
        sid = data["session_id"]
        self.session(db, sid)
        row = db.execute("SELECT COALESCE(MAX(number),0)+1 n,COALESCE(MAX(position),0)+1 p FROM tickets WHERE session_id=?", (sid,)).fetchone()
        require(row["n"] <= 999, "Sesi sudah mencapai 999 nomor; nomor yang dibatalkan tidak dipakai ulang.", 409)
        tid = db.execute("INSERT INTO tickets(session_id,number,alias,status,position,created_at) VALUES(?,?,?,'waiting',?,?)", (sid, row["n"], data["alias"], row["p"], now)).lastrowid
        self.event(db, sid, "issue", f"{code(row['n'])} masuk antrean.", now, tid)
        return {"session_id": sid, "ticket_id": tid, "code": code(row["n"])}

    def call(self, db, data, now):
        sid, cid = data["session_id"], data["counter_id"]
        self.session(db, sid)
        counter = db.execute("SELECT * FROM counters WHERE id=? AND session_id=?", (cid, sid)).fetchone()
        require(counter is not None, "Loket tidak ditemukan pada sesi ini.", 404)
        require(counter["version"] == data["expected_version"], "Status loket berubah di tab lain. Muat ulang sebelum memanggil.", 409)
        require(db.execute("SELECT 1 FROM tickets WHERE counter_id=? AND status='serving'", (cid,)).fetchone() is None, "Selesaikan atau lewatkan nomor yang sedang dilayani.", 409)
        ticket = db.execute("SELECT * FROM tickets WHERE session_id=? AND status='waiting' ORDER BY position,id LIMIT 1", (sid,)).fetchone()
        require(ticket is not None, "Belum ada nomor yang menunggu.", 409)
        db.execute("UPDATE tickets SET status='serving',counter_id=?,called_at=?,finished_at=NULL,version=version+1 WHERE id=?", (cid, now, ticket["id"]))
        db.execute("UPDATE counters SET version=version+1 WHERE id=?", (cid,))
        self.event(db, sid, "call", f"{code(ticket['number'])} dipanggil ke {counter['label']}.", now, ticket["id"])
        return {"session_id": sid, "ticket_id": ticket["id"], "code": code(ticket["number"]), "counter_id": cid}

    def transition(self, db, data, now):
        sid, action = data["session_id"], data["action"]
        self.session(db, sid)
        ticket = db.execute("SELECT * FROM tickets WHERE id=? AND session_id=?", (data["ticket_id"], sid)).fetchone()
        require(ticket is not None, "Nomor tidak ditemukan pada sesi ini.", 404)
        require(ticket["version"] == data["expected_version"], "Status nomor sudah berubah. Muat ulang sebelum melanjutkan.", 409)
        previous = "serving" if action in ("finish", "skip") else "skipped" if action == "requeue" else "waiting"
        require(ticket["status"] == previous, "Perpindahan status tidak sesuai kondisi nomor saat ini.", 409)
        status = {"finish": "done", "skip": "skipped", "requeue": "waiting", "cancel": "cancelled"}[action]
        if action == "requeue":
            position = db.execute("SELECT COALESCE(MAX(position),0)+1 FROM tickets WHERE session_id=?", (sid,)).fetchone()[0]
            db.execute("UPDATE tickets SET status='waiting',position=?,counter_id=NULL,called_at=NULL,finished_at=NULL,version=version+1 WHERE id=?", (position, ticket["id"]))
        else:
            db.execute("UPDATE tickets SET status=?,finished_at=?,version=version+1 WHERE id=?", (status, now, ticket["id"]))
        if previous == "serving":
            db.execute("UPDATE counters SET version=version+1 WHERE id=?", (ticket["counter_id"],))
        message = {"finish": "selesai dilayani", "skip": "dilewatkan karena belum hadir", "requeue": "masuk kembali di akhir antrean", "cancel": "dibatalkan"}[action]
        self.event(db, sid, action, f"{code(ticket['number'])} {message}.", now, ticket["id"])
        return {"session_id": sid, "ticket_id": ticket["id"], "code": code(ticket["number"]), "status": status}

    def mutate(self, payload, key):
        data, key = command(payload), request_key(key)
        fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
        try:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                try:
                    previous = db.execute("SELECT * FROM requests WHERE key=?", (key,)).fetchone()
                    if previous:
                        require(previous["payload_hash"] == fingerprint, "Kunci permintaan sudah digunakan untuk isi yang berbeda.", 409)
                        result = json.loads(previous["result_json"])
                        db.execute("COMMIT")
                        return result, True
                    now, action = self.now(), data["action"]
                    if action == "create":
                        result = self.create(db, data, now)
                    elif action == "issue":
                        result = self.issue(db, data, now)
                    elif action == "call":
                        result = self.call(db, data, now)
                    elif action in ("finish", "skip", "requeue", "cancel"):
                        result = self.transition(db, data, now)
                    elif action == "close":
                        sid = data["session_id"]
                        self.session(db, sid)
                        unfinished = db.execute("SELECT COUNT(*) FROM tickets WHERE session_id=? AND status IN ('waiting','serving')", (sid,)).fetchone()[0]
                        require(not unfinished, "Masih ada nomor menunggu atau dilayani. Selesaikan atau batalkan dahulu.", 409)
                        db.execute("UPDATE sessions SET closed_at=? WHERE id=?", (now, sid))
                        self.event(db, sid, "close", "Sesi ditutup. Nomor yang dilewatkan tetap tercatat.", now)
                        result = {"session_id": sid, "closed": True}
                    else:
                        require(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0, "Contoh hanya dapat dimuat pada database kosong; data lama tidak ditimpa.", 409)
                        result = self.create(db, {"title": "Layanan contoh sintetis", "day": self.clock().astimezone(WITA).date().isoformat(), "counters": ["Loket 1", "Loket 2"]}, now, synthetic=True)
                        sid = result["session_id"]
                        for i in range(5):
                            self.issue(db, {"session_id": sid, "alias": f"Tamu contoh {i+1}"}, now)
                        cid = db.execute("SELECT id FROM counters WHERE session_id=? ORDER BY id LIMIT 1", (sid,)).fetchone()[0]
                        first = self.call(db, {"session_id": sid, "counter_id": cid, "expected_version": 1}, now)
                        self.transition(db, {"action": "finish", "session_id": sid, "ticket_id": first["ticket_id"], "expected_version": 2}, now)
                        self.call(db, {"session_id": sid, "counter_id": cid, "expected_version": 3}, now)
                    result = {"action": action, **result}
                    db.execute("INSERT INTO requests(key,payload_hash,result_json,created_at) VALUES(?,?,?,?)", (key, fingerprint, json.dumps(result, ensure_ascii=False), now))
                    db.execute("COMMIT")
                    return result, False
                except Exception:
                    if db.in_transaction:
                        db.execute("ROLLBACK")
                    raise
        except sqlite3.Error as exc:
            raise AppError("Database belum dapat menyimpan. Status tidak diubah sebagian; periksa koneksi lalu coba ulang permintaan yang sama.", 503) from exc

    def state(self, session_id=None):
        if session_id is not None:
            positive(session_id, "session_id")
        with self.connect() as db:
            db.execute("BEGIN")
            sessions = [dict(r) for r in db.execute("SELECT * FROM sessions ORDER BY day DESC,id DESC")]
            active = next((s for s in sessions if s["closed_at"] is None), None)
            selected = next((s for s in sessions if s["id"] == session_id), None) if session_id is not None else active or (sessions[0] if sessions else None)
            if session_id is not None:
                require(selected is not None, "Sesi tidak ditemukan.", 404)
            sid = selected["id"] if selected else 0
            counters = [dict(r) for r in db.execute("SELECT * FROM counters WHERE session_id=? ORDER BY id", (sid,))]
            tickets = [dict(r) for r in db.execute("SELECT * FROM tickets WHERE session_id=? ORDER BY position,id", (sid,))]
            for ticket in tickets:
                ticket["code"] = code(ticket["number"])
            for counter in counters:
                counter["ticket"] = next((t for t in tickets if t["counter_id"] == counter["id"] and t["status"] == "serving"), None)
            counts = {status: sum(t["status"] == status for t in tickets) for status in STATUSES}
            events = [dict(r) for r in db.execute("SELECT * FROM events WHERE session_id=? ORDER BY id DESC LIMIT 40", (sid,))]
            revision = db.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]
            db.execute("COMMIT")
        return {"sessions": sessions, "selected": selected, "active_id": active["id"] if active else None, "counters": counters, "tickets": tickets, "counts": counts, "events": events, "revision": revision, "server_time": self.now(), "today": self.clock().astimezone(WITA).date().isoformat()}

    def display(self):
        state = self.state()
        selected = state["selected"]
        # Whitelist; alias dan catatan internal tidak pernah masuk respons layar.
        return {"session": None if not selected else {k: selected[k] for k in ("title", "day", "closed_at", "synthetic")},
                "counters": [{"label": c["label"], "code": c["ticket"]["code"] if c["ticket"] else None} for c in state["counters"]],
                "next": [t["code"] for t in state["tickets"] if t["status"] == "waiting"][:8],
                "counts": state["counts"], "revision": state["revision"], "server_time": state["server_time"]}

    def csv(self, session_id):
        state = self.state(session_id)
        require(state["selected"] is not None, "Belum ada sesi untuk diekspor.", 404)
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["tanggal_sesi", "nomor", "alias", "status", "loket", "masuk_UTC", "dipanggil_UTC", "selesai_UTC"])
        labels = {c["id"]: c["label"] for c in state["counters"]}
        def safe(value):
            return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
        for t in sorted(state["tickets"], key=lambda t: t["number"]):
            writer.writerow([state["selected"]["day"], t["code"], safe(t["alias"]), t["status"], safe(labels.get(t["counter_id"], "")), t["created_at"], t["called_at"] or "", t["finished_at"] or ""])
        return stream.getvalue().encode("utf-8-sig")

    def backup(self):
        with tempfile.TemporaryDirectory(prefix="loketkecil-backup-") as folder:
            path = Path(folder) / "cadangan.sqlite3"
            with self.connect() as source:
                destination = sqlite3.connect(path)
                try:
                    source.backup(destination)
                finally:
                    destination.close()
            return path.read_bytes()
