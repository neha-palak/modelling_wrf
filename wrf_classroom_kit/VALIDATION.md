# Validation record

Original plotting build: **18 November 2026**, engine version **1.0.0**.
Portable student workflow update: **23 November 2026**, workflow version **2**.

This record describes tests actually run during construction. The test data are synthetic. No authenticated connection to the instructor's HPC or access to the original 399 × 399 source fields was available.

## Student workflow version 2

The updated notebook supports one assigned group in Google Colab or a local VS Code notebook. Its standard-library helper discovers completed archives/datasets, streams regular TAR members into a separate work folder, preserves original metadata, and creates an explicitly scoped local manifest. The original full-export identity is retained in the NetCDF and provenance; completion in the student view refers only to selected groups.

**Thirteen new targeted tests passed:** nine discovery/extraction tests and four selected-group reporting tests. They verify single-group completeness without false warnings about unassigned groups; exact preservation of original metadata and NetCDF bytes; paths containing spaces; explicit group/mode ambiguity; matching multi-group selection; preservation of an already-extracted source manifest; reuse of completed files; interrupted extraction recovery; incomplete-file rejection; traversal/link/malformed-metadata rejection; absence of silent demo fallback; and selected-group gallery wording. Four relevant existing discovery, path-safety and CLI smoke regressions also passed.

The actual notebook cells were exercised in a local Linux test process with synthetic reducer-format input: one group TAR was discovered and prepared, all four fixture timestamps passed inspection, and a three-timestamp/four-field preview produced maps, city time series, vertical products and a results ZIP. The package contained 35 output members. The source TAR was unchanged, selected-group completion was true, and no processing errors were reported. The default `RUN_FULL = False` behavior was verified. This fixture was explicitly synthetic; it was not the original HPC weather/chemistry dataset.

Nine notebook-bootstrap checks also passed: automatic version-2 ZIP discovery and extraction, matching directory/ZIP runtime fingerprints, cache reuse, explicit ambiguity and hint handling, and rejection of traversal, symlinks, checksum mismatches, and an old kit without the version-2 helper. The notebook passed `nbformat` validation and all code cells compiled. Its import/version probe correctly rejected an installed Pillow version outside the declared constraint. The installation cell was not executed as a fresh native Windows/Colab installation. Actual Google Drive authorization/mounting and a native VS Code/Windows session were not available in this test environment. The notebook reports these prerequisites and does not claim to install or select its own initial VS Code kernel.

The one-group preview exposed clipped text in the former narrow vertical-figure layout. The layout now uses a minimum width of 11 inches and adjusted margins for a single experiment. A Delhi PM2.5 figure was regenerated from the cached synthetic preview and visually inspected at 1100 x 850 pixels; captions, axes, footer and colorbar are readable. The existing three-experiment layout is preserved.

The student handout was replaced with the assigned-group workflow and rendered to a four-page PDF for visual inspection. Earlier all-three-archive command-line examples remain available as an instructor option in README/INSTALL; they are not the default student notebook path.

## End-to-end graphics run

The actual CLI processed the bundled **24 NetCDF snapshots**: three experiments × four timestamps × two input modes. Full files contain 39 mass levels and surface files contain one. The horizontal practice grid is 30 × 30.

Command used, with the test environment's dependencies available:

```bash
python wrf_classroom.py run --data demo_data/full demo_data/surface --output TEST_OUTPUT
```

The completed status reported **24/24 records**, source complete, **zero errors and zero warnings**. The following products were verified:

| Product | Verified count |
|---|---:|
| India-view map GIFs | 144: 24 fields/products × 3 cases × 2 modes |
| Animated vertical profile GIFs | 6 |
| City time-series PNG figures | 48: 24 fields/products × 2 modes |
| City time–height / 3D PNG figures | 60: 6 vertical fields × 10 cities |
| Full city scalar table data rows | 2,880 |
| Surface city scalar table data rows | 2,880 |
| Full native-profile table data rows | 28,080 |
| Surface native-profile table data rows | 720 |

Every generated GIF contained **four frames**. PNG files were decoded for integrity. Representative precipitation and PM2.5 maps, city time series, vertical profile panels, and 3D time–height figures were visually inspected. A map footer/axis overlap and crowded city labels were corrected before the full run. Selected graphics are supplied in `examples/`, visibly marked as synthetic.

## Automated checks: 24 passed

The bundled tests use temporary synthetic files. Run them with the installed kit environment:

```bash
python -m unittest discover -s tests -v
```

The final development run passed all **24 tests**. Its checks cover:

- Native array decoding, packed data, fill values and masks.
- Full/surface discovery, actual NetCDF Times, duplicate rejection, incomplete and unsafe manifest entries.
- Out-of-domain city rejection and nearest-cell sampling.
- Physical geopotential heights, pressure, full native level preservation, and full/surface lowest-layer agreement.
- Positive rainfall differences, real elapsed intervals, missing first intervals, negative/reset masking, bucket counters and unknown bucket increments.
- Temperature, mixing-ratio, pressure and SO2 unit conversions; rejection of incompatible BC1/OC1 concentration units.
- Exactly seven rain-color bins and explicit over-range handling.
- Vertical interpolation without extrapolating below the lowest model level or across missing adjacent levels.
- Rejection of rain differences across changed grids or simulation origins.
- Cache reuse, an intermediate timestamp arriving late, and recovery after a preceding city cache was temporarily unavailable.
- GIF frame content, duration, looping and atomic publication.
- Real CLI map → GIF → numerical tables → gallery execution.
- Original input SHA256 remaining unchanged in the CLI check.
- Packaging only the current output inventory, excluding stale plots, stale tables and hidden caches.
- Fake-SFTP incremental transfer/resume, changed local-file retransmission, configuration mismatch, incomplete-source protection, traversal rejection and symlink protection.

The fake-SFTP tests use a local stand-in, not the campus server. A symlink test skips where the operating system/user cannot create symlinks.

## Installation and notebook checks

- Unix setup, launch and synchronization shell scripts passed `bash -n` syntax checks.
- Python modules compiled and their CLI help commands worked.
- The Colab notebook passed the `nbformat` schema validator; every code cell compiled.
- The Miniforge release and platform installer SHA256 digests were checked against the official release metadata; bootstrap scripts verify the pinned digest before executing a downloaded installer.
- No native Windows/macOS installer, real Conda solve on those platforms, or full Google Colab session was executed here. The notebook uses the same engine tested above.

## What to verify with the real pilot

The software was built against the instructor's posted variable names, dimensions and units. Run `inspect` on the first completed real full-level files, then a small `--max-frames 2` or `-MaxFrames 2` rendering pass. Confirm city coverage, actual grid spacing, source units, physical-height support and the intended time convention. Read any `data_status.json` notes before treating a figure as a scientific result.

The plots preserve WRF's conventionally UTC simulation timestamps; they are not relabelled with today's date or converted to IST. This historical case begins on 22 June 2023 according to the supplied sample metadata.
