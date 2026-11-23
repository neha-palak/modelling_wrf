# WRF India Classroom Plot Kit

**All twenty fields, India-view GIF maps, ten-city time series, and real vertical information where the data contain it.** This kit reads the reduced WRF-Chem NetCDF files produced by the companion WRF Lite reducer. It includes automatic Conda setup for supported laptops, the same workflow in Colab, incremental HPC downloads, a local results gallery, and a clearly marked synthetic practice dataset.

**Students: start with [START_HERE_STUDENTS.pdf](START_HERE_STUDENTS.pdf) or [STUDENT_NOTEBOOK_GUIDE.txt](STUDENT_NOTEBOOK_GUIDE.txt). Student workflow version 2 uses the same [WRF_Classroom_Colab.ipynb](WRF_Classroom_Colab.ipynb) in Google Colab and local VS Code.** Each student needs the updated plotting-kit ZIP, this notebook, and **only the TAR for their assigned group**. The full class archives have 41 snapshots and 39 atmospheric levels per group, covering 22–27 June 2023. Each full group archive is about 6 GiB.

Put these three files together in your own **My Drive / WRF_Classroom** for Colab, or in the local folder opened in VS Code. The notebook detects its runtime, locates the kit and input, prepares a plotting environment, and streams the selected TAR into its working directory. With one eligible group, leave `GROUP = None`; choose `1`, `2`, or `3` if several are present. Set `MODE` or `DATA_HINT` if multiple exports remain ambiguous. Discovery is bounded to known folders and never silently substitutes synthetic data.

**Run all initially makes a small preview.** After reviewing it, change `RUN_FULL = True` in the full-record cell and run that cell to make all-field plots. Colab extracts data and writes caches in its temporary runtime; successful results ZIPs are copied to **My Drive / WRF_Classroom / RESULTS**. Local VS Code uses a private plotting environment or a valid existing classroom Conda environment. A working local Python notebook kernel must be selected before the notebook can start; Drive authorization is required in Colab.

The preparation helper preserves the original archive, NetCDF values, and source metadata. It creates an explicitly scoped local manifest, so **one complete assigned group means 41 expected snapshots**, while the original three-group inventory is retained as provenance. Only the supplied group appears in its figures. To compare experiments, supply their matching archives and explicitly select `GROUP = "all"`.

Use **[INSTALL.md](INSTALL.md)** for additional platform-specific installation details. Read **[SCIENCE.md](SCIENCE.md)** for units and interpretation. The plotting software and synthetic practice data are included; the real HPC dataset must be supplied separately.

## 1. Optional synthetic practice and command-line workflow

Unzip the complete kit. In Windows PowerShell, enter the extracted `wrf_classroom_kit` directory. Keep all its files together.

Start a temporary PowerShell session that permits the supplied local scripts:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -NoExit
```

In that session run:

```powershell
.\setup_windows.ps1
.\run_windows.ps1 -Data .\demo_data\full -Output "$env:USERPROFILE\Downloads\WRF_Demo_Plots" -Fields 'PM2_5_DRY,so2,RAIN_RATE,WIND_SPEED' -MaxFrames 2
Invoke-Item "$env:USERPROFILE\Downloads\WRF_Demo_Plots\index.html"
```

Setup downloads and checks Miniforge only if a suitable existing Conda installation is not found, creates a separate environment, and records the paths for the launchers. The demo contains invented values, explicitly labelled **SYNTHETIC DEMO** in the data and graphics. It is a software exercise, not a reconstruction of the June 2023 weather or pollution.

The supplied demo has three experiments, four times, a small 30 × 30 horizontal grid, 39 full atmospheric levels, and a separate surface product. This lets every student install and learn the interface before real data finish downloading. To generate all twenty primary fields and four derived products, omit `-Fields` and `-MaxFrames`.

On macOS/Linux:

```bash
bash setup_unix.sh
bash run_unix.sh run --data demo_data/full --output demo_plots --fields PM2_5_DRY,so2,RAIN_RATE,WIND_SPEED --max-frames 2
```

The demo can be regenerated in a new directory with `python make_demo.py --output NEW_DIRECTORY` using the kit's Python environment.

## 2. Choose the right real dataset

**A full-level subset supplies both surface and vertical plots. Students do not need to download an additional surface copy when they already have full files.** A surface-only subset supplies the smaller map/time-series option.

| Input | Surface maps and city time series | Vertical products |
|---|---|---|
| `134061_LITE_3H_full` | All twenty retained fields; lowest model layer for the six atmospheric fields | Six fields at their available levels; physical-height plots require geopotential and terrain support |
| `134061_LITE_3H_surface` | All twenty retained fields | One retained atmospheric layer; full profiles cannot be recovered |

The six vertical fields are `PM2_5_DRY`, `PM10`, `TOT_DUST`, `BC1`, `so2`, and `OC1`. `T2`, `U10`, accumulated rain and the other fourteen surface fields do not have atmospheric vertical profiles in this subset.

Use the parent directory containing `01_CTRL`, `02_CTRL_NOISE`, `03_CLEAN`, and `manifest.json` as the input root. The actual filenames and internal `Times` determine the record; the software does not assume a fixed forecast date, 41 selected snapshots, or a particular horizontal resolution.

If a full conversion has not yet been started, the instructor can use [HPC_FULL_DATA.md](HPC_FULL_DATA.md). Do not launch a second reducer against an output directory already being written.

## 3. Instructor option: download and plot incrementally from the HPC

From the extracted kit on a campus-connected Windows laptop, in the permitted PowerShell session:

```powershell
.\sync_windows.ps1 -Remote /storage/neha.palak_ug2023/wrfchem/MSA_CANDIDATE_V1/134061_LITE_3H_full -Local "$env:USERPROFILE\Downloads\WRF_Data\full" -Watch
```

The default account is the instructor's supplied `neha.palak_ug2023@10.1.4.95`. This is for the instructor's authorized connection; do not distribute account passwords to the class. Other accounts can be selected with `-User` and `-Host`. Students can instead receive the completed reduced files or use a class folder in Drive.

The synchronizer requires the existing verified OpenSSH host-key entry. Your successful native SSH login normally establishes it. It prompts privately for a password, or supports an existing SSH key/agent. It does not change your other account's SSH configuration. It downloads manifest-listed completed `.nc` files to temporary names, checks sizes, publishes them atomically, and updates the local manifest.

In a second permitted PowerShell session in the same kit folder:

```powershell
.\run_windows.ps1 -Data "$env:USERPROFILE\Downloads\WRF_Data\full" -Output "$env:USERPROFILE\Downloads\WRF_Plots" -Watch
```

Open `WRF_Plots/index.html` and reload after each processing pass. The downloader and plotter poll once a minute by default. They finish when the conversion is complete and the available files have been handled, or stop after the configured idle timeout. Ctrl+C stops them; rerunning resumes completed work. Change `-IdleMinutes` for a long conversion.

**There is no need to wait for the final TAR files.** The watcher uses completed NetCDF snapshots directly. It can finish available figures while later snapshots are still converting, and adds those later times when they arrive. It cannot draw future data before those files exist.

For a completed local folder, omit `-Watch`. For a quick data check:

```powershell
.\run_windows.ps1 -Inspect -Data "$env:USERPROFILE\Downloads\WRF_Data\full"
```

## 4. What is produced

The default run makes the following outputs, using all available cases and times:

| Folder/file | Contents |
|---|---|
| `index.html` | Local browsable gallery; no internet connection or web server required |
| `maps/<mode>/<case>/*.gif` | One India-view animation per field, case and input mode: twenty primary fields plus wind speed and three rain rates |
| `city_timeseries/<mode>/*.png` | One figure per field with ten city panels; experiment curves share axes |
| `city_vertical/<city>/*.png` | For each of six full-level fields: time–height panels and three-dimensional time–height–concentration surfaces across the experiments |
| `profile_animations/*.gif` | Six animations of native vertical profiles across all ten cities; comparisons use shared actual timestamps |
| `tables/city_timeseries_<mode>.csv` | Native and displayed values, units, actual UTC timestamps, selected grid coordinates and distance, sampling status, and interval duration |
| `tables/city_profiles_<mode>.csv.gz` | Every retained city-column level, native and displayed concentrations, height AGL and pressure when available; gzip-compressed CSV |
| `data_status.json` | Completion, data coverage, missing inputs, and processing warnings |
| `effective_config.json` | The exact display configuration used |

The 3D figures' axes are **elapsed time, height above ground, and field value** at a city's model column. They do not claim a resolved three-dimensional city plume or a full horizontal 3D volume. The native full profiles remain in the CSV even above the default plotted 8 km height. Set `max_plot_height_m` and `height_grid_m` in the configuration to view a different height range.

If height support is missing, the kit reports that physical-height graphics are unavailable and preserves the native values by model-level index in the profile table. It does not manufacture heights. Cities outside the grid are explicitly marked as unavailable; no distant boundary-cell substitution occurs.

### Twenty primary fields

```text
T2 Q2 PSFC U10 V10 TSK PBLH HFX LH SWDOWN GLW
RAINC RAINNC GRDFLX PM2_5_DRY PM10 TOT_DUST BC1 so2 OC1
```

The derived products are `WIND_SPEED`, `RAINC_RATE`, `RAINNC_RATE`, and `RAIN_RATE`. This kit matches the corrected field list inspected in the instructor's files. It does not request the absent `o3`, `no2`, or `co` variables.

## 5. Scales and scientific meaning

Maps use the same fixed legend across cases and times. Examples are PM2.5 **0–400 µg/m³**, wind speed **0–25 m/s**, and signed `U10`/`V10` components **−25 to +25 m/s**. Out-of-range values receive a distinct color and are counted in the map footer; numerical CSV values are not clipped. Time-series axes are shared across the ten cities and expand if an actual extreme exceeds the display window.

Rain-rate maps have seven color intervals:

```text
0–0.1, 0.1–0.5, 0.5–1, 1–2, 2–5, 5–10, 10–15 mm/hour
```

They use differences of the cumulative rain fields divided by the actual elapsed hours. A 3-hour pair gives a **preceding-three-hour average**, not a measured hourly peak. The first frame is unavailable. Resets, changed simulation origins, changing grids, and unknown bucket increments are not converted into zero rainfall. Native `RAINC`/`RAINNC` accumulator plots in millimetres are retained separately.

`so2` converts from the observed ppmv to ppbv. BC1/OC1 retain **µg/kg dry air** and represent individual components. The 0–400 PM2.5 scale is a concentration display, not an AQI calculation. The full unit/range table and primary-source explanations are in [SCIENCE.md](SCIENCE.md).

Edit `config.json` for a class-wide change, or pass a separate override JSON through `-Config` / `--config`. All students should use the same override for comparisons. Fixed ranges are configurable teaching choices, not universal bounds for India.

## 6. Ten-city selection

The reproducible ranking uses **Census 2011 final urban agglomerations and standalone cities**, not a mixture of current population estimates. The order is Mumbai, Delhi, Kolkata, Chennai, Bengaluru, Hyderabad, Ahmedabad, Pune, Surat, and Jaipur. Jaipur is the municipal-corporation entry; the other nine are urban agglomerations.

`cities.csv` includes the population, unit definition, point coordinate and source for each. Nine reference points are documented IMD station locations; Surat uses its district government's published city location. Extraction is the nearest in-domain model grid cell to that point, not an urban population-weighted average or an observation.

## 7. Equivalent Colab notebook

Upload `WRF_Classroom_Colab.ipynb` at <https://colab.research.google.com/>. The notebook then asks for the kit ZIP and runs the same Python engine. Use `DATA_SOURCE = 'demo'` immediately, a small pilot upload, or a mounted Drive folder containing completed real NetCDF files and their manifests. No Conda installation is needed inside Colab; its existing runtime installs the declared Python dependencies.

**Hosted Colab cannot directly reach the private campus address `10.1.4.95`.** Stage the completed files through your laptop into Drive, or upload a small pilot. For live processing, a Drive folder must actually receive new completed files; the notebook's watcher monitors that folder. Save results under Drive if they must survive a runtime restart. Standard Colab runtime limits still apply.

## 8. Export results for students or hosting

The gallery uses relative links, so `index.html`, maps, city plots, profile GIFs, and tables can be hosted together as static files. The kit does not publish them to an external website automatically.

Package only the current results, excluding temporary rendering caches:

```bash
python wrf_classroom.py package --output /path/to/WRF_Plots --archive /path/to/WRF_Results.zip
```

On Windows, in the kit folder after setup:

```powershell
$runtime = Get-Content .\.runtime.json -Raw | ConvertFrom-Json
& $runtime.conda run --no-capture-output --prefix $runtime.prefix python .\wrf_classroom.py package --output "$env:USERPROFILE\Downloads\WRF_Plots" --archive "$env:USERPROFILE\Downloads\WRF_Results.zip"
```

Rendered PNG/GIF frames also consume disk space. Process one variant when it supplies all needed outputs. The hidden working cache enables resume and can be removed after final packaging when it is no longer needed; removing it causes future rendering to be repeated. Do not run two plotting processes against the same output directory.

## Validation and limitations

See [VALIDATION.md](VALIDATION.md) for the checks performed on synthetic input. The reader uses one snapshot at a time and reads city columns without loading entire 3D histories. Graphics need a CPU, not a GPU or WRF compilation. Initial dependency installation needs internet access.

The actual HPC files were not directly available during kit construction. Full native Windows/macOS setup and an authenticated HPC transfer were not executed in the development environment. The scripts check paths, units, manifests and host keys and report specific problems; unsupported hardware, institutional policies, missing source fields or unavailable networks still require attention. Confirm the first real pilot before distributing final scientific figures.
