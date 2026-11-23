# Install, transfer and run the classroom kit

Unzip the plotting kit and open a terminal in the directory containing `wrf_classroom.py`. Keep its files together. Paths to your input and output directories may contain spaces; always put those paths in quotes.

## Windows PowerShell: first setup

On a 64-bit Intel/AMD Windows 10/11 laptop, start a temporary PowerShell session for the supplied scripts:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -NoExit
```

Then run setup in that session:

```powershell
.\setup_windows.ps1
```

Keep this session open for the launch/sync commands below. Type `exit` when finished. This process-only execution policy applies to the temporary session; setup does not change your permanent PowerShell policy. A managed computer's enforced policy can still block scripts. In that case use the Colab notebook or ask your institution to approve the supplied script.

Setup reuses an existing working Conda installation when found. Otherwise it downloads the official Miniforge **26.9.4-2** installer, checks its SHA256 against the release digest, and installs it for your Windows user. It then creates a separate classroom environment under `%LOCALAPPDATA%\WRFClassroom\env-v1`. It does not run `conda init`, register Python as your system Python, or change the system PATH. A successful dependency check is followed by a local `.runtime.json` recording the exact environment paths. No activation command is needed.

Rerunning setup repairs/updates only the kit's `env-v1` environment to the declared package constraints. It does not remove another environment. Installed package versions are recorded in `resolved-packages.txt` under the installation directory.

Miniforge documents limitations with special characters and spaces in installation paths. Setup uses a Windows short path when one exists and quotes program arguments. If your user-profile path is incompatible, choose a **writable ASCII path** on your own drive:

```powershell
.\setup_windows.ps1 -InstallRoot D:\WRFClassroom
```

The kit/data directories themselves can be elsewhere. Do not use administrator mode just to write an unsuitable installation location. Windows ARM has an experimental upstream installer; this kit's automatic Windows bootstrap is restricted to Intel/AMD x86_64. Colab is available for other laptops.

## Put the data in a local folder

Use one root for full files and another root for surface files. Within each root keep the original experiment folders and `manifest.json`/`plan.json`:

```text
WRF_Data/full/manifest.json
WRF_Data/full/plan.json
WRF_Data/full/01_CTRL/wrflite_d01_2023-06-22_00-00-00.nc
WRF_Data/full/02_CTRL_NOISE/...
WRF_Data/full/03_CLEAN/...
WRF_Data/surface/manifest.json
WRF_Data/surface/01_CTRL/...
```

For completed TAR archives, create an empty destination and extract each archive into that same root. Do not put full and surface archives in the same destination. Native Windows `tar` can extract the archives:

```powershell
$dest = "$env:USERPROFILE\Downloads\WRF_Data\full"
New-Item -ItemType Directory -Force $dest | Out-Null
tar -xf "$env:USERPROFILE\Downloads\01_CTRL_lite.tar" -C $dest
tar -xf "$env:USERPROFILE\Downloads\02_CTRL_NOISE_lite.tar" -C $dest
tar -xf "$env:USERPROFILE\Downloads\03_CLEAN_lite.tar" -C $dest
```

Each archive includes shared metadata. When all three came from the same completed conversion it is safe for later extractions to replace the identical shared metadata. Do not combine archives from different conversion settings.

## Render on Windows

First use a small pilot:

```powershell
.\run_windows.ps1 -Data "$env:USERPROFILE\Downloads\WRF_Data\full" -Output "$env:USERPROFILE\Downloads\WRF_Plots" -Fields 'PM2_5_DRY,so2,RAINNC' -MaxFrames 3
```

Then generate all products from the full dataset:

```powershell
.\run_windows.ps1 -Data "$env:USERPROFILE\Downloads\WRF_Data\full" -Output "$env:USERPROFILE\Downloads\WRF_Plots"
```

To try the software immediately before your real files arrive, use the bundled synthetic test dataset:

```powershell
.\run_windows.ps1 -Data .\demo_data\full -Output .\demo_plots -Fields 'PM2_5_DRY,so2,RAINNC' -MaxFrames 3
```

The demo contains invented values and is clearly labelled; it is not an India forecast or observational dataset.

If script execution is blocked by the default local policy, run the launcher through a process-only policy just as for setup:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_windows.ps1 -Data "$env:USERPROFILE\Downloads\WRF_Data\full" -Output "$env:USERPROFILE\Downloads\WRF_Plots"
```

In an already permitted PowerShell session you can pass both roots as an array:

```powershell
.\run_windows.ps1 -Data @("$env:USERPROFILE\Downloads\WRF_Data\full", "$env:USERPROFILE\Downloads\WRF_Data\surface") -Output "$env:USERPROFILE\Downloads\WRF_Plots"
```

To inspect instead of render, use `-Inspect`; an output path is optional:

```powershell
.\run_windows.ps1 -Inspect -Data "$env:USERPROFILE\Downloads\WRF_Data\full"
```

Add `-Watch` to keep looking for newly completed files. Stop with Ctrl+C; existing completed products remain available. When omitted, `-Output` defaults to `classroom_output` inside the extracted kit.

## Download files while the HPC conversion runs

This is optional; completed TAR archives work without SFTP. Run this **on a laptop with campus network/VPN access**, not on the HPC master. It uses SFTP over SSH, the same encrypted connection family as current SCP, and does not run computation on the HPC.

First use native SSH with the intended account. On first contact verify the server fingerprint with the administrator before accepting it. The synchronizer requires that verified `known_hosts` entry and never accepts an unknown key automatically:

```powershell
ssh neha.palak_ug2023@10.1.4.95
```

After checking the login, type `exit` to return to **local PowerShell**. In the extracted plotting-kit folder start the full-data downloader:

```powershell
.\sync_windows.ps1 -Remote /storage/neha.palak_ug2023/wrfchem/MSA_CANDIDATE_V1/134061_LITE_3H_full -Local "$env:USERPROFILE\Downloads\WRF_Data\full" -Watch
```

Enter the password only at the hidden local prompt. The script keeps it only in process memory and never writes it to a file. For an existing key add `-KeyFile C:\path\to\your_private_key`; for an already configured SSH agent add `-Agent`. Defaults are `-Host 10.1.4.95` and `-User neha.palak_ug2023`; change them for another authorized account. Add `-KnownHosts C:\path\to\known_hosts` only when you intentionally use a different verified host-key file. The synchronizer does not modify your SSH configuration.

For surface data change both the remote suffix and local destination:

```powershell
.\sync_windows.ps1 -Remote /storage/neha.palak_ug2023/wrfchem/MSA_CANDIDATE_V1/134061_LITE_3H_surface -Local "$env:USERPROFILE\Downloads\WRF_Data\surface" -Watch
```

Use separate processes for separate roots. Do not run two synchronizers against the same local root. Omit `-Watch` for one pass. Polling defaults to 60 seconds and a 30-minute idle timeout; change `-PollSeconds` or `-IdleMinutes` when appropriate. The script downloads only completed entries in the reducer manifest, writes them as temporary files, checks transferred sizes, then renames them atomically and publishes the local manifest. It resumes completed transfers on rerun; an interrupted individual file is downloaded again. It never deletes completed local or remote data.

In a **second PowerShell window**, run the plotting watcher:

```powershell
.\run_windows.ps1 -Data "$env:USERPROFILE\Downloads\WRF_Data\full" -Output "$env:USERPROFILE\Downloads\WRF_Plots" -Watch
```

Once the reducer reports complete and all files have arrived, the watcher can finish the complete product. Until then the outputs describe the available portion of the record. Empty/missing input roots during early conversion should be monitored through the program's status messages. Plotting cannot finish future timestamps before their files arrive.

## macOS, Linux and WSL

Supported bootstrap targets are macOS 11+ on Intel/Apple Silicon and Linux x86_64/aarch64 with compatible glibc. WSL uses the Linux script inside its Linux terminal. Run without `sudo`:

```bash
bash setup_unix.sh
bash run_unix.sh inspect --data "$HOME/WRF_Data/full"
bash run_unix.sh run --data "$HOME/WRF_Data/full" --output "$HOME/WRF_Plots" --fields PM2_5_DRY,so2,RAINNC --max-frames 3
bash run_unix.sh run --data "$HOME/WRF_Data/full" --output "$HOME/WRF_Plots"
```

The default installation is `$HOME/.local/share/wrf-classroom`. A custom location is supported:

```bash
bash setup_unix.sh --install-root /absolute/writable/path/wrf-classroom
```

If no existing Conda installation is found, the bootstrap requires a path without spaces. Scientific packages come from conda-forge only. To watch both variants:

```bash
bash run_unix.sh watch --data "$HOME/WRF_Data/full" "$HOME/WRF_Data/surface" --output "$HOME/WRF_Plots" --poll-seconds 60 --idle-minutes 30
```

To run SFTP on Unix, use the supplied wrapper, which automatically locates the installed environment:

```bash
bash sync_unix.sh --remote /storage/neha.palak_ug2023/wrfchem/MSA_CANDIDATE_V1/134061_LITE_3H_full --local "$HOME/WRF_Data/full" --watch
```

## Google Colab

Use the updated student workflow version 2 notebook, `WRF_Classroom_Colab.ipynb`, together with the updated plotting-kit ZIP and only the assigned group's TAR. Put all three files in your own **My Drive / WRF_Classroom**. Open <https://colab.research.google.com/> and upload/open the notebook. See [STUDENT_NOTEBOOK_GUIDE.txt](STUDENT_NOTEBOOK_GUIDE.txt) for the complete student steps.

The notebook detects Colab, requests Drive authorization, finds and extracts the updated kit, installs its Python dependencies as needed, and discovers the real group data. `GROUP = None` works when exactly one eligible group is available. Choose `1`, `2`, `3`, or an exact case name if needed; `GROUP = "all"` explicitly selects the available matching groups for comparison. Set `MODE`, `KIT_HINT` or `DATA_HINT` for ambiguous or nonstandard locations. A broad scan of the entire Drive is not attempted.

The TAR is streamed from Drive into runtime-local `/content/WRF_Classroom_Work`. Plot caches also stay local to avoid storing another large data copy in Drive. After a successful preview or complete run, a results ZIP is copied to **My Drive / WRF_Classroom / RESULTS**. Runtime-local data and unsaved work disappear when a Colab runtime is deleted; saved Drive ZIPs remain. Rerunning after a reset extracts the source archive again. Colab lifetime/resource limits still apply.

Run all produces a three-timestamp preview for the assigned group. To process the whole record, set `RUN_FULL = True` in the full-record cell and run that cell. Leave `FULL_FIELDS = ""` for all twenty primary fields and four derived products, or enter a comma-separated selection. A one-group complete run should process 41 snapshots, report complete **selected group** data, and contain no processing errors. Original three-group metadata is preserved as provenance rather than treated as missing student downloads.

## The same notebook in local VS Code

Open a local folder containing the notebook, updated kit ZIP and assigned TAR. Select a working 64-bit Python 3.10+ notebook kernel (Python 3.11 recommended) through VS Code's kernel selector. Microsoft Python/Jupyter extension support and `ipykernel` are prerequisites for executing notebook cells. The notebook cannot install or choose its initial kernel before that kernel is running.

Run the same cells. Local execution does not mount Drive. The notebook reuses a valid classroom Conda environment when available, or creates a private plotting virtual environment under its working directory, and invokes the engine through that interpreter. The notebook kernel's unrelated installed packages are not replaced. All local input, working and output paths are printed. Local TAR storage plus extraction needs roughly twice the archive size, with additional space for the environment and plotting outputs.

Both environments use the identical plotting engine, scientific settings and city list. The old Colab-only notebook and a ZIP without `classroom_autodetect.py` are not compatible with the version-2 automatic workflow. The synthetic demo remains available through the command-line examples, but it is never an automatic fallback for missing student data.

## Installation scope and checks

An internet connection is needed for the initial environment installation; no package manager can promise success through every proxy, institution policy or unsupported operating system. The bootstrap fails with a specific message instead of silently changing unrelated Python installations. Disk needs depend on your chosen data and generated plots. A CPU is sufficient; no CUDA/MPI/WRF compilation is required by this plotting kit.

Bootstrap source and integrity references, checked 18 November 2026:

- Miniforge installation, supported platforms and path caveats: <https://github.com/conda-forge/miniforge>
- Pinned release: <https://github.com/conda-forge/miniforge/releases/tag/26.9.4-2>
- Release asset SHA256 digests: <https://api.github.com/repos/conda-forge/miniforge/releases/tags/26.9.4-2>
- Conda Windows silent-install flags: <https://docs.conda.io/projects/conda/en/stable/user-guide/install/windows.html>
- Paramiko known-host policies: <https://docs.paramiko.org/en/stable/api/client.html>
- Colab notebook import, Drive and runtime limits: <https://research.google.com/colaboratory/faq.html>
