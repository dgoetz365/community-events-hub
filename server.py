"""A local, single-user coordination demo. Python 3.12+, standard library only."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sqlite3
import socket

ROOT = Path(__file__).resolve().parent
MAX_BODY = 24_000
STATUSES = {"invited", "confirmed", "declined"}


class Problem(Exception):
    def __init__(self, status, message, reasons=None):
        super().__init__(message)
        self.status, self.message, self.reasons = status, message, reasons or []


def reject_surrogates(value):
    if isinstance(value, str):
        if any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise Problem(400, "Text contains an invalid Unicode surrogate.")
    elif isinstance(value, dict):
        for key, item in value.items():
            reject_surrogates(key)
            reject_surrogates(item)
    elif isinstance(value, list):
        for item in value:
            reject_surrogates(item)


def decode_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Problem(400, "JSON keys must be unique.")
            result[key] = value
        return result

    def constant(_):
        raise Problem(400, "JSON numbers must be finite.")

    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, ValueError, RecursionError):
        raise Problem(400, "Send a valid UTF-8 JSON object.") from None
    if not isinstance(data, dict):
        raise Problem(400, "Send a JSON object.")
    try:
        reject_surrogates(data)
    except RecursionError:
        raise Problem(400, "JSON nesting is too deep.") from None
    return data


def text_value(value, name, limit, required=True):
    if not isinstance(value, str):
        raise Problem(400, f"{name} must be text.")
    reject_surrogates(value)
    value = value.strip()
    if (required and not value) or len(value) > limit:
        raise Problem(400, f"{name} must contain {'1' if required else '0'}–{limit} characters.")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise Problem(400, f"{name} contains an unsupported control character.")
    return value


def time_value(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z", value):
        raise Problem(400, "Use a UTC time in YYYY-MM-DDTHH:MMZ format.")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%MZ")
    except ValueError:
        raise Problem(400, "The event date or time is invalid.") from None
    return value


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS members (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, specialty TEXT NOT NULL,
                    bio TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, title TEXT NOT NULL, location TEXT NOT NULL,
                    start TEXT NOT NULL, end TEXT NOT NULL, capacity INTEGER NOT NULL CHECK(capacity>0),
                    notes TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS engagements (
                    id INTEGER PRIMARY KEY, member_id INTEGER NOT NULL REFERENCES members(id),
                    event_id INTEGER NOT NULL REFERENCES events(id),
                    status TEXT NOT NULL CHECK(status IN ('invited','confirmed','declined')),
                    notes TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(member_id,event_id));
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY, at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                    entity TEXT NOT NULL, entity_id INTEGER NOT NULL, message TEXT NOT NULL);
            """)
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM metadata WHERE key='seeded'").fetchone():
                return
            db.executemany("INSERT INTO members(id,name,specialty,bio) VALUES(?,?,?,?)", [
                (1, "Copper Kite", "Kinetic sculpture", "Builds small moving objects from reclaimed materials."),
                (2, "Moss Circuit", "Repair & electronics", "Makes everyday repair approachable through hands-on sessions."),
                (3, "Paper Comet", "Printmaking", "Explores simple printing methods and collaborative editions."),
                (4, "Indigo Loom", "Textile experiments", "Pairs traditional weaving with unexpected found materials."),
                (5, "Cedar Echo", "Sound objects", "Turns discarded containers into playful acoustic instruments."),
            ])
            db.executemany("INSERT INTO events(id,title,location,start,end,capacity,notes) VALUES(?,?,?,?,?,?,?)", [
                (1, "Light & motion", "Workshop North", "2030-06-15T10:00Z", "2030-06-15T11:30Z", 2, "Open the side entrance at 09:30. Keep the demonstration table clear."),
                (2, "Repair circle", "Workshop South", "2030-06-15T11:00Z", "2030-06-15T12:00Z", 3, "Use the low-voltage bench. Label all brought-in objects."),
                (3, "Print exchange", "Paper Room", "2030-06-15T13:00Z", "2030-06-15T14:00Z", 1, "One presenter station. Drying racks arrive before noon."),
                (4, "Evening of small inventions", "Community Hall", "2030-06-15T17:00Z", "2030-06-15T18:30Z", 4, "Arrange chairs in a semicircle. Leave the center aisle open."),
            ])
            db.executemany("INSERT INTO engagements(id,member_id,event_id,status,notes) VALUES(?,?,?,?,?)", [
                (1, 1, 1, "confirmed", "Bring the hand-crank model. Needs one table and a nearby socket."),
                (2, 4, 1, "invited", "Display two fabric samples; no projector needed."),
                (3, 1, 2, "invited", "Asked to demonstrate hinge repair. Check overlap with Light & motion."),
                (4, 2, 2, "confirmed", "Bring the toolkit and three practice circuit boards."),
                (5, 2, 3, "confirmed", "Show a printed circuit pattern; reserve the single presenter station."),
                (6, 3, 3, "invited", "Needs a washable work surface and access to the sink."),
                (7, 1, 4, "confirmed", "Transport the model from Workshop North; retain the padded crate."),
                (8, 5, 4, "invited", "Five-minute sound demonstration. No amplification required."),
                (9, 4, 4, "declined", "Unavailable for the evening session; retain invitation history."),
            ])
            db.execute("INSERT INTO metadata VALUES('seeded','1')")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    @staticmethod
    def get(db, table, record_id):
        row = db.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone()
        if row is None:
            raise Problem(404, "This record does not exist.")
        return dict(row)

    @staticmethod
    def conflicts(db, member_id, event_id, start, end):
        return [dict(row) for row in db.execute("""
            SELECT e.id, e.title, e.start, e.end FROM engagements a
            JOIN events e ON e.id=a.event_id
            WHERE a.member_id=? AND a.status='confirmed' AND e.id<>?
            AND e.start < ? AND e.end > ? ORDER BY e.start, e.id
        """, (member_id, event_id, end, start))]

    def confirmation_reasons(self, db, engagement, event):
        reasons = []
        count = db.execute("SELECT count(*) FROM engagements WHERE event_id=? AND status='confirmed' AND id<>?", (event['id'], engagement['id'])).fetchone()[0]
        if count >= event['capacity']:
            reasons.append({"type": "capacity", "event_id": event['id'], "message": f"{event['title']} has all {event['capacity']} presenter slots filled."})
        for conflict in self.conflicts(db, engagement['member_id'], event['id'], event['start'], event['end']):
            reasons.append({"type": "overlap", "event_id": conflict['id'], "message": f"Already confirmed for {conflict['title']} ({conflict['start']} to {conflict['end']})."})
        return reasons

    def snapshot(self):
        with self.connect() as db:
            db.execute("BEGIN")
            result = {table: [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY id")] for table in ("members", "events", "engagements")}
            events = {event['id']: event for event in result['events']}
            for engagement in result['engagements']:
                engagement['reasons'] = self.confirmation_reasons(db, engagement, events[engagement['event_id']]) if engagement['status'] != 'confirmed' else []
            result['history'] = [dict(row) for row in db.execute("SELECT * FROM history ORDER BY id DESC LIMIT 100")]
            db.rollback()
            return result

    def update(self, table, record_id, data):
        if table not in {"members", "events", "engagements"}:
            raise Problem(404, "Unknown record type.")
        allowed = {"members": {"name", "specialty", "bio"}, "events": {"title", "location", "start", "end", "capacity", "notes"}, "engagements": {"status", "notes"}}[table]
        if set(data) - allowed - {"version"} or not (set(data) & allowed):
            raise Problem(400, "Supply version and one or more supported fields.")
        if type(data.get('version')) is not int or data['version'] < 1:
            raise Problem(400, "A positive integer version is required.")
        with self.transaction() as db:
            record = self.get(db, table, record_id)
            if data['version'] != record['version']:
                raise Problem(409, "This record changed in another tab. Refresh records, review the latest values, then try again.")
            values = {key: value for key, value in data.items() if key != 'version'}
            for key, value in values.items():
                if key in {'start', 'end'}:
                    values[key] = time_value(value)
                elif key == 'capacity':
                    if type(value) is not int or not 1 <= value <= 100:
                        raise Problem(400, "Presenter capacity must be an integer from 1 to 100.")
                elif key == 'status':
                    if not isinstance(value, str) or value not in STATUSES:
                        raise Problem(400, "Choose invited, confirmed, or declined.")
                else:
                    values[key] = text_value(value, key.capitalize(), 2000 if key in {'notes', 'bio'} else 100, required=key not in {'notes', 'bio'})
            merged = {**record, **values}
            if table == 'engagements' and merged['status'] == 'confirmed':
                event = self.get(db, 'events', record['event_id'])
                reasons = self.confirmation_reasons(db, merged, event)
                if reasons:
                    raise Problem(409, "Appearance cannot be confirmed. Resolve the reasons below and try again.", reasons)
            if table == 'events':
                if merged['end'] <= merged['start']:
                    raise Problem(400, "Event end must be after its start.")
                confirmed = db.execute("SELECT member_id FROM engagements WHERE event_id=? AND status='confirmed'", (record_id,)).fetchall()
                if len(confirmed) > merged['capacity']:
                    raise Problem(409, "Capacity cannot be lower than the number of confirmed presenters.")
                reasons = []
                for appearance in confirmed:
                    member = self.get(db, 'members', appearance['member_id'])
                    for conflict in self.conflicts(db, member['id'], record_id, merged['start'], merged['end']):
                        reasons.append({"type": "overlap", "event_id": conflict['id'], "message": f"{member['name']} is already confirmed for {conflict['title']} ({conflict['start']} to {conflict['end']})."})
                if reasons:
                    raise Problem(409, "Rescheduling would overlap a confirmed presenter's other event.", reasons)
            if all(record[key] == value for key, value in values.items()):
                return record
            assignments = ', '.join(f'{key}=?' for key in values)
            db.execute(f"UPDATE {table} SET {assignments}, version=version+1 WHERE id=?", (*values.values(), record_id))
            changed = ', '.join(key for key in values if record[key] != values[key])
            label = merged.get('name') or merged.get('title')
            if table == 'engagements':
                member = self.get(db, 'members', record['member_id'])
                event = self.get(db, 'events', record['event_id'])
                label = f"{member['name']} at {event['title']}"
                if 'status' in values and values['status'] != record['status']:
                    changed = f"{record['status']} → {values['status']}" + ("; logistics updated" if 'notes' in values and values['notes'] != record['notes'] else "")
            db.execute("INSERT INTO history(entity,entity_id,message) VALUES(?,?,?)", (table, record_id, f"{label}: {changed}."))
            return self.get(db, table, record_id)


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(3)
        return connection, address


def make_server(store, port=8766):
    class Handler(BaseHTTPRequestHandler):
        server_version = "CommunityDemo"
        sys_version = ""
        protocol_version = 'HTTP/1.0'

        def log_message(self, *_):
            pass

        def send(self, status, body, content_type='application/json; charset=utf-8'):
            self.close_connection = True
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            self.send_header('Connection', 'close')
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)

        def send_json(self, status, data):
            self.send(status, json.dumps(data, ensure_ascii=True).encode('utf-8'))

        def drain_small_body(self):
            lengths = self.headers.get_all('Content-Length', [])
            if self.headers.get('Transfer-Encoding') or len(lengths) != 1 or not re.fullmatch(r'\d{1,5}', lengths[0]):
                return
            length = int(lengths[0])
            if 0 < length <= MAX_BODY:
                try:
                    self.connection.settimeout(0.15)
                    self.rfile.read(length)
                except (OSError, TimeoutError):
                    pass

        def validate_request(self):
            seen = set()
            for key in self.headers.keys():
                key = key.lower()
                if key in seen:
                    raise Problem(400, "Duplicate headers are not accepted.")
                seen.add(key)
            if self.headers.get('Transfer-Encoding') is not None:
                raise Problem(400, "Transfer-Encoding is not supported.")
            actual_port = self.server.server_address[1]
            host = self.headers.get('Host')
            if host not in {f'127.0.0.1:{actual_port}', f'localhost:{actual_port}'}:
                raise Problem(403, "Use the local URL printed by the server.")
            origin = self.headers.get('Origin')
            if origin is not None and origin != f'http://{host}':
                raise Problem(403, "Cross-origin requests are not accepted.")
            fetch_site = self.headers.get('Sec-Fetch-Site')
            if fetch_site in {'cross-site', 'same-site'}:
                raise Problem(403, "Open this demo directly at its local URL.")
            raw_length = self.headers.get('Content-Length')
            if raw_length is not None and not re.fullmatch(r'\d{1,5}', raw_length):
                raise Problem(400, "Content-Length is invalid.")
            length = int(raw_length or 0)
            if length > MAX_BODY:
                raise Problem(413, "Request body is too large.")
            return length

        def dispatch(self):
            consumed = False
            try:
                length = self.validate_request()
                if self.command == 'GET':
                    if length:
                        raise Problem(400, "GET requests cannot contain a body.")
                    if self.path == '/api/state':
                        self.send_json(200, store.snapshot())
                        return
                    static = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
                    if self.path not in static:
                        raise Problem(404, "Route not found.")
                    filename, content_type = static[self.path]
                    self.send(200, (ROOT / 'web' / filename).read_bytes(), content_type)
                    return
                if self.command != 'PATCH':
                    raise Problem(405, "Use GET to read records or PATCH to edit a record.")
                route = re.fullmatch(r'/api/(members|events|engagements)/([1-9]\d{0,8})', self.path)
                if not route:
                    raise Problem(404, "Route not found.")
                if self.headers.get('Content-Type', '').lower() not in {'application/json', 'application/json; charset=utf-8'}:
                    raise Problem(415, "Use Content-Type: application/json.")
                if not length:
                    raise Problem(400, "A JSON request body is required.")
                consumed = True
                try:
                    raw = self.rfile.read(length)
                except (OSError, TimeoutError):
                    raise Problem(400, "Request body was not received in time.") from None
                if len(raw) != length:
                    raise Problem(400, "Request body is incomplete.")
                data = decode_json(raw)
                record = store.update(route[1], int(route[2]), data)
                self.send_json(200, {'record': record})
            except Problem as error:
                if not consumed:
                    self.drain_small_body()
                self.send_json(error.status, {'error': error.message, 'reasons': error.reasons})
            except sqlite3.OperationalError:
                self.send_json(503, {'error': 'The local database is busy. Try again shortly.', 'reasons': []})
            except sqlite3.Error:
                self.send_json(500, {'error': 'The database could not complete this request. No partial changes were saved.', 'reasons': []})
            except (BrokenPipeError, ConnectionResetError, socket.timeout):
                self.close_connection = True

        do_GET = dispatch
        do_PATCH = dispatch
        do_POST = dispatch
        do_PUT = dispatch
        do_DELETE = dispatch
        do_OPTIONS = dispatch
        do_HEAD = dispatch

    return LocalServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--db', type=Path, default=ROOT / 'runtime' / 'community.sqlite3')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    server = make_server(Store(args.db), args.port)
    print(f'Community Events Hub: http://127.0.0.1:{args.port}', flush=True)
    print('Local single-user demo. All people and events are fictional. Press Ctrl+C to stop.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
