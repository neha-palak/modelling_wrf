#Requires -Version 5.1
[CmdletBinding()]
param([string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'WRFClassroom'))
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

function Test-NativeSuccess([string]$Action) {
    if ($LASTEXITCODE -ne 0) { throw "$Action failed (exit $LASTEXITCODE). Read the message above; rerun this setup after resolving it." }
}
function Find-Conda {
    $candidates = @()
    if ($env:CONDA_EXE) { $candidates += $env:CONDA_EXE }
    $cmd = Get-Command conda.exe -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
    foreach ($base in @((Join-Path $InstallRoot 'miniforge3'), (Join-Path $env:USERPROFILE 'miniforge3'), (Join-Path $env:USERPROFILE 'miniconda3'), (Join-Path $env:USERPROFILE 'anaconda3'))) {
        $candidates += (Join-Path $base 'Scripts\conda.exe')
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            & $candidate --version | Out-Host
            if ($LASTEXITCODE -eq 0) { return $candidate }
        }
    }
    return $null
}

try {
    $arch = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    if ($arch -ne 'AMD64') {
        throw 'This supported bootstrap targets 64-bit Intel/AMD Windows. For Windows ARM use the Colab notebook or a separately prepared compatible Conda environment.'
    }
    if ([Environment]::OSVersion.Version.Major -lt 10) { throw 'Windows 10 or 11 is required.' }
    $InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
    New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
    # Prefer an existing short path when a Windows user profile contains spaces.
    # All subprocess arguments are also quoted; no system PATH changes are made.
    if ($InstallRoot -match '\s|[^\x00-\x7F]') {
        try {
            $fso = New-Object -ComObject Scripting.FileSystemObject
            $shortRoot = $fso.GetFolder($InstallRoot).ShortPath
            if ($shortRoot -notmatch '\s|[^\x00-\x7F]') { $InstallRoot = $shortRoot }
        } catch { Write-Host 'Using the fully quoted installation path.' }
    }
    $conda = Find-Conda
    if (-not $conda) {
        if ($InstallRoot -match '[^\x00-\x7F]') {
            throw 'Miniforge requires a dependable ASCII installation path. Rerun with -InstallRoot pointing to a writable ASCII folder, for example a folder on your own data drive.'
        }
        $release = '26.9.4-2'
        $asset = "Miniforge3-$release-Windows-x86_64.exe"
        $expected = '9d83983669bc5d3b5dd4c631454bf953c3caf4ac78b9c9ada9971e5b021d83c3'
        $cache = Join-Path $InstallRoot 'downloads'
        New-Item -ItemType Directory -Force -Path $cache | Out-Null
        $installer = Join-Path $cache $asset
        if (-not (Test-Path -LiteralPath $installer) -or (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Write-Host "Downloading Miniforge $release from conda-forge..."
            Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/conda-forge/miniforge/releases/download/$release/$asset" -OutFile "$installer.part"
            if ((Get-FileHash -LiteralPath "$installer.part" -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
                throw 'Installer SHA256 verification failed. It was not executed. Remove the .part download and retry.'
            }
            Move-Item -LiteralPath "$installer.part" -Destination $installer -Force
        }
        $basePrefix = Join-Path $InstallRoot 'miniforge3'
        if (Test-Path -LiteralPath $basePrefix) {
            throw "An incomplete installation already exists at $basePrefix. Inspect it or choose a different -InstallRoot; setup will not delete it."
        }
        Write-Host 'Installing Miniforge for this Windows user...'
        # NSIS requires /D last and unquoted within its argument string.
        $argline = "/InstallationType=JustMe /RegisterPython=0 /AddToPath=0 /S /D=$basePrefix"
        $proc = Start-Process -FilePath $installer -ArgumentList $argline -Wait -PassThru
        if ($proc.ExitCode -ne 0) { throw "Miniforge installer exited with $($proc.ExitCode)." }
        $conda = Join-Path $basePrefix 'Scripts\conda.exe'
        if (-not (Test-Path -LiteralPath $conda)) { throw "Conda was not found at $conda after installation." }
    }

    $envPrefix = Join-Path $InstallRoot 'env-v1'
    $verb = if (Test-Path -LiteralPath (Join-Path $envPrefix 'conda-meta\history')) { 'install' } else { 'create' }
    if ((Test-Path -LiteralPath $envPrefix) -and $verb -eq 'create') {
        throw "The target $envPrefix is not a valid Conda environment. Choose another -InstallRoot; existing files will not be removed."
    }
    $specs = @('python=3.11','numpy>=1.26,<3','netcdf4>=1.6.5,<2','matplotlib>=3.8,<4','pillow>=10,<13','paramiko>=3.4,<5','pip')
    Write-Host "Preparing the classroom environment at $envPrefix..."
    & $conda $verb --yes --prefix $envPrefix --override-channels --channel conda-forge --strict-channel-priority @specs
    Test-NativeSuccess 'Environment setup'
    & $conda run --no-capture-output --prefix $envPrefix python -c "import sys,numpy,netCDF4,matplotlib,PIL,paramiko; print('Environment ready:',sys.version.split()[0]); print('NumPy',numpy.__version__,'netCDF4',netCDF4.__version__,'Matplotlib',matplotlib.__version__)"
    Test-NativeSuccess 'Dependency check'
    $runtime = @{ conda = $conda; prefix = $envPrefix; platform = 'Windows'; kit_version = '1.0.0' }
    $runtime | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot '.runtime.json') -Encoding UTF8
    & $conda list --prefix $envPrefix --explicit | Set-Content -LiteralPath (Join-Path $InstallRoot 'resolved-packages.txt') -Encoding UTF8
    Write-Host "Setup complete. Run: .\run_windows.ps1 -Data 'C:\path\to\reduced_data' -Output 'C:\path\to\plots'"
} catch {
    Write-Error $_
    exit 1
}
