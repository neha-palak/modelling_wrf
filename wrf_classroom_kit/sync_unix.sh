#!/usr/bin/env bash
set -euo pipefail
kit_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
runtime_file="$kit_dir/.runtime-unix.txt"
if [[ ! -f "$runtime_file" ]]; then printf '%s\n' 'Run bash setup_unix.sh first in this extracted kit directory.' >&2; exit 2; fi
{ IFS= read -r wrf_conda; IFS= read -r env_prefix; } < "$runtime_file"
if [[ ! -x "$wrf_conda" ]]; then printf '%s\n' 'The recorded Conda installation is missing. Rerun setup_unix.sh.' >&2; exit 2; fi
if [[ $# -eq 0 ]]; then set -- --help; fi
exec "$wrf_conda" run --no-capture-output --prefix "$env_prefix" python "$kit_dir/sync_hpc.py" "$@"
