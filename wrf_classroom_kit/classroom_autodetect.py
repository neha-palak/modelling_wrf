"""Portable, dependency-free discovery and preparation for assigned WRF groups.

Only completed reducer outputs are accepted. Original TARs, NetCDF inputs,
and source JSON are never edited. A separate, explicitly scoped manifest
describes the selected group(s); exact source metadata is kept as provenance.
Archive extraction streams selected regular files and never uses extractall.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile

WORKFLOW_VERSION = 2
CASES = ('01_CTRL', '02_CTRL_NOISE', '03_CLEAN')
PRIMARY = set(('T2 Q2 PSFC U10 V10 TSK PBLH HFX LH SWDOWN GLW '
               'RAINC RAINNC GRDFLX PM2_5_DRY PM10 TOT_DUST BC1 so2 OC1').split())
DISCOVERY_WARNINGS = []
_SKIP = {'demo_data', 'examples', 'node_modules', '__pycache__', 'site-packages',
         'runtime', 'results', 'RESULTS', 'plots', 'provenance', 'env-v1', 'miniforge3',
         'anaconda3', 'miniconda3', 'venv', '.venv', '.git', '.cache', 'test_deps',
         'drive', 'gdrive'}
_JSON_LIMIT = 32 * 1024 * 1024


class PreparationError(ValueError):
    """A student input needs correction; never silently substitute other data."""


def _need(condition, message):
    if not condition:
        raise PreparationError(message)


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _stable(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _json_bytes(path):
    _need(path.is_file(), 'Missing metadata: ' + str(path))
    _need(path.stat().st_size <= _JSON_LIMIT, 'Metadata file is unexpectedly large: ' + str(path))
    data = path.read_bytes()
    return data, json.loads(data.decode('utf-8'))


def _relative(name):
    _need(isinstance(name, str) and bool(name) and '\\' not in name,
          'Invalid archive/manifest path: ' + repr(name))
    path = PurePosixPath(name)
    _need(not path.is_absolute() and '..' not in path.parts
          and all(':' not in part for part in path.parts),
          'Unsafe archive/manifest path: ' + name)
    _need(bool(path.parts), 'Empty archive path')
    return path.as_posix()


def _within(root, relative):
    path = root.joinpath(*PurePosixPath(_relative(relative)).parts)
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise PreparationError('A path or symlink leaves the dataset: ' + str(path)) from exc
    return path


def _validate_source(manifest, plan):
    _need(isinstance(manifest, dict) and isinstance(plan, dict), 'Invalid source JSON structure')
    cfg = plan.get('config', {})
    entries = manifest.get('files', {})
    _need(isinstance(entries, dict) and entries, 'Source manifest has no file inventory')
    _need(manifest.get('complete') is True,
          'This source conversion is not marked complete. Ask for the completed group archive.')
    signature = plan.get('config_hash')
    _need(isinstance(signature, str) and re.fullmatch(r'[0-9a-f]{64}', signature)
          and manifest.get('config_hash') == signature, 'Source plan and manifest hashes differ')
    _need(cfg.get('vertical') in ('full', 'surface'), 'Source vertical mode is missing or invalid')
    fields = cfg.get('primary_variables', [])
    _need(len(fields) == 20 and set(fields) == PRIMARY,
          'The source does not contain the corrected classroom selection of 20 fields')
    times = cfg.get('selected_times', [])
    _need(isinstance(times, list) and bool(times), 'Source plan has no selected times')
    parsed = [datetime.strptime(t, '%Y-%m-%d_%H:%M:%S') for t in times]
    _need(cfg.get('interval_hours') == 3 and all((b-a).total_seconds() == 10800
          for a, b in zip(parsed, parsed[1:])), 'Source times are not an exact three-hour sequence')
    cases = cfg.get('cases', [])
    _need(bool(cases) and len(cases) == len(set(cases)) and set(cases).issubset(CASES),
          'Unexpected experiment names in the source plan')
    _need(manifest.get('planned_files') == plan.get('planned_files_total')
          == len(entries) == len(times) * len(cases), 'Source planned and recorded counts differ')
    _need(plan.get('planned_files_per_case') == len(times), 'Source per-group count differs')
    grouped = {case: {} for case in cases}
    for relative, info in entries.items():
        rel = _relative(relative)
        _need(rel == relative and isinstance(info, dict), 'Noncanonical source file inventory')
        case = info.get('case')
        _need(case in grouped and PurePosixPath(rel).parts[0] == case and rel.endswith('.nc'),
              'Source file is outside its declared experiment: ' + rel)
        _need(isinstance(info.get('bytes'), int) and info['bytes'] > 0,
              'Missing/invalid recorded file size: ' + rel)
        grouped[case][rel] = info
    for case, files in grouped.items():
        _need(len(files) == len(times) and sorted(x['time'] for x in files.values()) == sorted(times),
              case + ': source timestamp inventory is incomplete')
    return cfg, grouped


def _archive_index(handle):
    index = {}
    for member in handle.getmembers():
        name = _relative(member.name)
        _need(member.isdir() or member.isfile(),
              'Archive links/devices are unsupported: ' + member.name)
        if member.isdir():
            continue
        _need(name not in index, 'Archive has duplicate member: ' + name)
        index[name] = member
    return index


def _archive_metadata(path):
    before = path.stat()
    with tarfile.open(path, 'r:*') as handle:
        index = _archive_index(handle)
        raw = {}
        for name in ('manifest.json', 'plan.json'):
            _need(name in index, 'Archive lacks ' + name + ': ' + str(path))
            _need(index[name].size <= _JSON_LIMIT, 'Archive metadata is unexpectedly large')
            stream = handle.extractfile(index[name])
            _need(stream is not None, 'Cannot read ' + name)
            with stream:
                raw[name] = stream.read(_JSON_LIMIT + 1)
            _need(len(raw[name]) == index[name].size, 'Incomplete archive metadata: ' + name)
    after = path.stat()
    _need((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
          'Archive changed while being inspected; wait for the upload/download to finish')
    manifest, plan = json.loads(raw['manifest.json']), json.loads(raw['plan.json'])
    cfg, grouped = _validate_source(manifest, plan)
    available = {case: {rel: member.size for rel in files if (member := index.get(rel)) is not None}
                 for case, files in grouped.items()}
    return {'kind': 'archive', 'path': path, 'manifest': manifest, 'plan': plan, 'cfg': cfg,
            'manifest_bytes': raw['manifest.json'], 'plan_bytes': raw['plan.json'],
            'grouped': grouped, 'available': available, 'prepared': False,
            'stat': (after.st_size, after.st_mtime_ns)}


def _folder_metadata(root):
    active_bytes, active = _json_bytes(root / 'manifest.json')
    scope = active.get('classroom_scope', {})
    if scope.get('kind') == 'selected_cases':
        original_bytes, manifest = _json_bytes(root / 'provenance' / 'source_manifest.json')
        plan_bytes, plan = _json_bytes(root / 'provenance' / 'source_plan.json')
        _need(_digest(original_bytes) == scope.get('parent_manifest_sha256'),
              'Prepared data provenance differs from its recorded parent manifest')
        _need(active.get('config_hash') == manifest.get('config_hash'),
              'Prepared manifest has a different source configuration')
        allowed = set(scope.get('selected_cases', []))
        prepared = True
    else:
        original_bytes, manifest = active_bytes, active
        plan_bytes, plan = _json_bytes(root / 'plan.json')
        allowed = set(CASES)
        prepared = False
    cfg, grouped = _validate_source(manifest, plan)
    available = {}
    for case, files in grouped.items():
        if case not in allowed:
            continue
        found = {}
        for rel in files:
            path = _within(root, rel)
            if path.is_file():
                found[rel] = path.stat().st_size
        available[case] = found
    return {'kind': 'dataset', 'path': root, 'manifest': manifest, 'plan': plan, 'cfg': cfg,
            'manifest_bytes': original_bytes, 'plan_bytes': plan_bytes, 'grouped': grouped,
            'available': available, 'prepared': prepared,
            'active_manifest_digest': _digest(active_bytes)}


def _load_source(path, kind):
    return _archive_metadata(path) if kind == 'archive' else _folder_metadata(path)


def _selection_digest(source, case):
    selected = source['grouped'][case]
    return _digest(_stable([(rel, x['time'], x['bytes'], x.get('sha256_payload'))
                            for rel, x in sorted(selected.items())]))


def _candidates(source):
    results = []
    for case, found in source['available'].items():
        if not found:
            continue
        expected = source['grouped'][case]
        ready = sum(found.get(rel) == info['bytes'] for rel, info in expected.items())
        mode = source['cfg']['vertical']
        results.append({'kind': source['kind'], 'path': str(source['path'].resolve()),
                        'case': case, 'cases': [case], 'mode': mode,
                        'config_hash': source['plan']['config_hash'],
                        'parent_manifest_sha256': _digest(source['manifest_bytes']),
                        'selection_sha256': _selection_digest(source, case),
                        'expected_records': len(expected), 'ready_records': ready,
                        'prepared': source['prepared'],
                        'label': '%s | %s | %d/%d files | %s' %
                                 (case, mode, ready, len(expected), source['path'])})
    return results


def _normalize_group(group):
    if group is None or str(group).strip() == '':
        return None
    value = str(group).strip()
    if value.lower() == 'all':
        return 'all'
    if value in ('1', '2', '3'):
        return CASES[int(value) - 1]
    _need(value in CASES, 'GROUP must be None, 1, 2, 3, an exact case name, or "all"')
    return value


def _bounded_paths(search_roots, max_depth=4, max_directories=400):
    visited = set()
    queue = deque((Path(p).expanduser(), 0) for p in search_roots if p is not None)
    directories = 0
    while queue and directories < max_directories:
        path, depth = queue.popleft()
        if not path.exists():
            continue
        resolved = str(path.resolve())
        if resolved in visited:
            continue
        visited.add(resolved)
        if path.is_file():
            if path.name.lower().endswith(('.tar', '.tar.gz', '.tgz')):
                yield 'archive', path
            continue
        directories += 1
        if (path / 'manifest.json').is_file():
            yield 'dataset', path
            continue
        if depth >= max_depth:
            continue
        try:
            children = sorted(path.iterdir(), key=lambda p: p.name.lower())
        except OSError as exc:
            DISCOVERY_WARNINGS.append('Cannot search %s: %s' % (path, exc))
            continue
        for child in children:
            if child.name.startswith('.') or child.name in _SKIP:
                continue
            if child.is_file() and child.name.lower().endswith(('.tar', '.tar.gz', '.tgz')):
                queue.append((child, depth + 1))
            elif child.is_dir() and not child.is_symlink():
                queue.append((child, depth + 1))
    if queue:
        DISCOVERY_WARNINGS.append('Search reached its folder limit; set DATA_HINT to the exact TAR or data folder.')


def discover_student_data(search_roots, group=None, data_hint=None, mode=None):
    """Return unambiguous candidate choices; no data are extracted by discovery.

    Search is bounded to the supplied roots, four levels, and 400 folders.
    Demo folders are excluded. Multiple modes/groups/configurations remain
    explicit choices. Identical archive/directory copies are deduplicated.
    """
    DISCOVERY_WARNINGS.clear()
    group = _normalize_group(group)
    _need(mode in (None, '', 'full', 'surface'), 'MODE must be None, "full", or "surface"')
    roots = [data_hint] if data_hint else search_roots
    if data_hint:
        _need(Path(data_hint).expanduser().exists(), 'DATA_HINT does not exist: ' + str(data_hint))
    candidates = []
    for kind, path in _bounded_paths(roots):
        try:
            source = _load_source(path.resolve(), kind)
            candidates.extend(_candidates(source))
        except (OSError, ValueError, KeyError, TypeError, tarfile.TarError) as exc:
            DISCOVERY_WARNINGS.append('%s: %s' % (path, exc))
    candidates = [c for c in candidates if (not mode or c['mode'] == mode)
                  and (group in (None, 'all') or c['case'] == group)]
    # Prefer a complete prepared copy, then a complete extracted copy, then TAR.
    def rank(c):
        return (c['ready_records'] != c['expected_records'],
                0 if c['prepared'] else 1 if c['kind'] == 'dataset' else 2, c['path'])
    unique = {}
    for candidate in sorted(candidates, key=rank):
        key = (candidate['case'], candidate['mode'], candidate['config_hash'], candidate['selection_sha256'])
        unique.setdefault(key, candidate)
    candidates = sorted(unique.values(), key=lambda c: (c['mode'], c['case'], c['path']))
    if group == 'all':
        groups = {}
        for candidate in candidates:
            key = (candidate['mode'], candidate['config_hash'], candidate['parent_manifest_sha256'])
            groups.setdefault(key, []).append(candidate)
        collections = []
        for (vertical, signature, parent), members in groups.items():
            names = sorted({c['case'] for c in members})
            _need(len(names) == len(members), 'Conflicting copies of a group; narrow DATA_HINT.')
            collections.append({'kind': 'collection', 'members': members, 'cases': names,
                                'case': '+'.join(names), 'mode': vertical, 'config_hash': signature,
                                'parent_manifest_sha256': parent,
                                'expected_records': sum(c['expected_records'] for c in members),
                                'label': '%s | %s | selected available groups' % (', '.join(names), vertical)})
        return collections
    return candidates


def _atomic_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='wb', prefix='.' + path.name + '.',
                                     suffix='.part', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_json(path, data):
    _atomic_bytes(path, (json.dumps(data, indent=2, allow_nan=False) + '\n').encode('utf-8'))


def _file_ready(path, entry, state):
    if not path.is_file() or not state:
        return False
    stat = path.stat()
    return stat.st_size == entry['bytes'] == state.get('bytes') and stat.st_mtime_ns == state.get('mtime_ns')


def _enough_space(root, size):
    free = shutil.disk_usage(root).free
    _need(free >= size + 256 * 1024**2,
          'Insufficient working-disk space: need approximately %.2f GiB more, plus plotting space; '
          'only %.2f GiB is available. Choose another WORK_ROOT.' % (size / 2**30, free / 2**30))


def _stream_to_file(stream, target, expected_bytes):
    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', prefix='.' + target.name + '.',
                                         suffix='.part', dir=target.parent, delete=False) as output:
            temporary = Path(output.name)
            while True:
                chunk = stream.read(8 * 1024**2)
                if not chunk:
                    break
                output.write(chunk)
                written += len(chunk)
        _need(written == expected_bytes, 'Incomplete extracted file: ' + str(target))
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def prepare_student_dataset(candidate, work_root=None):
    """Stream/copy selected files into a resumable workspace and scope metadata.

    On Colab pass a runtime-local work_root; store final results ZIPs in Drive.
    Local hardlinks are used when possible for already-extracted input data.
    Original inputs and original metadata bytes remain unchanged.
    """
    selected = candidate.get('members', [candidate])
    _need(bool(selected), 'No selected group data')
    source_cache, sources = {}, []
    for item in selected:
        key = (item['kind'], item['path'])
        if key not in source_cache:
            source_cache[key] = _load_source(Path(item['path']).resolve(), item['kind'])
        source = source_cache[key]
        case = item['case']
        _need(source['plan']['config_hash'] == item['config_hash']
              and _digest(source['manifest_bytes']) == item['parent_manifest_sha256']
              and _selection_digest(source, case) == item['selection_sha256'],
              'Source metadata changed after discovery; rerun the discovery cell')
        expected = source['grouped'][case]
        found = source['available'].get(case, {})
        missing = [rel for rel, info in expected.items() if found.get(rel) != info['bytes']]
        _need(not missing, '%s is incomplete or has size mismatches (%d file(s)); first: %s. '
              'Finish/retry the group download or upload.' %
              (case, len(missing), missing[0] if missing else ''))
        sources.append((case, source))
    first = sources[0][1]
    cases = sorted(case for case, _ in sources)
    _need(len(cases) == len(set(cases)), 'Selected group appears more than once')
    parent_digest = _digest(first['manifest_bytes'])
    _need(all(s['plan']['config_hash'] == first['plan']['config_hash']
              and s['cfg']['vertical'] == first['cfg']['vertical']
              and _digest(s['manifest_bytes']) == parent_digest for _, s in sources),
          'Selected groups come from different exports; choose one matching export')
    work = Path(work_root or (Path.cwd() / 'WRF_Classroom_Work')).expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)
    mode = first['cfg']['vertical']
    group_tag = '_'.join('g%d' % (CASES.index(case)+1) for case in cases)
    tag = '%s_%s_%s_%s' % (mode, group_tag, first['plan']['config_hash'][:10], parent_digest[:8])
    destination = work / 'data' / tag
    destination.mkdir(parents=True, exist_ok=True)
    lock = destination / '.prepare.lock'
    try:
        descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise PreparationError('Preparation lock exists: %s. Another kernel may be extracting. '
                               'Stop the other run first; remove a stale lock only after confirming it stopped.' % lock) from exc
    with os.fdopen(descriptor, 'w') as stream:
        stream.write('pid=%d\n' % os.getpid())
    warnings = []
    selected_files = {rel: info for case, source in sources for rel, info in source['grouped'][case].items()}
    identity = {'parent_manifest_sha256': parent_digest, 'config_hash': first['plan']['config_hash'],
                'selected_cases': cases}
    state_path = destination / 'extraction_state.json'
    state = {'identity': identity, 'files': {}}
    try:
        if state_path.is_file():
            old = json.loads(state_path.read_text(encoding='utf-8'))
            if old.get('identity') == identity:
                state = old
        counter = 0
        for case, source in sources:
            wanted = source['grouped'][case]
            pending = [(rel, info) for rel, info in sorted(wanted.items())
                       if not _file_ready(_within(destination, rel), info, state['files'].get(rel))]
            if source['kind'] == 'archive':
                _enough_space(work, sum(info['bytes'] for _, info in pending))
                with tarfile.open(source['path'], 'r:*') as handle:
                    index = _archive_index(handle)
                    for rel, info in pending:
                        member = index.get(rel)
                        _need(member is not None and member.size == info['bytes'], 'Archive file size changed: ' + rel)
                        target = _within(destination, rel)
                        stream = handle.extractfile(member)
                        _need(stream is not None, 'Cannot extract ' + rel)
                        with stream:
                            _stream_to_file(stream, target, info['bytes'])
                        stat = target.stat()
                        state['files'][rel] = {'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
                        _atomic_json(state_path, state)
                        counter += 1
                        print('Prepared %s (%d / %d newly needed for this group)' % (Path(rel).name,
                              sum(r in state['files'] for r, _ in pending), len(pending)), flush=True)
                after = source['path'].stat()
                _need((after.st_size, after.st_mtime_ns) == source['stat'],
                      'Source archive changed during extraction; rerun discovery')
            else:
                for rel, info in pending:
                    original, target = _within(source['path'], rel), _within(destination, rel)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if original.resolve() != target.resolve():
                        temporary = target.with_name(target.name + '.part')
                        try:
                            if temporary.exists():
                                temporary.unlink()
                            try:
                                os.link(original, temporary)
                                os.replace(temporary, target)
                            except OSError:
                                if temporary.exists():
                                    temporary.unlink()
                                _enough_space(work, info['bytes'])
                                with original.open('rb') as stream:
                                    _stream_to_file(stream, target, info['bytes'])
                        finally:
                            if temporary.exists():
                                temporary.unlink()
                    _need(target.stat().st_size == info['bytes'], 'Copied size differs: ' + rel)
                    stat = target.stat()
                    state['files'][rel] = {'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
                    _atomic_json(state_path, state)
                    counter += 1
                current = _folder_metadata(source['path'])
                _need(_digest(current['manifest_bytes']) == parent_digest,
                      'Source metadata changed during preparation')
        for rel, info in selected_files.items():
            _need(_file_ready(_within(destination, rel), info, state['files'].get(rel)),
                  'Prepared file is not ready: ' + rel)
        provenance = destination / 'provenance'
        _atomic_bytes(provenance / 'source_manifest.json', first['manifest_bytes'])
        _atomic_bytes(provenance / 'source_plan.json', first['plan_bytes'])
        scope = {'kind': 'selected_cases', 'selected_cases': cases,
                 'parent_manifest_sha256': parent_digest,
                 'parent_manifest_file': 'provenance/source_manifest.json',
                 'parent_complete': True, 'parent_planned_files': first['manifest']['planned_files'],
                 'parent_config_hash': first['plan']['config_hash']}
        scoped = {'version': first['manifest'].get('version', '1.0.0'),
                  'config_hash': first['plan']['config_hash'], 'complete': True,
                  'planned_files': len(selected_files), 'files': dict(sorted(selected_files.items())),
                  'output_data_bytes': sum(x['bytes'] for x in selected_files.values()),
                  'classroom_scope': scope}
        _atomic_json(destination / 'selection_plan.json',
                     {'workflow_version': WORKFLOW_VERSION, 'scope': scope,
                      'vertical': mode, 'selected_times': first['cfg']['selected_times'],
                      'primary_variables': first['cfg']['primary_variables'],
                      'selected_files': len(selected_files), 'source_plan_file': 'provenance/source_plan.json'})
        _atomic_json(destination / 'manifest.json', scoped)
        if counter == 0:
            print('Reusing %d prepared files for %s.' % (len(selected_files), ', '.join(cases)), flush=True)
        print('Selected group data ready: %d snapshots, %s mode, %s.' %
              (len(selected_files), mode, ', '.join(cases)), flush=True)
        return {'data_root': str(destination), 'output_root': str(work / 'results' / tag),
                'case': '+'.join(cases), 'cases': cases, 'mode': mode,
                'expected_records': len(selected_files), 'source_complete': True, 'warnings': warnings}
    finally:
        lock.unlink(missing_ok=True)
