#!/usr/bin/env python3
"""Audit only allowlisted release files. An optional private denylist stays outside the package."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
IGNORED_PARTS = {'.git', '__pycache__', '.venv'}
ALLOWED_EMAIL_DOMAINS = {'example.com', 'example.org', 'example.net', 'example.invalid'}
TEXT_SUFFIXES = {'.md', '.txt', '.json', '.py', '.css', '.js', '.html', '.yml', '.yaml'}


def paths(root):
    manifest = root / 'release-files.json'
    values = json.loads(manifest.read_text(encoding='utf-8'))
    if not isinstance(values, list) or len(set(values)) != len(values):
        raise ValueError('Invalid release manifest')
    for value in values:
        path = Path(value)
        if path.is_absolute() or '..' in path.parts or any(part.startswith('.') and part != '.gitignore' for part in path.parts):
            raise ValueError('Unsafe manifest path')
        target = root / path
        if not target.is_file() or target.is_symlink() or root.resolve() not in target.resolve().parents:
            raise ValueError('Missing, linked, or external release file: ' + value)
    return values


def text_findings(text, denied=()):
    findings = []
    patterns = {
        'local home path': r'/(?:Users|home)/[^/\s"\']+/',
        'Windows home path': r'[A-Za-z]:\\Users\\[^\\\s]+',
        'private key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
        'GitHub token': r'\b(?:gh[pousr]_[A-Za-z0-9]{24,}|github_pat_[A-Za-z0-9_]{30,})\b',
        'API token': r'\bsk-[A-Za-z0-9_-]{24,}\b',
        'cloud account directory': r'GoogleDrive-[^/\s]+@[^/\s]+'
    }
    for label, pattern in patterns.items():
        if re.search(pattern, text):
            findings.append(label)
    for email in re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', text):
        if email.rsplit('@', 1)[1].lower() not in ALLOWED_EMAIL_DOMAINS:
            findings.append('non-example email address')
    folded = text.casefold()
    for term in denied:
        if re.search(r'(?<!\w)' + re.escape(term.casefold()) + r'(?!\w)', folded):
            findings.append('private denylist match')
    return sorted(set(findings))


def audit(root=ROOT, denied=()):
    root = root.resolve()
    values = paths(root)
    expected = set(values)
    errors = []
    for path in root.rglob('*'):
        rel = path.relative_to(root)
        if any(part in IGNORED_PARTS for part in rel.parts) or path.name == '.DS_Store':
            continue
        if path.is_file() and rel.as_posix() not in expected:
            errors.append((rel.as_posix(), 'not in release allowlist'))
    for relative in values:
        path = root / relative
        raw = path.read_bytes()
        if path.suffix.lower() == '.woff2':
            # Compressed font bytes are not text. Verify the licensed upstream asset by its pinned hash.
            registry = path.parent / 'sources.json'
            entries = json.loads(registry.read_text(encoding='utf-8')) if registry.exists() else []
            entry = next((x for x in entries if x.get('file') == path.name), None)
            if not entry or hashlib.sha256(raw).hexdigest() != entry.get('sha256'):
                errors.append((relative, 'font does not match its licensed source hash'))
            continue
        # Scan text-bearing files and PDF strings; inspect images separately.
        contents = raw.decode('utf-8', errors='ignore')
        if path.suffix.lower() == '.pdf':
            if not shutil.which('pdftotext') or not shutil.which('pdfinfo'):
                errors.append((relative, 'Poppler is required for PDF privacy inspection'))
                continue
            for command in (['pdftotext', str(path), '-'], ['pdfinfo', str(path)]):
                result = subprocess.run(command, capture_output=True, text=True)
                if result.returncode:
                    errors.append((relative, 'PDF inspection failed'))
                contents += '\n' + result.stdout
        for finding in text_findings(contents, denied):
            errors.append((relative, finding))
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-denylist', type=Path, help='External JSON array of private names or identifying phrases')
    args = parser.parse_args()
    denied = []
    if args.private_denylist:
        path = args.private_denylist.resolve()
        if path == ROOT or ROOT in path.parents:
            parser.error('The private denylist must stay outside this repository')
        denied = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(denied, list) or any(not isinstance(x, str) or not x.strip() for x in denied):
            parser.error('The private denylist must be an array of nonempty strings')
    try:
        errors = audit(denied=denied)
    except (OSError, ValueError) as error:
        print('Audit failed: ' + str(error))
        return 1
    for filename, reason in errors:
        print(filename + ': ' + reason)
    if errors:
        print('Release blocked. No matching private text was printed.')
        return 1
    print('Release audit passed. Inspect example images separately before publishing.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
