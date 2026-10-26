"""Read-only AST and Markdown analysis; project code is never executed."""
import ast
import fnmatch
import re
from pathlib import Path

BACKUP = ['backs up the original file before', 'backs up original files before', 'backs up the file before overwriting', 'backs up files before overwriting', 'original files are backed up before', 'original file is backed up before', 'backup is created before overwriting', 'backups are created before overwriting', 'a backup is created before', 'creates a backup before overwriting', 'creates backups before overwriting', 'backs up the original file', 'backs up original files', 'backs up your files', 'backs up the file', 'original files are backed up', 'original file is backed up', 'a backup is created', 'backups are created', 'creates a backup', 'creates backups', 'makes a backup', 'makes backups', 'keeps a backup', 'saves a backup']
NOBACKUP = ['does not create a backup', 'does not create backups', 'does not back up', 'never creates a backup', 'never creates backups', 'never backs up', 'no backup is created', 'no backups are created', 'backup is not created', 'backups are not created', 'without creating a backup', 'without creating backups', 'does not keep a backup', 'original files are not backed up', 'original file is not backed up']


def normalize(text):
    return re.sub(r"\s+", " ", text.lower().replace("n't", " not").replace("-", " ")).strip()


def claim_sentences(text):
    prose = []
    fence = None
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if match:
            token = match.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is None:
            prose.append(line)
    phrases = sorted([(p, "backup") for p in BACKUP] + [(p, "nobackup") for p in NOBACKUP], key=lambda x: -len(x[0]))
    for sentence in re.split(r"[.!?\n]+", "\n".join(prose)):
        normalized = normalize(sentence)
        for phrase, family in phrases:
            match = re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", normalized)
            if match:
                remainder = normalized[:match.start()] + normalized[match.end():]
                if family == "backup" and re.search(r"\b(no|not|never|without)\b", remainder):
                    break
                yield family, phrase, sentence.strip()
                break


def marker(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return any(s in node.value.lower() for s in (".bak", "backup", ".orig"))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return marker(node.left) or marker(node.right)
    if isinstance(node, ast.JoinedStr):
        return any(marker(x) for x in node.values)
    return False


def call_name(node):
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ""


def source_evidence(text, filename="<source>"):
    tree = ast.parse(text, filename=filename)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    suffix_names = set()
    def suffix(node):
        return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "with_suffix" and bool(node.args) and marker(node.args[0])
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None and suffix(node.value):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            suffix_names.update(t.id for t in targets if isinstance(t, ast.Name))
    def destination(node):
        return marker(node) or suffix(node) or (isinstance(node, ast.Name) and node.id in suffix_names)
    items = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = call_name(node.func)
        args = list(node.args) + [k.value for k in node.keywords]
        reason = None
        if "backup" in name.lower():
            ancestor = parents.get(node)
            recursive = False
            while ancestor is not None:
                if isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and ancestor.name == name:
                    recursive = True
                    break
                ancestor = parents.get(ancestor)
            if not recursive:
                reason = "backup-named call"
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "shutil" and name in ("copy", "copy2", "copyfile", "copytree"):
            if any(destination(a) for a in args):
                reason = "copy with backup destination marker"
        is_open = isinstance(node.func, ast.Name) and name == "open" or isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "io" and name == "open"
        if is_open:
            path = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "file"), None)
            mode = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "mode"), None)
            if isinstance(mode, ast.Constant) and isinstance(mode.value, str) and any(c in mode.value for c in "wax+") and destination(path):
                reason = "write-mode open with backup marker"
        if isinstance(node.func, ast.Attribute) and name in ("write_text", "write_bytes"):
            statement = node
            while statement in parents and not isinstance(statement, ast.stmt):
                statement = parents[statement]
            if any(marker(n) or suffix(n) or isinstance(n, ast.Name) and n.id in suffix_names for n in ast.walk(statement)):
                reason = "statement-local backup write"
        if reason:
            items.append("line {}: {}".format(node.lineno, reason))
    return sorted(set(items))


def audit(path, ignore=()):
    root = Path(path).resolve()
    if not root.is_dir():
        raise ValueError("project path must be a readable directory")
    claims = {}
    sentences = []
    evidence = []
    production = 0
    # Explicit recursion avoids following directory symlinks and never opens .env.
    def walk(directory):
        for entry in sorted(directory.iterdir()):
            if entry.is_symlink():
                continue
            rel = entry.relative_to(root).as_posix()
            if any(fnmatch.fnmatchcase(rel, pattern) for pattern in ignore):
                continue
            if entry.is_dir():
                if entry.name not in (".git", ".venv", "venv", "__pycache__", "build", "dist") and not entry.name.endswith(".egg-info"):
                    yield from walk(entry)
            elif entry.is_file():
                yield entry, rel
    for entry, rel in walk(root):
        parts = Path(rel).parts
        if rel == "README.md" or parts[0] == "docs" and entry.suffix == ".md":
            for family, phrase, sentence in claim_sentences(entry.read_text(encoding="utf-8")):
                claim = claims.setdefault(family, {"family": family, "phrases": [], "files": []})
                if phrase not in claim["phrases"]:
                    claim["phrases"].append(phrase)
                if rel not in claim["files"]:
                    claim["files"].append(rel)
                sentences.append({"file": rel, "family": family, "sentence": sentence})
        if entry.suffix != ".py":
            continue
        test_only = any(p in ("tests", "fixtures") for p in parts[:-1]) or entry.name.startswith("test_") or entry.name.endswith("_test.py")
        excluded = any(p in ("docs", "examples") for p in parts[:-1])
        if excluded:
            continue
        if not test_only:
            production += 1
        items = source_evidence(entry.read_text(encoding="utf-8"), rel)
        if items:
            evidence.append({"file": rel, "items": items, "test_only": test_only})
    prod = [e["file"] for e in evidence if not e["test_only"]]
    tests = [e["file"] for e in evidence if e["test_only"]]
    findings = []
    for family in claims:
        severity = None
        details = []
        if family == "backup" and not prod:
            severity = "MEDIUM" if tests and production else "HIGH"
            details = tests if severity == "MEDIUM" else ["no-source"] if not production else []
        elif family == "nobackup" and (prod or tests):
            severity = "HIGH" if prod else "MEDIUM"
            details = prod or tests
        if severity:
            rule = "documented-{}-claim-false".format("backup" if family == "backup" else "no-backup")
            if severity == "MEDIUM":
                rule += "-test-only"
            findings.append({"rule": rule, "severity": severity, "family": family, "evidence": details})
    return {"path": str(root), "verdict": "fail" if findings else "pass", "claims": list(claims.values()), "evidence": evidence, "findings": findings}, sentences
