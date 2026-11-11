import concurrent.futures
import http.client
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

from server import MAX_BODY, Problem, Store, make_server


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'records.sqlite3'
        self.store = Store(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def get(self, table, record_id):
        return next(row for row in self.store.snapshot()[table] if row['id'] == record_id)

    def assertProblem(self, status, call):
        with self.assertRaises(Problem) as caught:
            call()
        self.assertEqual(caught.exception.status, status)
        return caught.exception

    def test_linked_seed_and_persistence_without_reseed(self):
        self.assertEqual(len(self.store.snapshot()['members']), 5)
        self.store.update('members', 1, {'version': 1, 'name': 'Copper Kite Updated'})
        reopened = Store(self.path).snapshot()
        self.assertEqual(reopened['members'][0]['name'], 'Copper Kite Updated')
        self.assertEqual(len(reopened['events']), 4)
        self.assertEqual(len(reopened['engagements']), 9)
        self.assertEqual(len(reopened['history']), 1)
        members = {row['id'] for row in reopened['members']}
        events = {row['id'] for row in reopened['events']}
        self.assertTrue(all(row['member_id'] in members and row['event_id'] in events for row in reopened['engagements']))

    def test_overlap_rejected_and_status_and_notes_unchanged(self):
        before = self.get('engagements', 3)
        error = self.assertProblem(409, lambda: self.store.update('engagements', 3, {'version': 1, 'status': 'confirmed'}))
        self.assertEqual(error.reasons[0]['type'], 'overlap')
        self.assertEqual(error.reasons[0]['event_id'], 1)
        self.assertEqual(self.get('engagements', 3), before)
        self.assertEqual(self.store.snapshot()['history'], [])

    def test_capacity_rejected_then_released_slot_can_be_confirmed(self):
        error = self.assertProblem(409, lambda: self.store.update('engagements', 6, {'version': 1, 'status': 'confirmed'}))
        self.assertEqual(error.reasons[0]['type'], 'capacity')
        self.store.update('engagements', 5, {'version': 1, 'status': 'declined'})
        changed = self.store.update('engagements', 6, {'version': 1, 'status': 'confirmed'})
        self.assertEqual(changed['status'], 'confirmed')

    def test_nonoverlapping_boundary_is_allowed(self):
        self.store.update('events', 2, {'version': 1, 'start': '2030-06-15T11:30Z'})
        self.store.update('engagements', 3, {'version': 1, 'status': 'confirmed'})
        self.assertEqual(self.get('engagements', 3)['status'], 'confirmed')

    def test_reschedule_protects_confirmed_members(self):
        before = self.get('events', 4)
        error = self.assertProblem(409, lambda: self.store.update('events', 4, {'version': 1, 'start': '2030-06-15T10:15Z', 'end': '2030-06-15T11:00Z'}))
        self.assertEqual(error.reasons[0]['event_id'], 1)
        self.assertIn('Copper Kite', error.reasons[0]['message'])
        self.assertEqual(before, self.get('events', 4))

    def test_reduced_capacity_cannot_displace_confirmed_members(self):
        self.store.update('engagements', 2, {'version': 1, 'status': 'confirmed'})
        self.assertProblem(409, lambda: self.store.update('events', 1, {'version': 1, 'capacity': 1}))

    def test_stale_versions_rejected_on_all_entities(self):
        for table, values in [('members', {'bio': 'New profile.'}), ('events', {'location': 'East Workshop'}), ('engagements', {'notes': 'Bring a mat.'})]:
            with self.subTest(table=table):
                self.store.update(table, 1, {'version': 1, **values})
                before = self.get(table, 1)
                self.assertProblem(409, lambda: self.store.update(table, 1, {'version': 1, **values}))
                self.assertEqual(before, self.get(table, 1))

    def test_edits_preserve_logistics_and_other_fields(self):
        before = self.get('engagements', 1)
        event_notes = self.get('events', 1)['notes']
        self.store.update('members', 1, {'version': 1, 'specialty': 'Moving sculpture'})
        self.store.update('events', 1, {'version': 1, 'title': 'New title', 'start': '2030-06-15T09:45Z'})
        self.assertEqual(before, self.get('engagements', 1))
        self.assertEqual(event_notes, self.get('events', 1)['notes'])
        self.store.update('engagements', 1, {'version': 1, 'notes': 'Keep the original crate.'})
        self.store.update('engagements', 1, {'version': 2, 'status': 'declined'})
        self.assertEqual(self.get('engagements', 1)['notes'], 'Keep the original crate.')
        self.assertEqual(Store(self.path).snapshot()['engagements'][0]['notes'], 'Keep the original crate.')

    def test_atomic_race_cannot_overbook_last_slot(self):
        self.store.update('engagements', 5, {'version': 1, 'status': 'declined'})
        barrier = threading.Barrier(2)
        def confirm(record_id, version):
            barrier.wait(timeout=3)
            try:
                self.store.update('engagements', record_id, {'version': version, 'status': 'confirmed'})
                return 200
            except Problem as error:
                return error.status
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(confirm, 5, 2), pool.submit(confirm, 6, 1)]
            self.assertEqual(sorted(future.result(timeout=5) for future in futures), [200, 409])
        self.assertEqual(sum(row['event_id'] == 3 and row['status'] == 'confirmed' for row in self.store.snapshot()['engagements']), 1)

    def test_atomic_race_cannot_confirm_overlapping_appearances(self):
        self.store.update('engagements', 1, {'version': 1, 'status': 'invited'})
        barrier = threading.Barrier(2)
        def confirm(record_id, version):
            barrier.wait(timeout=3)
            try:
                self.store.update('engagements', record_id, {'version': version, 'status': 'confirmed'})
                return 200
            except Problem as error:
                return error.status
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(confirm, 1, 2), pool.submit(confirm, 3, 1)]
            self.assertEqual(sorted(future.result(timeout=5) for future in futures), [200, 409])

    def test_validation_and_noop_history(self):
        self.store.update('members', 1, {'version': 1, 'name': 'Copper Kite'})
        self.assertEqual(self.get('members', 1)['version'], 1)
        self.assertEqual(self.store.snapshot()['history'], [])
        invalid = [
            ('events', {'version': 1, 'capacity': True}),
            ('events', {'version': 1, 'capacity': 0}),
            ('events', {'version': 1, 'start': '2030-02-30T10:00Z'}),
            ('events', {'version': 1, 'end': '2030-06-15T09:00Z'}),
            ('members', {'version': True, 'name': 'Test'}),
            ('members', {'version': 1, 'name': ''}),
            ('members', {'version': 1, 'name': '\ud800'}),
            ('members', {'version': 1, 'name': 'a' * 101}),
            ('members', {'version': 1, 'id': 2}),
            ('engagements', {'version': 1, 'status': 'maybe'}),
        ]
        for table, values in invalid:
            with self.subTest(values=values):
                self.assertProblem(400, lambda: self.store.update(table, 1, values))


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'http.sqlite3')
        self.server = make_server(self.store, 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

    def request(self, method='GET', path='/api/state', body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def raw(self, request):
        with socket.create_connection(('127.0.0.1', self.port), timeout=3) as connection:
            connection.sendall(request)
            response = b''
            while True:
                part = connection.recv(65536)
                if not part:
                    break
                response += part
        return int(response.split(b' ', 2)[1]), response

    def test_get_snapshot_assets_and_headers(self):
        status, headers, body = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)['engagements']), 9)
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(self.server.server_address[0], '127.0.0.1')
        for path in ['/', '/app.js', '/style.css']:
            self.assertEqual(self.request(path=path)[0], 200)

    def test_allowlist_does_not_expose_database_or_source(self):
        for path in ['/server.py', '/runtime/community.sqlite3', '/../server.py', '/%2e%2e/server.py', '/?other=1', '/web/index.html']:
            with self.subTest(path=path):
                self.assertEqual(self.request(path=path)[0], 404)

    def test_real_http_edit_and_stale_rejection(self):
        body = json.dumps({'version': 1, 'bio': 'Preserved across requests.'})
        headers = {'Content-Type': 'application/json', 'Origin': f'http://127.0.0.1:{self.port}'}
        status, _, result = self.request('PATCH', '/api/members/1', body, headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(result)['record']['version'], 2)
        self.assertEqual(self.request('PATCH', '/api/members/1', body, headers)[0], 409)
        self.assertEqual(json.loads(self.request()[2])['members'][0]['bio'], 'Preserved across requests.')

    def test_real_http_conflict_and_capacity_reason(self):
        for record_id, kind in [(3, 'overlap'), (6, 'capacity')]:
            status, _, body = self.request('PATCH', f'/api/engagements/{record_id}', json.dumps({'version': 1, 'status': 'confirmed'}), {'Content-Type': 'application/json'})
            self.assertEqual(status, 409)
            self.assertEqual(json.loads(body)['reasons'][0]['type'], kind)

    def test_invalid_json_and_surrogates(self):
        for body in [b'[]', b'{', b'{"version":1,"version":2,"name":"x"}', b'{"version":1,"name":"\\ud800"}', b'{"version":1,"bio":"\\udfff"}', b'{"version":NaN,"name":"x"}', b'{"version":1,"name":"\xff"}']:
            with self.subTest(body=body):
                self.assertEqual(self.request('PATCH', '/api/members/1', body, {'Content-Type': 'application/json'})[0], 400)

    def test_excessive_nesting_returns_a_coherent_client_error(self):
        deeply_nested = b'{"bio":' + b'[' * 1200 + b'0' + b']' * 1200 + b'}'
        self.assertEqual(self.request('PATCH', '/api/members/1', deeply_nested, {'Content-Type': 'application/json'})[0], 400)
        with patch('server.reject_surrogates', side_effect=RecursionError):
            status, _, body = self.request('PATCH', '/api/members/1', b'{"version":1,"bio":"x"}', {'Content-Type': 'application/json'})
        self.assertEqual(status, 400)
        self.assertIn('nesting', json.loads(body)['error'])

    def test_failed_history_insert_rolls_back_record_and_returns_json_error(self):
        before = self.store.snapshot()
        with self.store.transaction() as db:
            db.execute("CREATE TRIGGER fail_history BEFORE INSERT ON history BEGIN SELECT RAISE(ABORT, 'test constraint failure'); END")
        status, headers, body = self.request('PATCH', '/api/members/1', b'{"version":1,"name":"Changed alias"}', {'Content-Type': 'application/json'})
        self.assertEqual(status, 500)
        self.assertIn('application/json', headers['Content-Type'])
        self.assertIn('No partial changes', json.loads(body)['error'])
        self.assertEqual(self.store.snapshot(), before)

    def test_host_origin_and_fetch_site_guards(self):
        for headers in [{'Host': 'outside.example'}, {'Origin': 'https://outside.example'}, {'Origin': 'null'}, {'Sec-Fetch-Site': 'cross-site'}, {'Sec-Fetch-Site': 'same-site'}]:
            with self.subTest(headers=headers):
                self.assertEqual(self.request(headers=headers)[0], 403)

    def test_early_rejected_small_post_drains_body(self):
        self.assertEqual(self.request('POST', '/api/members/1', b'{}', {'Content-Type': 'application/json'})[0], 405)
        self.assertEqual(self.request('PATCH', '/api/members/1', b'{}', {'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.request('PATCH', '/api/members/1', b'{}', {'Host': 'outside.example', 'Content-Type': 'application/json'})[0], 403)

    def test_duplicate_headers_transfer_encoding_and_invalid_length(self):
        cases = [
            f'Host: 127.0.0.1:{self.port}\r\nHost: 127.0.0.1:{self.port}\r\n',
            f'Host: 127.0.0.1:{self.port}\r\nOrigin: x\r\nOrigin: y\r\n',
            f'Host: 127.0.0.1:{self.port}\r\nContent-Length: 0\r\nContent-Length: 0\r\n',
            f'Host: 127.0.0.1:{self.port}\r\nTransfer-Encoding: chunked\r\n',
            f'Host: 127.0.0.1:{self.port}\r\nContent-Length: -1\r\n',
        ]
        for headers in cases:
            with self.subTest(headers=headers):
                self.assertEqual(self.raw(f'GET /api/state HTTP/1.1\r\n{headers}Connection: close\r\n\r\n'.encode())[0], 400)

    def test_body_limit_before_reading_payload(self):
        request = f'PATCH /api/members/1 HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nContent-Type: application/json\r\nContent-Length: {MAX_BODY + 1}\r\nConnection: close\r\n\r\n'
        self.assertEqual(self.raw(request.encode())[0], 413)

    def test_stored_html_remains_literal_json_data(self):
        value = '<img src=x onerror=alert(1)>'
        self.assertEqual(self.request('PATCH', '/api/members/1', json.dumps({'version': 1, 'bio': value}), {'Content-Type': 'application/json'})[0], 200)
        self.assertEqual(json.loads(self.request()[2])['members'][0]['bio'], value)
        script = (Path(__file__).parents[1] / 'web' / 'app.js').read_text(encoding='utf-8')
        self.assertNotIn('innerHTML', script)
        self.assertNotIn('insertAdjacentHTML', script)


if __name__ == '__main__':
    unittest.main()
