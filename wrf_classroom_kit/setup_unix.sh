#!/usr/bin/env bash
# Personal setup for macOS, Linux and WSL. Run with bash, not sudo.
set -euo pipefail
kit_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
install_root="${WRF_CLASSROOM_INSTALL_ROOT:-$HOME/.local/share/wrf-classroom}"
if [[ $# -gt 0 ]]; then
    if [[ $# -eq 2 && "$1" == '--install-root' ]]; then install_root="$2";
    else printf '%s\n' 'Usage: bash setup_unix.sh [--install-root /absolute/writable/path]' >&2; exit 2; fi
fi
if [[ "$install_root" != /* || "$install_root" == *$'\n'* ]]; then
    printf '%s\n' 'Choose an absolute installation path without newlines.' >&2; exit 2
fi
mkdir -p -- "$install_root"
install_root="$(cd -- "$install_root" && pwd)"
wrf_conda=''
for candidate in "${CONDA_EXE:-}" "$(type -P conda || true)" "$install_root/miniforge3/bin/conda" "$HOME/miniforge3/bin/conda" "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda"; do
    if [[ -n "$candidate" && -x "$candidate" ]] && "$candidate" --version; then wrf_conda="$candidate"; break; fi
done
if [[ -z "$wrf_conda" ]]; then
    os_name="$(uname -s)"; arch="$(uname -m)"
    if [[ "$os_name" == Darwin ]]; then
        os_name='MacOSX'
        # Install native Apple Silicon binaries even from a Rosetta terminal.
        if [[ "$(sysctl -n hw.optional.arm64 2>/dev/null || true)" == 1 ]]; then arch='arm64'; fi
    fi
    case "$os_name-$arch" in
        Linux-x86_64) expected='bbaf16b3897da24c4be50315934ba74848f617b4495982841d6a0a60e0edbbdf' ;;
        Linux-aarch64) expected='1adf18b530e4ffb00886ce6d5bd2eb1fa6311d2f14709b13bd154d8cd98d94c8' ;;
        MacOSX-x86_64) expected='30e82ce68875fc50b917a3a541ea0516272866584187f7ea980ce8eaf715807d' ;;
        MacOSX-arm64) expected='fb567612b76f4ef46de326f04425dbe381b6afc6a66c545f5043255a5ef34258' ;;
        *) printf 'Unsupported bootstrap platform: %s-%s. Use Colab or an existing compatible Conda installation.\n' "$os_name" "$arch" >&2; exit 2 ;;
    esac
    if [[ "$install_root" == *' '* ]]; then
        printf '%s\n' 'For the Miniforge bootstrap, use --install-root with a writable path without spaces.' >&2; exit 2
    fi
    release='26.9.4-2'
    asset="Miniforge3-$release-$os_name-$arch.sh"
    installer="$install_root/downloads/$asset"
    mkdir -p -- "$install_root/downloads"
    hash_file() {
        if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}';
        elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}';
        else printf '%s\n' 'Install sha256sum or shasum before continuing.' >&2; exit 2; fi
    }
    if [[ ! -f "$installer" ]] || [[ "$(hash_file "$installer")" != "$expected" ]]; then
        url="https://github.com/conda-forge/miniforge/releases/download/$release/$asset"
        printf 'Downloading Miniforge %s...\n' "$release"
        if command -v curl >/dev/null 2>&1; then curl --fail --location --retry 3 --connect-timeout 30 --output "$installer.part" "$url";
        elif command -v wget >/dev/null 2>&1; then wget --tries=3 --timeout=30 --output-document="$installer.part" "$url";
        else printf '%s\n' 'Install curl or wget, then rerun setup.' >&2; exit 2; fi
        if [[ "$(hash_file "$installer.part")" != "$expected" ]]; then
            printf '%s\n' 'Installer SHA256 verification failed. The installer was not executed.' >&2; exit 1
        fi
        mv -- "$installer.part" "$installer"
    fi
    base_prefix="$install_root/miniforge3"
    if [[ -e "$base_prefix" ]]; then
        printf 'An incomplete installation exists at %s; inspect it or choose another --install-root.\n' "$base_prefix" >&2; exit 1
    fi
    bash "$installer" -b -p "$base_prefix"
    wrf_conda="$base_prefix/bin/conda"
fi
env_prefix="$install_root/env-v1"
verb='create'
if [[ -f "$env_prefix/conda-meta/history" ]]; then verb='install';
elif [[ -e "$env_prefix" ]]; then printf 'Not a Conda environment: %s. Choose another --install-root.\n' "$env_prefix" >&2; exit 1; fi
specs=('python=3.11' 'numpy>=1.26,<3' 'netcdf4>=1.6.5,<2' 'matplotlib>=3.8,<4' 'pillow>=10,<13' 'paramiko>=3.4,<5' 'pip')
"$wrf_conda" "$verb" --yes --prefix "$env_prefix" --override-channels --channel conda-forge --strict-channel-priority "${specs[@]}"
"$wrf_conda" run --no-capture-output --prefix "$env_prefix" python -c "import sys,numpy,netCDF4,matplotlib,PIL,paramiko; print('Environment ready:',sys.version.split()[0]); print('NumPy',numpy.__version__,'netCDF4',netCDF4.__version__,'Matplotlib',matplotlib.__version__)"
printf '%s\n%s\n' "$wrf_conda" "$env_prefix" > "$kit_dir/.runtime-unix.txt"
"$env_prefix/bin/python" - "$kit_dir/.runtime.json" "$wrf_conda" "$env_prefix" <<'PY'
import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps(dict(conda=sys.argv[2],prefix=sys.argv[3],platform=sys.platform,kit_version='1.0.0'),indent=2)+'\n')
PY
"$wrf_conda" list --prefix "$env_prefix" --explicit > "$install_root/resolved-packages.txt"
printf '%s\n' 'Setup complete. Run: bash run_unix.sh run --data /path/to/reduced_data --output /path/to/plots'
