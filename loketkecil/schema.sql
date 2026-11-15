BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL, day TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL, closed_at TEXT,
    synthetic INTEGER NOT NULL DEFAULT 0 CHECK (synthetic IN (0,1))
);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_session ON sessions((1)) WHERE closed_at IS NULL;
CREATE TABLE IF NOT EXISTS counters (
    id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id),
    label TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1 CHECK (version>0),
    UNIQUE(session_id,label)
);
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id),
    number INTEGER NOT NULL CHECK (number BETWEEN 1 AND 999), alias TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('waiting','serving','done','skipped','cancelled')),
    position INTEGER NOT NULL CHECK (position>0),
    counter_id INTEGER REFERENCES counters(id), version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL, called_at TEXT, finished_at TEXT,
    UNIQUE(session_id,number), CHECK (status!='serving' OR counter_id IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_ticket_per_counter ON tickets(counter_id) WHERE status='serving';
CREATE INDEX IF NOT EXISTS waiting_order ON tickets(session_id,status,position,id);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL REFERENCES sessions(id),
    kind TEXT NOT NULL, ticket_id INTEGER REFERENCES tickets(id), message TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS requests (
    key TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL
);
PRAGMA user_version=1;
COMMIT;
