#!/usr/bin/env python3
"""Create a ZIP from the audited release allowlist; never archive the whole working directory."""
import argparse
import json
from pathlib import Path
import zipfile
from audit_release import ROOT, audit, paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--private-denylist', type=Path)
    args = parser.parse_args()
    out = args.out.expanduser().resolve()
    if ROOT == out or ROOT in out.parents:
        parser.error('Archive destination must be outside this repository')
    if out.exists():
        parser.error('Archive exists; choose a new release filename')
    denied = []
    if args.private_denylist:
        deny_path = args.private_denylist.resolve()
        if ROOT == deny_path or ROOT in deny_path.parents:
            parser.error('Private denylist must stay outside the repository')
        denied = json.loads(deny_path.read_text(encoding='utf-8'))
    errors = audit(denied=denied)
    if errors:
        for name, reason in errors:
            print(name + ': ' + reason)
        return 1
    members = paths(ROOT)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in members:
            archive.write(ROOT / name, 'daily-brief-skills/' + name)
    with zipfile.ZipFile(out) as archive:
        if archive.testzip() is not None or len(archive.namelist()) != len(members):
            raise ValueError('Archive verification failed')
    print('Created verified release ZIP: ' + out.name)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
