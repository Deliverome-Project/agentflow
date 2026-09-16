"""Security boundaries: late wheels, lookup failures, and leaked release data."""
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


age = load('check_dependency_age')
release = load('check_release_contents')
NOW = datetime(2026, 9, 16, tzinfo=UTC)


def package():
    return {'name': 'example', 'version': '1', 'source': {'registry': 'https://pypi.org/simple'},
            'wheels': [{'hash': 'sha256:old'}, {'hash': 'sha256:late'}]}


def metadata(late_days=7, yanked=False):
    return {'urls': [{'digests': {'sha256': digest}, 'yanked': yanked,
                      'upload_time_iso_8601': (NOW - timedelta(days=days)).isoformat()}
                     for digest, days in [('old', 30), ('late', late_days)]]}


def test_all_artifacts_must_age_including_later_wheel():
    age.check_package(package(), NOW, lambda _: metadata())
    with pytest.raises(ValueError, match='seven days'):
        age.check_package(package(), NOW, lambda _: metadata(6.99))


def test_missing_hash_yanked_and_network_failure_block():
    with pytest.raises(ValueError):
        age.check_package(package(), NOW, lambda _: {'urls': []})
    with pytest.raises(ValueError, match='yanked'):
        age.check_package(package(), NOW, lambda _: metadata(yanked=True))
    def offline(_):
        raise TimeoutError()
    with pytest.raises(TimeoutError):
        age.check_package(package(), NOW, offline)
    bad = package()
    bad['source'] = {'git': 'https://example.org/repo'}
    with pytest.raises(ValueError, match='source'):
        age.check_package(bad, NOW)


def test_release_guards():
    notices = [(name, b'notice') for name in release.REQUIRED]
    release.inspect_members(notices)
    for filename in ['sample.fcs', 'events.parquet', '.env', '../escape']:
        with pytest.raises(ValueError):
            release.inspect_members(notices + [(filename, b'')])
    with pytest.raises(ValueError, match='Missing notice'):
        release.inspect_members(notices[:-1])
    private_url = ('https://www.notion.' + 'so/' + 'a' * 32).encode()
    with pytest.raises(ValueError, match='Private reference'):
        release.inspect_members(notices + [('README.md', private_url)])
