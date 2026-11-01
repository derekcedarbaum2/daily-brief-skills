#!/usr/bin/env python3
"""Append-only interview history and idempotent review milestones in private state."""
import argparse
import copy
from contextlib import contextmanager
import datetime as dt
import importlib.util
import hashlib
import json
from pathlib import Path
import statistics
import uuid


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def history(db):
    return db.setdefault('history', {'schema_version': 1, 'invocations': {}, 'events': {}, 'reviews': {}})


def pending(h):
    done = {r['milestone'] for r in h['reviews'].values() if r['status'] in ('applied', 'no_change')}
    return [n for n in range(20, len(h['invocations']) + 1, 20) if n not in done]


def start(db, run_id, historical=False):
    h = history(db)
    if run_id not in db['runs']:
        raise ValueError('Create the run before starting its interview history')
    if run_id not in h['invocations']:
        h['invocations'][run_id] = {'number': len(h['invocations']) + 1, 'run_id': run_id,
                                  'registered_at': now(), 'historical': historical,
                                  'target_date': db['runs'][run_id].get('target_date')}
    return h['invocations'][run_id]


def append(records, key, value):
    if key in records:
        if records[key] != value:
            raise ValueError('Immutable record ID reused with different content: ' + key)
        return False
    records[key] = copy.deepcopy(value)
    return True


def migrate(db):
    h = history(db)
    for rid, run in sorted(db['runs'].items(), key=lambda x: (x[1].get('target_date') or '', x[0])):
        start(db, rid, historical=True)
        for index, item in enumerate(run.get('interview_decisions', [])):
            eid = str(uuid.uuid5(uuid.NAMESPACE_URL, 'daily-brief/legacy/' + rid + '/' + str(index)))
            if eid not in h['events']:
                h['events'][eid] = {'id': eid, 'run_id': rid, 'kind': 'legacy_decision',
                                    'source': 'Existing structured record; wording may be paraphrased',
                                    'recorded_at': item.get('answered_at'), 'legacy': copy.deepcopy(item)}
    return {'migrated_runs': len(h['invocations']), 'events': len(h['events'])}


def record(db, payload):
    h = history(db)
    event = payload['event']
    if not all(isinstance(event.get(k), str) and event[k] for k in ('id', 'run_id', 'kind', 'recorded_at')):
        raise ValueError('Event requires id, run_id, kind, recorded_at')
    if event['run_id'] not in h['invocations']:
        raise ValueError('Start the run first')
    if event['kind'] not in ('question', 'answer', 'rundown', 'decision', 'correction', 'task_update', 'feedback', 'outcome'):
        raise ValueError('Unknown event kind')
    if event['kind'] in ('question', 'answer', 'rundown', 'feedback') and not isinstance(event.get('text'), str):
        raise ValueError('Capture the actual text')
    if event['kind'] == 'question' and not event.get('question_key'):
        raise ValueError('Question requires a stable question_key')
    if event['kind'] == 'answer':
        question = h['events'].get(event.get('question_id'))
        if not question or question['kind'] != 'question' or question['run_id'] != event['run_id']:
            raise ValueError('Answer must link to a question in this run')
        if event.get('status') not in ('answered', 'skipped', 'deferred', 'declined'):
            raise ValueError('Answer requires an explicit status')
    if event.get('supersedes') and event['supersedes'] not in h['events']:
        raise ValueError('Correction refers to a missing event')
    # Save the transaction envelope so a retry cannot silently change its patches.
    envelope = copy.deepcopy(event)
    envelope['transaction_sha256'] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    envelope['updates'] = [{'collection': u['collection'], 'id': u['id']} for u in payload.get('updates', [])]
    if not append(h['events'], event['id'], envelope):
        return {'id': event['id'], 'replayed': True}
    for update in payload.get('updates', []):
        collection = update['collection']
        if collection not in ('runs', 'commitments', 'outcomes', 'patterns'):
            raise ValueError('Unsupported update collection')
        if not isinstance(update.get('record'), dict) or not isinstance(update.get('id'), str) or not update['id']:
            raise ValueError('Update needs a stable ID and object record')
        db[collection][update['id']] = copy.deepcopy(update['record'])
    return {'id': event['id'], 'replayed': False}


def review(db, value):
    h = history(db)
    n = value.get('milestone')
    if type(n) is not int or n < 20 or n % 20 or n > len(h['invocations']):
        raise ValueError('Review milestone is not due')
    if not all(value.get(k) for k in ('id', 'recorded_at', 'findings', 'evidence_ids', 'checks')):
        raise ValueError('Review requires findings, evidence, and checks')
    if value.get('status') not in ('applied', 'no_change', 'deferred'):
        raise ValueError('Invalid review status')
    if any(e not in h['events'] for e in value['evidence_ids']):
        raise ValueError('Unknown review evidence ID')
    if value['status'] == 'applied' and not value.get('changes'):
        raise ValueError('Applied review requires changes and verification details')
    if value['status'] in ('applied', 'no_change') and not all(isinstance(c, dict) and c.get('passed') is True for c in value['checks']):
        raise ValueError('Completion requires passing checks')
    append(h['reviews'], value['id'], value)
    return {'review_id': value['id'], 'evaluation_due': pending(h)}


def evidence(db, offset=0, limit=100):
    h = history(db)
    events = list(h['events'].values())
    metrics = {}
    for e in events:
        if e['kind'] != 'question':
            continue
        row = metrics.setdefault(e['question_key'], {'asked': 0, 'answered': 0, 'skipped': 0, 'deferred': 0, 'declined': 0})
        row['asked'] += 1
    latest_answers = {e['question_id']: e for e in events if e['kind'] == 'answer'}
    for e in latest_answers.values():
        q = h['events'][e['question_id']]
        metrics[q['question_key']][e['status']] += 1
    latency = [e['response_latency_ms'] for e in events if isinstance(e.get('response_latency_ms'), (float, int)) and e['response_latency_ms'] >= 0]
    return {'evaluation_due': pending(h), 'question_metrics': metrics,
            'median_measured_response_latency_ms': statistics.median(latency) if latency else None,
            'total_events': len(events), 'events': events[offset:offset + limit],
            'next_offset': offset + limit if offset + limit < len(events) else None,
            'reviews': h['reviews']}


def backend(path):
    directory = Path(__file__).resolve().parent
    generic = (directory / 'state.py').exists()
    spec = importlib.util.spec_from_file_location('_brief_state', directory / ('state.py' if generic else 'database.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = Path(path).expanduser().resolve() if path else (module.data_root() / 'database.json' if generic else module.DEFAULT)
    if generic:
        module.assert_private(target)
    return module, target, generic


@contextmanager
def locked(module, path, generic):
    if generic:
        with module.lock(path.parent):
            yield
    else:
        with open(str(path) + '.lock', 'a') as handle:
            module.fcntl.flock(handle, module.fcntl.LOCK_EX)
            yield


def save(module, path, generic, db):
    raw = (json.dumps(db, indent=2, ensure_ascii=False) + '\n').encode()
    if generic:
        module.atomic_write(path, raw, path.parent / 'backups')
    else:
        import os
        import tempfile
        backups = path.parent / 'Backups'
        backups.mkdir(exist_ok=True)
        (backups / (dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')).write_bytes(path.read_bytes())
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.history-')
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        if path.read_bytes() != raw:
            raise OSError('Readback verification failed')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('migrate', 'start', 'record', 'review', 'context', 'evidence'))
    p.add_argument('--database')
    p.add_argument('--run-id')
    p.add_argument('--input', type=Path)
    p.add_argument('--expected-revision', type=int)
    p.add_argument('--offset', type=int, default=0)
    p.add_argument('--limit', type=int, default=100)
    a = p.parse_args()
    try:
        module, path, generic = backend(a.database)
        with locked(module, path, generic):
            db = json.loads(path.read_text())
            validate = module.validate_database if generic else module.validate
            validate(db)
            before = copy.deepcopy(db)
            if a.action not in ('context', 'evidence') and a.expected_revision != db['revision']:
                raise ValueError('Revision changed or missing; reread context and merge')
            if a.action == 'context':
                h = history(db)
                result = {'run': db['runs'].get(a.run_id), 'invocation': h['invocations'].get(a.run_id),
                          'evaluation_due': pending(h),
                          'open_commitments': {k: v for k, v in db['commitments'].items() if v.get('status') not in ('done', 'complete', 'completed', 'cancelled')},
                          'recent_events': [e for e in h['events'].values() if e['run_id'] == a.run_id][-8:]}
            elif a.action == 'evidence':
                if a.offset < 0 or not 1 <= a.limit <= 500:
                    raise ValueError('Invalid pagination')
                result = evidence(db, a.offset, a.limit)
            elif a.action == 'migrate':
                result = migrate(db)
            elif a.action == 'start':
                result = {'invocation': start(db, a.run_id), 'evaluation_due': pending(history(db))}
            else:
                payload = json.loads(a.input.read_text())
                result = record(db, payload) if a.action == 'record' else review(db, payload)
            if a.action not in ('context', 'evidence') and db != before:
                db['revision'] += 1
                db['updated_at'] = now()
                validate(db)
                save(module, path, generic, db)
            result.update(revision=db['revision'], verified=True)
            print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        print(json.dumps({'error': str(e)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
