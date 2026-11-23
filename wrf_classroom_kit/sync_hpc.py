#!/usr/bin/env python3
"""Download completed WRF Lite snapshots using SFTP, with atomic local publication.

Uses the reducer's manifest. It does not run programs on the HPC, upload data,
delete data, change SSH settings, or save passwords. A verified known_hosts
entry is mandatory. Run beside the plotting watcher in a second terminal.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import time
from typing import Any

try:
    import paramiko
except ImportError:
    raise SystemExit('Missing paramiko. Run the kit setup, then use its Conda environment.')

MAX_JSON_BYTES = 16 * 1024 * 1024
SAFE_CASE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')
SAFE_FILE = re.compile(r'^wrflite_d[0-9]+_[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}\.nc$')


def atomic_json(path: Path, value: Any) -> None:
    tmp = path.with_name(path.name + f'.tmp.{os.getpid()}')
    with tmp.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def safe_relative(name: str) -> PurePosixPath:
    relative = PurePosixPath(name)
    if '\\' in name or relative.is_absolute() or len(relative.parts) != 2:
        raise ValueError(f'Unexpected manifest path: {name!r}')
    if not SAFE_CASE.fullmatch(relative.parts[0]) or relative.parts[0] in ('.', '..'):
        raise ValueError(f'Unexpected experiment directory: {name!r}')
    if not SAFE_FILE.fullmatch(relative.name):
        raise ValueError(f'Unexpected reduced filename: {name!r}')
    return relative


def local_target(root: Path, relative: PurePosixPath) -> Path:
    target = root.joinpath(*relative.parts)
    if target.is_symlink() or any(parent.is_symlink() for parent in target.parents if parent != root.parent):
        raise ValueError(f'Refusing symlinked local destination: {target}')
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('A destination path escapes the local root.')
    return target


def remote_json(sftp: Any, remote_path: str) -> dict[str, Any]:
    with sftp.open(remote_path, 'rb') as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError(f'Unexpectedly large metadata file: {remote_path}')
    value = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError(f'Expected a JSON object: {remote_path}')
    return value


def entry_signature(entry: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(entry, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def transfer_file(sftp: Any, remote: str, target: Path, expected_bytes: int) -> str:
    before = sftp.stat(remote)
    if before.st_size != expected_bytes or not stat.S_ISREG(before.st_mode):
        raise ValueError(f'Remote file does not match its completed manifest entry: {remote}')
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + f'.part.{os.getpid()}')
    hasher = hashlib.sha256()
    count = 0
    try:
        with sftp.open(remote, 'rb') as source, temporary.open('wb') as destination:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                count += len(chunk)
                if count > expected_bytes:
                    raise ValueError(f'Remote file grew during transfer: {remote}')
                destination.write(chunk)
                hasher.update(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        after = sftp.stat(remote)
        if count != expected_bytes or after.st_size != before.st_size or after.st_mtime != before.st_mtime:
            raise ValueError(f'Remote file changed during transfer: {remote}')
        os.replace(temporary, target)
    finally:
        # Only this process's incomplete temporary file is removed.
        if temporary.exists():
            temporary.unlink()
    return hasher.hexdigest()


def load_local_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    result = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(result, dict):
        raise ValueError(f'Expected an object in {path}')
    return result


def sync_once(sftp: Any, remote_root: str, local_root: Path) -> tuple[int, bool, int]:
    manifest = remote_json(sftp, remote_root + '/manifest.json')
    entries = manifest.get('files')
    if not isinstance(entries, dict):
        raise ValueError('Remote manifest has no files mapping. Is this a WRF Lite output root?')
    old_manifest = load_local_json(local_root / 'manifest.json')
    if old_manifest and old_manifest.get('config_hash') != manifest.get('config_hash'):
        raise ValueError('Local and remote conversion configurations differ. Choose a new --local directory.')
    state_path = local_root / 'sync_state.json'
    state = load_local_json(state_path)
    state_entries = state.setdefault('files', {})
    ready: dict[str, Any] = {}
    for name, entry in entries.items():
        relative = safe_relative(name)
        if not isinstance(entry, dict) or type(entry.get('bytes')) is not int or entry['bytes'] <= 0:
            raise ValueError(f'Invalid size in manifest: {name}')
        target = local_target(local_root, relative)
        previous = state_entries.get(name, {})
        if target.is_file():
            st = target.stat()
            if (st.st_size == entry['bytes'] and previous.get('entry_signature') == entry_signature(entry)
                    and previous.get('mtime_ns') == st.st_mtime_ns):
                ready[name] = entry

    def publish() -> bool:
        local = dict(manifest)
        local['files'] = dict(ready)
        planned = int(manifest.get('planned_files', len(entries)))
        complete = bool(manifest.get('complete')) and len(ready) == len(entries) == planned
        local['complete'] = complete
        local['output_data_bytes'] = sum(entry['bytes'] for entry in ready.values())
        local['sync_note'] = 'Only atomically downloaded completed files are listed; source files are unchanged.'
        atomic_json(local_root / 'manifest.json', local)
        atomic_json(state_path, state)
        return complete

    # Publish an empty/partial manifest before any final .nc appears locally.
    publish()
    transferred = 0
    for name, entry in sorted(entries.items()):
        if name in ready:
            continue
        relative = safe_relative(name)
        target = local_target(local_root, relative)
        print(f'Downloading {name} ({entry["bytes"] / 2**20:.1f} MiB)', flush=True)
        digest = transfer_file(sftp, str(PurePosixPath(remote_root) / relative), target, entry['bytes'])
        st = target.stat()
        state_entries[name] = {'entry_signature': entry_signature(entry), 'mtime_ns': st.st_mtime_ns,
                               'bytes': st.st_size, 'sha256_file': digest}
        ready[name] = entry
        transferred += 1
        publish()
    for metadata_name in ('plan.json', 'pilot_summary.json'):
        try:
            metadata = remote_json(sftp, remote_root + '/' + metadata_name)
        except OSError:
            continue
        atomic_json(local_root / metadata_name, metadata)
    complete = publish()
    return transferred, complete, len(ready)


def connect(args: argparse.Namespace, password: str | None) -> Any:
    known = Path(args.known_hosts).expanduser()
    if not known.is_file():
        raise ValueError(f'No known_hosts file at {known}. First log in with native ssh and verify the host fingerprint with your HPC administrator.')
    client = paramiko.SSHClient()
    client.load_host_keys(str(known))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(hostname=args.host, port=args.port, username=args.user,
                   password=password, key_filename=args.key_file,
                   allow_agent=args.agent, look_for_keys=False,
                   timeout=30, banner_timeout=30, auth_timeout=30)
    transport = client.get_transport()
    if transport:
        transport.set_keepalive(30)
    return client


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='10.1.4.95')
    parser.add_argument('--port', type=int, default=22)
    parser.add_argument('--user', default='neha.palak_ug2023')
    parser.add_argument('--remote', required=True, help='Absolute full OR surface WRF Lite output root on the HPC')
    parser.add_argument('--local', required=True, type=Path, help='Separate local directory for that root')
    parser.add_argument('--known-hosts', default=str(Path.home() / '.ssh' / 'known_hosts'))
    parser.add_argument('--key-file', help='Explicit private-key path; absent by default')
    parser.add_argument('--agent', action='store_true', help='Use keys from your SSH agent instead of prompting for a password')
    parser.add_argument('--watch', action='store_true', help='Poll for newly finished files until complete, idle, or interrupted')
    parser.add_argument('--poll-seconds', type=int, default=60)
    parser.add_argument('--idle-minutes', type=float, default=60)
    args = parser.parse_args()
    remote_path = PurePosixPath(args.remote)
    if not remote_path.is_absolute() or '..' in remote_path.parts:
        parser.error('--remote must be an absolute path without ..')
    if args.poll_seconds < 10 or args.idle_minutes <= 0:
        parser.error('Use poll-seconds >=10 and idle-minutes >0.')
    args.remote = str(remote_path)
    args.local = args.local.expanduser().absolute()
    args.local.mkdir(parents=True, exist_ok=True)
    password = None if args.key_file or args.agent else getpass.getpass(f'{args.user}@{args.host} password (not saved): ')
    last_progress = time.monotonic()
    consecutive_failures = 0
    client = None
    try:
        while True:
            try:
                if client is None or client.get_transport() is None or not client.get_transport().is_active():
                    if client is not None:
                        client.close()
                    client = connect(args, password)
                with client.open_sftp() as sftp:
                    transferred, complete, count = sync_once(sftp, args.remote, args.local)
                consecutive_failures = 0
                if transferred:
                    last_progress = time.monotonic()
                print(f'{count} completed snapshots available locally. Conversion complete: {complete}', flush=True)
                if complete or not args.watch:
                    return 0
            except (paramiko.AuthenticationException, paramiko.BadHostKeyException) as exc:
                print(f'SSH verification/authentication failed: {exc}. No automatic retry.', file=sys.stderr)
                return 2
            except (OSError, EOFError, paramiko.SSHException) as exc:
                if client:
                    client.close()
                client = None
                consecutive_failures += 1
                if not args.watch or consecutive_failures >= 5:
                    print(f'Sync stopped: {exc}', file=sys.stderr)
                    return 2
                print(f'Transfer unavailable ({exc}); retry {consecutive_failures}/5 after the poll interval.', flush=True)
            if time.monotonic() - last_progress >= args.idle_minutes * 60:
                print('Idle timeout reached. Existing completed files are ready; rerun sync to continue.', flush=True)
                return 0
            time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        print('\nStopped. Completed snapshots are retained; rerun to continue.')
        return 0
    except (ValueError, json.JSONDecodeError) as exc:
        print(f'Sync configuration/data error: {exc}', file=sys.stderr)
        return 2
    finally:
        if client:
            client.close()


if __name__ == '__main__':
    raise SystemExit(main())
