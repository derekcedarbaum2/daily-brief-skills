#!/usr/bin/env python3
"""Install both skill folders without overwriting an existing installation."""
import argparse
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('daily-brief', 'daily-brief-setup')


def install(destination):
    destination = Path(destination).expanduser().resolve()
    if destination == ROOT or ROOT in destination.parents:
        raise ValueError('Choose the host runtime skills directory outside this repository')
    destination.mkdir(parents=True, exist_ok=True)
    collisions = [name for name in NAMES if (destination / name).exists() or (destination / name).is_symlink()]
    if collisions:
        raise ValueError('Existing skills would be overwritten: ' + ', '.join(collisions))
    for name in NAMES:
        source = ROOT / 'skills' / name
        if not (source / 'SKILL.md').is_file() or any(p.is_symlink() for p in source.rglob('*')):
            raise ValueError('Invalid or linked source skill: ' + name)
    installed = []
    try:
        with tempfile.TemporaryDirectory(prefix='.daily-brief-install-', dir=destination) as staging:
            for name in NAMES:
                shutil.copytree(ROOT / 'skills' / name, Path(staging) / name,
                                ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store'))
            for name in NAMES:
                Path(staging, name).rename(destination / name)
                installed.append(destination / name)
    except Exception:
        for path in installed:
            shutil.rmtree(path)
        raise
    return installed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skills-dir', required=True)
    args = parser.parse_args()
    try:
        paths = install(args.skills_dir)
        print('Installed both skills. Invoke daily-brief-setup to start the interview.')
        for path in paths:
            print(path)
        return 0
    except (OSError, ValueError) as error:
        print('Installation failed: ' + str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
