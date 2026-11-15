"""Integrasi HTTP dan SQLite nyata, termasuk race dan kegagalan transaksi."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import contextlib
import csv
import http.client
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
import uuid
import server as launcher

from loketkecil.database import Store
from loketkecil.http import Server, ASSETS
from loketkecil.validation import AppError

NOW = datetime(2026, 11, 15, 17, 30, tzinfo=timezone.utc)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "queue.sqlite3"
        self.store = Store(self.path, clock=lambda: NOW)
        self.server = Server(("127.0.0.1", 0), self.store)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.02), daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.tmp.cleanup()

    def request(self, method, path, value=None, *, key=None, raw=None, headers=None):
        body = raw if raw is not None else None if value is None else json.dumps(value, ensure_ascii=False).encode()
        h = {"Content-Type": "application/json", **(headers or {})}
        if method == "POST":
            h["Idempotency-Key"] = key or str(uuid.uuid4())
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=6)
        try:
            conn.request(method, path, body, h)
            response = conn.getresponse()
            data = response.read()
            if "application/json" in response.getheader("Content-Type", ""):
                data = json.loads(data)
            return response.status, data, dict(response.getheaders())
        finally:
            conn.close()

    def post(self, data, **kwargs):
        return self.request("POST", "/api/mutate", data, **kwargs)

    def state(self):
        status, data, _ = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        return data

    def create(self, day="2026-11-16"):
        status, data, _ = self.post({"action": "create", "title": "Meja kegiatan sintetis", "day": day, "counters": ["Loket 1", "Loket 2"]})
        self.assertEqual(status, 200, data)
        return data["result"]["session_id"]

    def issue(self, sid, alias="Tamu sintetis", **kwargs):
        status, data, _ = self.post({"action": "issue", "session_id": sid, "alias": alias}, **kwargs)
        self.assertEqual(status, 200, data)
        return data["result"]

    def call_payload(self, counter=0):
        state = self.state();c = state["counters"][counter]
        return {"action": "call", "session_id": state["selected"]["id"], "counter_id": c["id"], "expected_version": c["version"]}

    def transition(self, action, ticket):
        return {"action": action, "session_id": ticket["session_id"], "ticket_id": ticket["id"], "expected_version": ticket["version"]}

    def test_complete_flow_requeue_at_tail_and_archive(self):
        sid = self.create()
        for i in range(3):self.issue(sid, f"Contoh {i}")
        self.assertEqual(self.post(self.call_payload())[0], 200)
        t = next(t for t in self.state()["tickets"] if t["status"] == "serving")
        self.assertEqual(t["code"], "A001")
        self.assertEqual(self.post(self.transition("skip", t))[0], 200)
        t = next(t for t in self.state()["tickets"] if t["status"] == "skipped")
        self.assertEqual(self.post(self.transition("requeue", t))[0], 200)
        self.assertEqual([t["code"] for t in self.state()["tickets"]], ["A002", "A003", "A001"])
        for expected in ("A002", "A003", "A001"):
            status, result, _ = self.post(self.call_payload())
            self.assertEqual((status, result["result"]["code"]), (200, expected))
            t = next(t for t in self.state()["tickets"] if t["status"] == "serving")
            self.assertEqual(self.post(self.transition("finish", t))[0], 200)
        self.assertEqual(self.post({"action": "close", "session_id": sid})[0], 200)
        state = self.state();self.assertIsNone(state["active_id"]);self.assertEqual(state["counts"]["done"], 3)
        self.assertEqual(self.post({"action": "issue", "session_id": sid, "alias": "Telat"})[0], 409)

    def test_parallel_counters_never_claim_same_ticket(self):
        sid = self.create();self.issue(sid);self.issue(sid)
        commands = [self.call_payload(0), self.call_payload(1)]
        barrier = threading.Barrier(2)
        def run(data):barrier.wait();return self.post(data)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, commands))
        self.assertEqual([r[0] for r in results], [200, 200])
        self.assertEqual({r[1]["result"]["code"] for r in results}, {"A001", "A002"})
        state = self.state();self.assertEqual(state["counts"]["serving"], 2)
        self.assertEqual(len({c["ticket"]["id"] for c in state["counters"]}), 2)

    def test_parallel_same_counter_has_one_winner(self):
        sid = self.create();self.issue(sid);self.issue(sid)
        payload = self.call_payload();barrier = threading.Barrier(2)
        def run(_):barrier.wait();return self.post(payload)[0]
        with ThreadPoolExecutor(max_workers=2) as pool:statuses = list(pool.map(run, range(2)))
        self.assertEqual(sorted(statuses), [200, 409]);self.assertEqual(self.state()["counts"]["serving"], 1);self.assertEqual(self.state()["counts"]["waiting"], 1)

    def test_parallel_issuance_numbers_are_unique_contiguous(self):
        sid = self.create()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda i: self.issue(sid, f"Tamu {i}"), range(20)))
        self.assertEqual({r["code"] for r in results}, {f"A{i:03d}" for i in range(1,21)})
        self.assertEqual(self.state()["counts"]["waiting"], 20)

    def test_parallel_identical_request_is_applied_once(self):
        sid = self.create();payload = {"action": "issue", "session_id": sid, "alias": "Satu"};key = "same-command-001"
        with ThreadPoolExecutor(max_workers=6) as pool:results = list(pool.map(lambda _: self.post(payload, key=key), range(12)))
        self.assertTrue(all(r[0] == 200 for r in results));self.assertEqual(sum(not r[1]["replayed"] for r in results), 1)
        self.assertEqual({r[1]["result"]["code"] for r in results}, {"A001"});self.assertEqual(len(self.state()["tickets"]), 1)

    def test_reply_body_lost_then_retry_after_reopen(self):
        sid = self.create();payload = {"action": "issue", "session_id": sid, "alias": "Koneksi contoh"};key = "lost-response-001"
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        conn.request("POST", "/api/mutate", json.dumps(payload), {"Content-Type": "application/json", "Idempotency-Key": key})
        response = conn.getresponse();self.assertEqual(response.status, 200);conn.close()  # sengaja buang body jawaban
        self.server.store = Store(self.path, clock=lambda: NOW)
        status, result, headers = self.post(payload, key=key)
        self.assertEqual(status, 200);self.assertTrue(result["replayed"]);self.assertEqual(headers["Idempotency-Replayed"], "true");self.assertEqual(len(self.state()["tickets"]), 1)

    def test_key_payload_mismatch_is_rejected(self):
        sid = self.create();self.issue(sid, "Awal", key="repeat-key-001")
        status, _, _ = self.post({"action": "issue", "session_id": sid, "alias": "Berbeda"}, key="repeat-key-001")
        self.assertEqual(status, 409);self.assertEqual(len(self.state()["tickets"]), 1)

    def test_audit_failure_rolls_back_call_counter_and_request(self):
        sid = self.create();self.issue(sid);before = self.state();payload = self.call_payload();key = "rollback-call-001"
        with self.store.connect() as db:db.execute("CREATE TRIGGER fail_call BEFORE INSERT ON events WHEN NEW.kind='call' BEGIN SELECT RAISE(ABORT,'injected'); END")
        status, error, _ = self.post(payload, key=key)
        self.assertEqual(status, 503);self.assertNotIn("injected", error["error"]);self.assertEqual(self.state(), before)
        with self.store.connect() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM requests WHERE key=?", (key,)).fetchone());db.execute("DROP TRIGGER fail_call")
        status, result, _ = self.post(payload, key=key)
        self.assertEqual(status, 200);self.assertFalse(result["replayed"]);self.assertEqual(result["result"]["code"], "A001")

    def test_audit_failure_does_not_consume_issued_number(self):
        sid = self.create()
        with self.store.connect() as db:db.execute("CREATE TRIGGER fail_issue BEFORE INSERT ON events WHEN NEW.kind='issue' BEGIN SELECT RAISE(ABORT,'fail'); END")
        self.assertEqual(self.post({"action": "issue", "session_id": sid, "alias": "X"})[0], 503)
        self.assertEqual(self.state()["tickets"], [])
        with self.store.connect() as db:db.execute("DROP TRIGGER fail_issue")
        self.assertEqual(self.issue(sid)["code"], "A001")

    def test_stale_finish_does_not_finish_next_customer(self):
        sid = self.create();self.issue(sid);self.issue(sid);self.post(self.call_payload())
        first = next(t for t in self.state()["tickets"] if t["status"] == "serving")
        payload = self.transition("finish", first);self.assertEqual(self.post(payload)[0], 200);self.post(self.call_payload())
        self.assertEqual(self.post(payload)[0], 409);self.assertEqual(next(c["ticket"]["code"] for c in self.state()["counters"] if c["ticket"]), "A002")

    def test_cancelled_number_is_never_reused(self):
        sid = self.create();self.issue(sid);t = self.state()["tickets"][0]
        self.assertEqual(self.post(self.transition("cancel", t))[0], 200);self.assertEqual(self.issue(sid)["code"], "A002")

    def test_close_with_unfinished_queue_is_rejected(self):
        sid = self.create();self.issue(sid);before = self.state();self.assertEqual(self.post({"action":"close","session_id":sid})[0],409);self.assertEqual(self.state(),before)

    def test_open_session_and_duplicate_day_are_protected(self):
        sid = self.create();payload = {"action":"create","title":"Lain","day":"2026-11-17","counters":["Satu"]}
        self.assertEqual(self.post(payload)[0],409);self.post({"action":"close","session_id":sid});payload["day"]="2026-11-16";self.assertEqual(self.post(payload)[0],409)
        payload["day"]="2026-11-17";self.assertEqual(self.post(payload)[0],200);self.assertEqual(self.state()["selected"]["day"],"2026-11-17")

    def test_skipped_can_remain_in_closed_archive(self):
        sid=self.create();self.issue(sid);self.post(self.call_payload());t=self.state()["tickets"][0];self.post(self.transition("skip",t))
        self.assertEqual(self.post({"action":"close","session_id":sid})[0],200);self.assertEqual(self.state()["counts"]["skipped"],1)

    def test_demo_is_synthetic_and_cannot_overwrite(self):
        status,result,_=self.post({"action":"demo"});self.assertEqual(status,200);state=self.state()
        self.assertEqual(state["today"],"2026-11-16");self.assertEqual(state["counts"],{"waiting":3,"serving":1,"done":1,"skipped":0,"cancelled":0});self.assertEqual(state["selected"]["synthetic"],1)
        self.assertEqual(self.post({"action":"demo"})[0],409);self.assertEqual(self.state(),state)

    def test_display_whitelist_does_not_include_alias(self):
        sid=self.create();self.issue(sid,"RAHASIA-ALIAS-123");self.post(self.call_payload())
        status,data,_=self.request("GET","/api/display");self.assertEqual(status,200);serialized=json.dumps(data)
        self.assertNotIn("RAHASIA-ALIAS",serialized);self.assertNotIn('"alias"',serialized);self.assertEqual(data["counters"][0]["code"],"A001")

    def test_csv_has_all_statuses_and_neutralizes_formulas(self):
        sid=self.create();self.issue(sid,"=SUM(1,2)");self.issue(sid,"Normal");self.post(self.transition("cancel",self.state()["tickets"][1]))
        status,data,headers=self.request("GET",f"/api/report.csv?session_id={sid}");self.assertEqual(status,200);rows=list(csv.reader(io.StringIO(data.decode('utf-8-sig'))))
        self.assertEqual(len(rows),3);self.assertEqual(rows[1][2],"'=SUM(1,2)");self.assertEqual(rows[2][3],"cancelled");self.assertIn('attachment',headers['Content-Disposition'])

    def test_backup_restores_queue_and_replay_records(self):
        sid=self.create();self.issue(sid,key="backup-issue-001");status,raw,_=self.request("GET","/api/backup.sqlite3");self.assertEqual(status,200)
        path=Path(self.tmp.name)/'restored.sqlite3';path.write_bytes(raw);restored=Store(path,clock=lambda:NOW)
        self.assertEqual(restored.state()["tickets"],self.state()["tickets"])
        result,replayed=restored.mutate({"action":"issue","session_id":sid,"alias":"Tamu sintetis"},"backup-issue-001");self.assertTrue(replayed);self.assertEqual(result['code'],'A001')

    def test_unknown_database_schema_is_not_replaced(self):
        path=Path(self.tmp.name)/'foreign.sqlite3'
        with sqlite3.connect(path) as db:db.execute('CREATE TABLE important(value TEXT)');db.execute("INSERT INTO important VALUES('keep')");db.execute('PRAGMA user_version=9')
        with self.assertRaises(AppError):Store(path)
        with sqlite3.connect(path) as db:self.assertEqual(db.execute('SELECT value FROM important').fetchone()[0],'keep')

    def test_invalid_inputs_do_not_mutate(self):
        for payload in [[],{'action':'missing'},{'action':'demo','extra':1},{'action':'create','title':'X','day':'2026-02-30','counters':['A']},{'action':'create','title':'X','day':'2026-11-16','counters':['A','a']},{'action':'issue','session_id':True,'alias':'X'}]:
            with self.subTest(payload=payload):self.assertEqual(self.post(payload)[0],400)
        self.assertEqual(self.state()['sessions'],[])

    def test_json_duplicate_fields_and_non_finite_numbers_rejected(self):
        for raw in [b'{"action":"demo","action":"close"}',b'{"action":"issue","session_id":NaN,"alias":"x"}',b'\xff']:
            with self.subTest(raw=raw):self.assertEqual(self.request('POST','/api/mutate',raw=raw)[0],400)
        self.assertEqual(self.state()['sessions'],[])

    def test_foreign_origin_host_and_wrong_content_type_rejected(self):
        for headers,status in [({'Origin':'https://foreign.example'},403),({'Host':'foreign.example'},403),({'Content-Type':'text/plain'},415)]:
            with self.subTest(headers=headers):self.assertEqual(self.post({'action':'demo'},headers=headers)[0],status)
        self.assertEqual(self.post({'action':'demo'},key='bad')[0],400)

    def test_unknown_paths_and_query_inputs_are_rejected(self):
        for route in ['/../server.py','/%2e%2e/server.py','/.git/config','/data/loketkecil.sqlite3','/unknown']:
            with self.subTest(route=route):self.assertEqual(self.request('GET',route)[0],404)
        for route in ['/api/state?session_id=-1','/api/state?other=1','/api/state?session_id=1&session_id=2']:
            self.assertEqual(self.request('GET',route)[0],400)

    def test_all_static_assets_exist_and_headers_disable_cache(self):
        for route in ASSETS:
            with self.subTest(route=route):
                status,data,headers=self.request('GET',route);self.assertEqual(status,200);self.assertGreater(len(data),10);self.assertEqual(headers['Cache-Control'],'no-store');self.assertEqual(headers['X-Content-Type-Options'],'nosniff')

    def test_empty_queue_call_and_incorrect_transition_rejected(self):
        sid=self.create();self.assertEqual(self.post(self.call_payload())[0],409);self.issue(sid);t=self.state()['tickets'][0]
        self.assertEqual(self.post(self.transition('finish',t))[0],409);self.assertEqual(self.post(self.transition('requeue',t))[0],409)

    def test_corrupt_database_startup_returns_error_without_overwriting(self):
        path=Path(self.tmp.name)/'corrupt.sqlite3';original=b'not-a-sqlite-database';path.write_bytes(original)
        with contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(launcher.main(['--db',str(path),'--no-browser']),1)
        self.assertIn('Belum dapat menjalankan',error.getvalue());self.assertEqual(path.read_bytes(),original)


if __name__=='__main__':unittest.main()
