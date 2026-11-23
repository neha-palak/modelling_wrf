# Preparing the full-level input on the instructor's HPC

The plotting kit works immediately with its synthetic practice data and with any completed real snapshots. A full-level subset supports both surface and vertical figures. The observed surface pilot by itself cannot recover the discarded upper layers.

These commands are for the instructor's existing **HPC SSH session**. They reuse the installed reducer in its actual nested directory. If a full reduction already runs, let it continue; do not submit another job to the same output directory.

```bash
cd "$HOME/wrf_lite_kit/wrf_lite_kit"
conda activate wrf-lite
export WRF_LITE_PYTHON="$(python3 -c 'import sys; print(sys.executable)')"
export WRF_LITE_VARIABLES="T2,Q2,PSFC,U10,V10,TSK,PBLH,HFX,LH,SWDOWN,GLW,RAINC,RAINNC,GRDFLX,PM2_5_DRY,PM10,TOT_DUST,BC1,so2,OC1"
```

The variable list is exported as one environment variable because commas have special meaning inside `qsub -v`. The existing wrapper's `#PBS -V` passes it to the job.

To measure a full-level pilot:

```bash
qsub -q cpu -v WRF_LITE_ACTION=pilot,WRF_LITE_VERTICAL=full,WRF_LITE_PYTHON="$WRF_LITE_PYTHON" reduce_wrf.pbs
```

After that job completes successfully, inspect its summary:

```bash
OUT=/storage/neha.palak_ug2023/wrfchem/MSA_CANDIDATE_V1/134061_LITE_3H_full
python3 -m json.tool "$OUT/pilot_summary.json"
```

If it is suitable, submit the full export:

```bash
qsub -q cpu -v WRF_LITE_ACTION=reduce,WRF_LITE_VERTICAL=full,WRF_LITE_PACKAGE=1,WRF_LITE_PYTHON="$WRF_LITE_PYTHON" reduce_wrf.pbs
qstat -u "$USER"
```

The `cpu` queue was enabled and accepted the instructor's earlier pilot. Use that explicit queue rather than the disabled default `workq`. Run reduction through PBS as required by the HPC banner; the plotting kit's laptop transfer does not run remote computation.

In a local Windows PowerShell session, the new kit's `sync_windows.ps1` can copy manifest-listed completed snapshots while this job is still running. There is no need to wait for TAR packaging. The original files are read, not replaced.

The full reducer copies `P`, `PB`, `PH`, `PHB`, and other support fields **when they exist in the source**. The plotting kit checks their availability for pressure and physical height. If a real pilot lacks support, read `data_status.json` and the original source header before attempting physical-height figures.

The previously measured **869,854,237-byte projection applies only to the surface mode** and is a first-snapshot extrapolation. It is not a measured full-level download size. Use the new full pilot to measure that choice.
