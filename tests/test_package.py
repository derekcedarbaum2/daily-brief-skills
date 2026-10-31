import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


state = load('state', 'skills/daily-brief/scripts/state.py')
renderer = load('renderer', 'skills/daily-brief/scripts/render_briefing.py')
installer = load('installer', 'scripts/install.py')
audit = load('audit', 'scripts/audit_release.py')


class PrivateStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {'DAILY_BRIEF_CONFIG': str(self.base / 'config.json')})
        self.environment.start()
        self.root = self.base / 'private-data'
        state.initialize(self.root)

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def call(self, *args):
        with contextlib.redirect_stdout(io.StringIO()):
            return state.main(list(args))

    def test_initialize_twice_preserves_answers(self):
        reference = self.root / 'reference.md'
        reference.write_text('Confirmed custom shift pattern.')
        state.initialize(self.root)
        self.assertEqual(reference.read_text(), 'Confirmed custom shift pattern.')

    def test_reference_write_and_stale_rejection_preserve_backup(self):
        reference = self.root / 'reference.md'
        old = reference.read_bytes()
        original_hash = hashlib.sha256(old).hexdigest()
        draft = self.base / 'draft.md'
        draft.write_text('Shift worker. No dependent-care obligations.')
        self.assertEqual(self.call('write', '--file', 'reference.md', '--input', str(draft), '--expected-sha', original_hash), 0)
        current = reference.read_bytes()
        self.assertIn(old, [p.read_bytes() for p in (self.root / 'backups').iterdir()])
        draft.write_text('Stale answer must not replace the latest reference.')
        self.assertEqual(self.call('write', '--file', 'reference.md', '--input', str(draft), '--expected-sha', original_hash), 1)
        self.assertEqual(reference.read_bytes(), current)

    def test_run_revision_rejects_stale_writer(self):
        record = self.base / 'run.json'
        record.write_text(json.dumps({'status': 'draft', 'meeting_agendas': {'event:2030-01-02': {'purpose': 'Resolve a decision'}}}))
        args = ['put', '--collection', 'runs', '--id', 'run-a', '--input', str(record), '--expected-revision', '0']
        self.assertEqual(self.call(*args), 0)
        self.assertEqual(self.call(*args), 1)
        data = json.loads((self.root / 'database.json').read_text())
        self.assertEqual(data['revision'], 1)
        self.assertIn('event:2030-01-02', data['runs']['run-a']['meeting_agendas'])

    def test_lock_stops_second_writer(self):
        with state.lock(self.root):
            with self.assertRaises(ValueError):
                with state.lock(self.root):
                    pass
        self.assertFalse((self.root / '.write-lock').exists())

    def test_private_path_inside_package_is_rejected(self):
        with self.assertRaises(ValueError):
            state.initialize(ROOT / 'private-data')
        with self.assertRaises(ValueError):
            state.initialize(ROOT / 'skills' / 'daily-brief' / 'personal')

    def test_changing_storage_pointer_cannot_abandon_existing_answers(self):
        with self.assertRaises(ValueError):
            state.initialize(self.base / 'different-data')
        self.assertEqual(state.data_root(), self.root.resolve())

    def test_manual_inventory_round_trip(self):
        inventory = {'schema_version': 1, 'sources': [{'id': 'employer-tasks', 'product': 'Jira', 'access_status': 'manual', 'permitted_scopes': [], 'manual_fallback': 'User-approved meeting rundown'}]}
        draft = self.base / 'inventory.json'
        draft.write_text(json.dumps(inventory))
        current = hashlib.sha256((self.root / 'tools.json').read_bytes()).hexdigest()
        self.assertEqual(self.call('write', '--file', 'tools.json', '--input', str(draft), '--expected-sha', current), 0)
        self.assertEqual(json.loads((self.root / 'tools.json').read_text())['sources'][0]['access_status'], 'manual')


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads((ROOT / 'examples/sample-day.json').read_text())

    def test_fictional_example_is_valid(self):
        renderer.validate(self.spec)

    def test_empty_template_cannot_render_as_a_plan(self):
        blank = json.loads((ROOT / 'skills/daily-brief/assets/templates/daily-brief.json').read_text())
        with self.assertRaises(renderer.SpecError):
            renderer.validate(blank)

    def test_bad_timezone_is_rejected(self):
        self.spec['timezone'] = 'Not/A_Timezone'
        with self.assertRaises(KeyError):
            renderer.validate(self.spec)

    def test_invalid_midnight_times_are_rejected(self):
        for bad in ('24:30', '25:00', '-1:00'):
            with self.subTest(bad=bad), self.assertRaises(renderer.SpecError):
                renderer.mins(bad)
        self.spec['agenda'][0]['start'] = '24:00'
        with self.assertRaises(renderer.SpecError):
            renderer.validate(self.spec)

    def test_html_does_not_fetch_remote_fonts_or_load_injected_markup(self):
        self.spec['agenda'][0]['detail'] = '<img src=x onerror="alert(1)">'
        prep = renderer.dt.datetime.fromisoformat(self.spec['prepared_at'])
        html = renderer.build_html(self.spec, prep)
        self.assertNotIn('<img src=x', html)
        self.assertIn('&lt;img', html)
        self.assertNotIn('fonts.googleapis.com', html)
        self.assertIn('data:font/woff2;base64,', html)
        self.assertNotIn('What matters most', html)

    def test_source_record_keeps_only_spec_filename(self):
        prep = renderer.dt.datetime.fromisoformat(self.spec['prepared_at'])
        record = renderer.record_md(self.spec, prep, 'sample', Path(tempfile.gettempdir()) / 'some-private-folder' / 'sample.json')
        self.assertIn('`sample.json`', record)
        self.assertNotIn('some-private-folder', record)

    def test_named_output_cannot_escape_directory(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stderr(io.StringIO()):
            result = renderer.main([str(ROOT / 'examples/sample-day.json'), '--out-dir', temp, '--name', '../outside', '--html-only'])
        self.assertEqual(result, 1)


class InstallAndReleaseTests(unittest.TestCase):
    def test_install_preserves_siblings_and_refuses_existing_files(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / 'skills'
            installed = installer.install(dest)
            self.assertEqual(len(installed), 2)
            marker = dest / 'daily-brief' / 'keep.txt'
            marker.write_text('existing local change')
            with self.assertRaises(ValueError):
                installer.install(dest)
            self.assertEqual(marker.read_text(), 'existing local change')
            self.assertTrue((dest / 'daily-brief-setup/SKILL.md').is_file())

    def test_privacy_rules_catch_home_email_token_and_private_terms(self):
        cases = [('/' + 'Users' + '/' + 'somebody' + '/file', 'local home path'),
                 ('person' + '@' + 'private.example', 'non-example email address'),
                 ('ghp_' + 'a' * 36, 'GitHub token')]
        for text, kind in cases:
            self.assertIn(kind, audit.text_findings(text))
        self.assertIn('private denylist match', audit.text_findings('an identifying phrase', ['identifying phrase']))
        self.assertFalse(audit.text_findings('contributors@example.invalid'))

    def test_unknown_file_and_symlink_block_release(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'release-files.json').write_text(json.dumps(['release-files.json', 'README.md']))
            (root / 'README.md').write_text('Generic content')
            self.assertEqual(audit.audit(root), [])
            (root / 'private-notes.txt').write_text('Must not ship')
            self.assertTrue(audit.audit(root))
            (root / 'private-notes.txt').unlink()
            (root / 'README.md').unlink()
            (root / 'README.md').symlink_to(root / 'release-files.json')
            with self.assertRaises(ValueError):
                audit.audit(root)

    def test_font_hashes_match_licensed_sources(self):
        fonts = ROOT / 'skills/daily-brief/assets/fonts'
        for entry in json.loads((fonts / 'sources.json').read_text()):
            self.assertEqual(hashlib.sha256((fonts / entry['file']).read_bytes()).hexdigest(), entry['sha256'])
        self.assertIn('SIL OPEN FONT LICENSE', (fonts / 'SourceSerif4-OFL.txt').read_text())
        self.assertIn('SIL OPEN FONT LICENSE', (fonts / 'SourceSans3-OFL.txt').read_text())


if __name__ == '__main__':
    unittest.main()
