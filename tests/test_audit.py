import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from backup_claim_audit.audit import BACKUP, NOBACKUP, audit, claim_sentences, source_evidence
from backup_claim_audit.cli import main

FIXTURES = ROOT / 'tests' / 'fixtures'


class PhraseTests(unittest.TestCase):
    pass


def phrase_test(phrase, family):
    def test(self):
        result = list(claim_sentences(phrase.upper() + '.'))
        self.assertEqual([(x[0], x[1]) for x in result], [(family, phrase)])
    return test


for index, phrase in enumerate(BACKUP + NOBACKUP):
    setattr(PhraseTests, 'test_phrase_{:02d}'.format(index), phrase_test(phrase, 'backup' if phrase in BACKUP else 'nobackup'))


class FixtureTests(unittest.TestCase):
    pass


def fixture_test(name, rule, severity):
    def test(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main([str(FIXTURES / name), '--json'])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 2 if rule else 0)
        self.assertEqual(result['verdict'], 'fail' if rule else 'pass')
        self.assertEqual(set(result), {'path', 'verdict', 'claims', 'evidence', 'findings'})
        self.assertEqual([(f['rule'], f['severity']) for f in result['findings']], [(rule, severity)] if rule else [])
        if name == 'nosource/backup':
            self.assertEqual(result['findings'][0]['evidence'], ['no-source'])
        if name == 'negation':
            self.assertEqual([c['family'] for c in result['claims']], ['nobackup'])
        if name in ('fenced-code', 'noclaim'):
            self.assertEqual(result['claims'], [])
    return test


for name in ['good/backup', 'good/nobackup', 'bad/backup', 'bad/nobackup', 'testonly/backup', 'testonly/nobackup', 'noclaim', 'nosource/backup', 'nosource/nobackup', 'negation', 'inline-code', 'fenced-code', 'fstring', 'plaincopy', 'backupfn', 'printonly']:
    failing = name in ['bad/backup', 'bad/nobackup', 'testonly/backup', 'testonly/nobackup', 'nosource/backup', 'inline-code', 'plaincopy', 'printonly']
    family = 'no-backup' if name.endswith('/nobackup') else 'backup'
    medium = name.startswith('testonly/')
    rule = 'documented-{}-claim-false{}'.format(family, '-test-only' if medium else '') if failing else None
    setattr(FixtureTests, 'test_' + name.replace('/', '_').replace('-', '_'), fixture_test(name, rule, 'MEDIUM' if medium else 'HIGH'))


class ExtraTests(unittest.TestCase):
    def test_threshold(self):
        for family in ('backup', 'nobackup'):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(FIXTURES / 'testonly' / family), '--fail-on', 'HIGH']), 0)

    def test_env_not_read(self):
        original = Path.open
        def guarded(path, *args, **kwargs):
            self.assertNotEqual(path.name, '.env')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', guarded):
            audit(FIXTURES / 'bad/backup')

    def test_marked_operations(self):
        for source in ['shutil.copy2(src, "backups/")', 'shutil.copyfile(src, src + ".orig")', 'shutil.copytree(src, f"{src}.bak")', 'open("file.bak", "w")', 'io.open(file="backup", mode="a")', 'Path("backup").write_text(data)', 'Path(f"{src}.bak").write_bytes(data)', 'shutil.copy(src, path.with_suffix(".bak"))', 'b = path.with_suffix(".bak")\nopen(b, "x")', 'b = path.with_suffix(".bak")\nb.write_text(data)', 'self.backup_file(path)']:
            with self.subTest(source=source):
                self.assertTrue(source_evidence(source))

    def test_non_evidence(self):
        for source in ['import shutil\nimport pathlib', 'shutil.copy(src, dest)', 'open("backup", "r")', 'tempfile.mkstemp()', 'os.replace(src, dest)', 'os.rename(src, dest)', 'print(".bak")', '"shutil.copy(src, src + .bak)"', '# make_backup()', 'p = Path("backup")\np.write_text(data)', 'p.write_bytes(data)', 'def backup():\n    backup()']:
            with self.subTest(source=source):
                self.assertEqual(source_evidence(source), [])

    def test_normalization_and_negation(self):
        self.assertEqual(list(claim_sentences("It doesn't create a backup."))[0][0], 'nobackup')
        self.assertEqual(list(claim_sentences('It creates-a-backup.'))[0][0], 'backup')
        self.assertEqual(list(claim_sentences('It never makes a backup.')), [])
        self.assertEqual(list(claim_sentences('backup backups .bak')), [])
        self.assertEqual(list(claim_sentences('~~~md\ncreates a backup\n~~~')), [])

    def test_docs_ignore_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'docs').mkdir()
            (root / 'docs' / 'guide.md').write_text('Creates a backup.')
            (root / 'app.py').write_text('open(path, "w")')
            (root / 'linked.py').symlink_to(FIXTURES / 'good/backup/app.py')
            (root / 'README.md').symlink_to(FIXTURES / 'good/nobackup/README.md')
            result, _ = audit(root)
            self.assertEqual(len(result['findings']), 1)
            self.assertEqual(result['claims'][0]['files'], ['docs/guide.md'])
            self.assertEqual(audit(root, ['docs/*'])[0]['claims'], [])

    def test_entry_points(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'))
        result = subprocess.run(['python3', '-m', 'backup_claim_audit', '--version'], env=env, capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, '0.1.0'))

    def test_usage_errors(self):
        for args in [[str(ROOT / 'nonexistent')], ['--fail-on', 'LOW']]:
            with contextlib.redirect_stderr(io.StringIO()):
                if args[0].startswith('--'):
                    with self.assertRaises(SystemExit) as raised:
                        main(args)
                    self.assertEqual(raised.exception.code, 1)
                else:
                    self.assertEqual(main(args), 1)

    def test_verbose(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            main([str(FIXTURES / 'good/backup'), '--verbose'])
        self.assertIn('claim README.md', output.getvalue())
        self.assertIn('evidence app.py', output.getvalue())

    def test_self_audit(self):
        result, _ = audit(ROOT)
        self.assertEqual(result['claims'], [])
        self.assertEqual(result['verdict'], 'pass')

    def test_local_called_definition(self):
        self.assertTrue(source_evidence('def backup():\n    backup()\nbackup()'))

    def test_both_families(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'README.md').write_text('Creates a backup.\nNo backup is created.')
            (root / 'app.py').write_text('open(path, "w")')
            result, _ = audit(root)
            self.assertEqual(len(result['claims']), 2)
            self.assertEqual(len(result['findings']), 1)


if __name__ == '__main__':
    unittest.main()
