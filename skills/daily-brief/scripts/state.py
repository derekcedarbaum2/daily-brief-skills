#!/usr/bin/env python3
"""Private Daily Brief state with optimistic revisions, backups, and atomic writes."""
import argparse
from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid

SKILL = Path(__file__).resolve().parents[1]
TEMPLATES = SKILL / 'assets' / 'templates'
COLLECTIONS = ('commitments', 'outcomes', 'patterns', 'runs')
EDITABLE = ('reference.md', 'tools.json', 'setup.json')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def assert_private(path):
    path = Path(path).expanduser().resolve()
    skills = SKILL.parent.resolve()
    public = skills.parent if (skills.parent / 'bundle.json').exists() else skills
    if path == public or public in path.parents:
        raise ValueError('Personal data must be outside the package and installed skills directory')
    return path


def config_path():
    return assert_private(os.environ.get('DAILY_BRIEF_CONFIG', str(Path.home() / '.daily-brief' / 'config.json')))


def data_root():
    config = json.loads(config_path().read_text(encoding='utf-8'))
    return assert_private(config['data_dir'])


@contextmanager
def lock(root):
    root.mkdir(parents=True, exist_ok=True)
    lock_dir = root / '.write-lock'
    try:
        lock_dir.mkdir()
    except FileExistsError:
        raise ValueError('Another writer or a stale lock exists; establish that no writer is active before recovery')
    try:
        yield
    finally:
        lock_dir.rmdir()


def atomic_write(path, raw, backups=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and backups:
        backups.mkdir(exist_ok=True)
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        (backups / (stamp + '-' + path.name)).write_bytes(path.read_bytes())
    fd, temporary = tempfile.mkstemp(prefix='.writing-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    if path.read_bytes() != raw:
        raise OSError('Readback verification failed')


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode('utf-8')


def validate_database(value):
    if value.get('schema_version') != 1 or type(value.get('revision')) is not int:
        raise ValueError('Invalid database schema or revision')
    for key in COLLECTIONS:
        if not isinstance(value.get(key), dict) or any(not isinstance(v, dict) for v in value[key].values()):
            raise ValueError('Invalid database collection: ' + key)


def validate_file(name, raw):
    if name.endswith('.json'):
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError('State JSON must be an object')
        if name == 'tools.json':
            if value.get('schema_version') != 1 or not isinstance(value.get('sources'), list):
                raise ValueError('Invalid tools inventory')
            ids = [x.get('id') for x in value['sources']]
            if any(not x for x in ids) or len(set(ids)) != len(ids):
                raise ValueError('Source IDs must be present and unique')
            for source in value['sources']:
                if source.get('access_status') not in ('unverified', 'verified', 'unavailable', 'manual', 'disabled'):
                    raise ValueError('Invalid access status')
        if name == 'setup.json' and value.get('status') not in ('in_progress', 'ready'):
            raise ValueError('Invalid setup status')
    elif not raw.decode('utf-8').strip():
        raise ValueError('Reference cannot be empty')


def initialize(directory):
    root = assert_private(directory)
    cfg = config_path()
    if cfg.exists() and data_root() != root:
        raise ValueError('A different data directory is already configured; migrate it deliberately before changing the pointer')
    with lock(root):
        existing = [root / name for name in (*EDITABLE, 'database.json') if (root / name).exists()]
        if existing:
            if not cfg.exists() or not all((root / name).exists() for name in (*EDITABLE, 'database.json')):
                raise ValueError('Existing or partial state found; refusing to overwrite it')
            validate_database(json.loads((root / 'database.json').read_text(encoding='utf-8')))
        else:
            for name in EDITABLE:
                atomic_write(root / name, (TEMPLATES / name).read_bytes())
            data = {'schema_version': 1, 'revision': 0, 'updated_at': now(), **{k: {} for k in COLLECTIONS}}
            atomic_write(root / 'database.json', json_bytes(data))
        for directory_name in ('reports', 'notes', 'backups'):
            (root / directory_name).mkdir(exist_ok=True)
        atomic_write(cfg, json_bytes({'schema_version': 1, 'data_dir': str(root)}))
    return {'initialized': True, 'data_dir': str(root), 'cloud_sync_verified': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('status', 'init', 'read', 'write', 'put', 'new-id'))
    parser.add_argument('--data-dir')
    parser.add_argument('--file', choices=(*EDITABLE, 'database.json'))
    parser.add_argument('--input', type=Path)
    parser.add_argument('--expected-sha')
    parser.add_argument('--collection', choices=COLLECTIONS)
    parser.add_argument('--id')
    parser.add_argument('--expected-revision', type=int)
    args = parser.parse_args(argv)
    try:
        if args.action == 'new-id':
            result = {'id': str(uuid.uuid4())}
        elif args.action == 'status':
            if not config_path().exists():
                result = {'configured': False}
            else:
                root = data_root()
                setup = json.loads((root / 'setup.json').read_text(encoding='utf-8'))
                result = {'configured': True, 'data_dir': str(root), 'setup_status': setup['status']}
        elif args.action == 'init':
            if not args.data_dir:
                parser.error('init requires --data-dir')
            result = initialize(args.data_dir)
        elif args.action == 'read':
            if not args.file:
                parser.error('read requires --file')
            raw = (data_root() / args.file).read_bytes()
            result = {'file': args.file, 'sha256': digest(raw), 'content': raw.decode('utf-8')}
        elif args.action == 'write':
            if args.file not in EDITABLE or not args.input or not args.expected_sha:
                parser.error('write requires an editable --file, --input, and --expected-sha')
            raw = args.input.read_bytes()
            validate_file(args.file, raw)
            root = data_root()
            with lock(root):
                path = root / args.file
                if digest(path.read_bytes()) != args.expected_sha:
                    raise ValueError('File changed; reread and merge before writing')
                atomic_write(path, raw, root / 'backups')
            result = {'file': args.file, 'sha256': digest(raw), 'verified': True}
        else:
            if not args.collection or not args.id or not args.input or args.expected_revision is None:
                parser.error('put requires --collection, --id, --input, and --expected-revision')
            record = json.loads(args.input.read_text(encoding='utf-8'))
            if not isinstance(record, dict):
                raise ValueError('Record must be an object')
            root = data_root()
            with lock(root):
                path = root / 'database.json'
                value = json.loads(path.read_text(encoding='utf-8'))
                validate_database(value)
                if value['revision'] != args.expected_revision:
                    raise ValueError('Revision changed; reread and merge before writing')
                value[args.collection][args.id] = record
                value['revision'] += 1
                value['updated_at'] = now()
                validate_database(value)
                atomic_write(path, json_bytes(value), root / 'backups')
            result = {'revision': value['revision'], 'verified': True}
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({'error': str(error)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
