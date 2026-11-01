import copy
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / 'skills/daily-brief/scripts/memory.py'
spec = importlib.util.spec_from_file_location('brief_memory', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def database():
    return {'schema_version': 1, 'revision': 0, 'runs': {}, 'commitments': {}, 'outcomes': {}, 'patterns': {}}


def question(rid='r1', eid='q1'):
    return {'event': {'id': eid, 'run_id': rid, 'kind': 'question', 'question_key': 'daily.food',
                      'text': 'What needs preparing?', 'recorded_at': '2026-01-01T12:00:00Z'}}


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.db = database()
        self.db['runs']['r1'] = {'target_date': '2026-01-01', 'interview_decisions': [{'question': 'Old question', 'answer': 'Old answer'}]}

    def test_migration_is_idempotent_and_preserves_source(self):
        original = copy.deepcopy(self.db['runs'])
        m.migrate(self.db)
        once = copy.deepcopy(self.db)
        m.migrate(self.db)
        self.assertEqual(once, self.db)
        self.assertEqual(original, self.db['runs'])
        event = next(iter(self.db['history']['events'].values()))
        self.assertIsNone(event['recorded_at'])
        self.assertIn('paraphrased', event['source'])

    def test_resume_and_twentieth_milestone(self):
        for n in range(1, 42):
            rid = 'r' + str(n)
            self.db['runs'].setdefault(rid, {})
            m.start(self.db, rid)
            m.start(self.db, rid)
            self.assertEqual(len(self.db['history']['invocations']), n)
            self.assertEqual(m.pending(self.db['history']), [i for i in (20, 40) if i <= n])

    def test_replay_and_collision(self):
        m.start(self.db, 'r1')
        payload = question()
        m.record(self.db, payload)
        self.assertTrue(m.record(self.db, payload)['replayed'])
        changed = copy.deepcopy(payload)
        changed['updates'] = [{'collection': 'commitments', 'id': 'task', 'record': {}}]
        with self.assertRaises(ValueError):
            m.record(self.db, changed)

    def test_answer_and_correction_preserve_history(self):
        m.start(self.db, 'r1')
        m.record(self.db, question())
        answer = {'id': 'a1', 'run_id': 'r1', 'kind': 'answer', 'question_id': 'q1', 'status': 'answered', 'text': 'None', 'recorded_at': '2026-01-01T12:01:00Z'}
        m.record(self.db, {'event': answer})
        m.record(self.db, {'event': {'id': 'a2', 'run_id': 'r1', 'kind': 'correction', 'supersedes': 'a1', 'text': 'Pack lunch', 'recorded_at': '2026-01-01T12:02:00Z'}})
        self.assertEqual(self.db['history']['events']['a1']['text'], 'None')
        self.assertEqual(m.evidence(self.db)['question_metrics']['daily.food']['answered'], 1)

    def test_large_updates_stay_out_of_history(self):
        m.start(self.db, 'r1')
        payload = question()
        payload['updates'] = [{'collection': 'runs', 'id': 'r1', 'record': {'notes': 'x' * 10000}}]
        m.record(self.db, payload)
        self.assertLess(len(json.dumps(self.db['history']['events']['q1'])), 600)
        self.assertEqual(len(self.db['runs']['r1']['notes']), 10000)

    def test_answer_revision_counts_once(self):
        m.start(self.db, 'r1')
        m.record(self.db, question())
        for eid, status in [('a1', 'deferred'), ('a2', 'answered')]:
            m.record(self.db, {'event': {'id': eid, 'run_id': 'r1', 'kind': 'answer', 'question_id': 'q1', 'status': status, 'text': status, 'recorded_at': 'now'}})
        metrics = m.evidence(self.db)['question_metrics']['daily.food']
        self.assertEqual(metrics['answered'], 1)
        self.assertEqual(metrics['deferred'], 0)

    def test_answer_requires_question(self):
        m.start(self.db, 'r1')
        with self.assertRaises(ValueError):
            m.record(self.db, {'event': {'id': 'a1', 'run_id': 'r1', 'kind': 'answer', 'text': 'yes', 'recorded_at': 'now', 'question_id': 'missing', 'status': 'answered'}})

    def test_review_requires_actual_checks_and_only_clears_due_milestone(self):
        for n in range(1, 41):
            rid = 'r' + str(n)
            self.db['runs'].setdefault(rid, {})
            m.start(self.db, rid)
        m.record(self.db, question())
        review = {'id': 'review1', 'milestone': 20, 'recorded_at': 'now', 'status': 'no_change',
                  'findings': ['No supported improvement'], 'evidence_ids': ['q1'], 'checks': [{'passed': False}]}
        with self.assertRaises(ValueError):
            m.review(self.db, review)
        self.assertEqual(m.pending(self.db['history']), [20, 40])
        review['checks'][0]['passed'] = True
        m.review(self.db, review)
        self.assertEqual(m.pending(self.db['history']), [40])

    def test_paging_never_silently_loses_events(self):
        m.start(self.db, 'r1')
        for n in range(5):
            m.record(self.db, question(eid='q' + str(n)))
        ids, offset = [], 0
        while offset is not None:
            page = m.evidence(self.db, offset, 2)
            ids += [e['id'] for e in page['events']]
            offset = page['next_offset']
        self.assertEqual(len(set(ids)), 5)

    def test_cli_atomic_failure_stale_revision_and_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'database.json'
            path.write_text(json.dumps(self.db))
            def run(action, *args):
                return subprocess.run([sys.executable, '-B', str(SCRIPT), action, '--database', str(path), *args], capture_output=True, text=True)
            self.assertEqual(run('migrate', '--expected-revision', '0').returncode, 0)
            before = path.read_bytes()
            self.assertNotEqual(run('start', '--run-id', 'r1', '--expected-revision', '0').returncode, 0)
            payload = question()
            payload['updates'] = [{'collection': 'history', 'id': 'bad', 'record': {}}]
            p = pathlib.Path(directory) / 'event.json'
            p.write_text(json.dumps(payload))
            self.assertNotEqual(run('record', '--input', str(p), '--expected-revision', '1').returncode, 0)
            self.assertEqual(path.read_bytes(), before)
            payload['updates'] = [{'collection': 'commitments', 'id': 'task1', 'record': {'status': 'open'}}]
            p.write_text(json.dumps(payload))
            self.assertEqual(run('record', '--input', str(p), '--expected-revision', '1').returncode, 0)
            saved = json.loads(path.read_text())
            self.assertEqual(saved['revision'], 2)
            self.assertEqual(saved['commitments']['task1']['status'], 'open')
            self.assertIn('q1', saved['history']['events'])
            self.assertTrue(list((path.parent / 'backups').glob('*.json')))

    def test_public_path_rejected(self):
        with self.assertRaises(ValueError):
            m.backend(SCRIPT.parent / 'database.json')


if __name__ == '__main__':
    unittest.main()
