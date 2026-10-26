# backup-claim-audit

An offline, standard-library-only static checker for Python projects. Version 0.1.0.
MIT licensed. It compares documented backup behavior with AST evidence without
executing project code. It never reads .env contents.

## Usage

```sh
python3 -m pip install .
backup-claim-audit /path/to/project
python3 -m backup_claim_audit /path/to/project --json
python3 -m backup_claim_audit . --verbose --ignore 'vendor/*' --fail-on HIGH
python3 -m backup_claim_audit --version
python3 -m unittest discover -s tests -v
python3 -m build
```

Exit codes: 0 means no findings at the selected threshold; 2 means findings;
1 means a usage, unreadable-project, decoding, or source syntax error.
The default threshold includes HIGH and MEDIUM. `--fail-on HIGH` keeps MEDIUM
findings visible with exit 0; the verdict still describes all findings.
`--fail-on MEDIUM` includes both severities. Repeat `--ignore` for relative-path
globs; matching directories are pruned. `--json` emits path, verdict, claims,
evidence, and findings. `--verbose` adds per-sentence claims and per-file evidence
(in JSON, claim_sentences is an additional field).

## Scope and limitations

Claim input is root README.md and Markdown beneath docs/. Fenced code is ignored;
inline code counts. Normalization lowercases text, expands n't to a space plus
not, replaces hyphens with spaces, and collapses whitespace. Sentences end at
periods, exclamation marks, question marks, or newlines. Exact phrases match
longest first across both families, with at most one family per sentence.
Residual no/not/never/without suppresses a positive match. Bare nouns do not count.
One claim record and at most one finding are emitted per family.

Production includes .py files except tests/, fixtures/, docs/, examples/ and
files named test_*.py or *_test.py. Test evidence is reported separately.
Symlink files and directories are skipped. Build, distribution, environment,
Git, cache, and egg-info directories are skipped.

Evidence includes shutil.copy/copy2/copyfile/copytree with a marker argument,
write-mode open/io.open with a marker path, and backup-named calls.
A marker is a string containing .bak, backup, or .orig, case-insensitively;
addition with a literal marker side and f-string literal marker parts count.
Suffix constructions via with_suffix qualify when used in a copy/open/write
statement or assigned to a simple name used by such an operation in the file.
For write_text/write_bytes, this implementation chooses the **statement-local**
rule: a marker construction anywhere in the same AST statement qualifies.
Assigned suffix names also qualify there. Arbitrary Path assignments are not
followed. Suffix name following is file-wide and flow-insensitive.
Backup-named calls are an over-approximation: they need not actually retain data.
Only recursive calls inside a same-named function/class definition are excluded.
This checker does not prove ordering, runtime reachability, successful execution,
copy completeness, or retention of original bytes.

Bare imports, unmarked plain copies, read-mode opens, temporary files,
os.replace/os.rename, comments, docstrings, and marker strings in print/log
calls are not evidence on their own. Imported aliases and dynamic path values
are not resolved. Syntax errors cause exit 1 rather than silent omission.

The positive family requires production evidence. Missing source produces HIGH
with evidence ["no-source"]. Test evidence with production present produces
MEDIUM instead. The negative family conflicts with production evidence (HIGH)
or test evidence alone (MEDIUM); absent source satisfies that family.
The rule identifiers and recognized phrases are listed below in fenced text
so this README has no audit claim of its own.

```text
documented-backup-claim-false HIGH
documented-backup-claim-false-test-only MEDIUM
documented-no-backup-claim-false HIGH
documented-no-backup-claim-false-test-only MEDIUM

BACKUP:
backs up the original file before
backs up original files before
backs up the file before overwriting
backs up files before overwriting
original files are backed up before
original file is backed up before
backup is created before overwriting
backups are created before overwriting
a backup is created before
creates a backup before overwriting
creates backups before overwriting
backs up the original file
backs up original files
backs up your files
backs up the file
original files are backed up
original file is backed up
a backup is created
backups are created
creates a backup
creates backups
makes a backup
makes backups
keeps a backup
saves a backup

NOBACKUP:
does not create a backup
does not create backups
does not back up
never creates a backup
never creates backups
never backs up
no backup is created
no backups are created
backup is not created
backups are not created
without creating a backup
without creating backups
does not keep a backup
original files are not backed up
original file is not backed up
```
