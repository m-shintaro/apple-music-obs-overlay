[CmdletBinding()]
param(
    [string]$PythonExe = "",
    [string]$PythonVersion = "-3",
    [switch]$SkipTests,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$VenvDir = Join-Path $RootDir ".venv-build"
$SpecPath = Join-Path $RootDir "packaging\windows\OBSAppleMusicProgressBar.spec"
$ReadmePath = Join-Path $RootDir "packaging\windows\README.txt"
$DistDir = Join-Path $RootDir "dist\OBSAppleMusicProgressBar"
$BuildDir = Join-Path $RootDir "build"

function New-BuildVenv {
    if (Test-Path $VenvDir) {
        return
    }

    if ($PythonExe) {
        & $PythonExe -m venv $VenvDir
        Assert-LastExitCode "Creating virtual environment with $PythonExe"
        return
    }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        & py $PythonVersion -m venv $VenvDir
        if ($LASTEXITCODE -eq 0) {
            return
        }
        Write-Warning "py $PythonVersion could not create the virtual environment; falling back to python."
    }

    $python = Get-Command python -ErrorAction Stop
    & $python.Source -m venv $VenvDir
    Assert-LastExitCode "Creating virtual environment with python"
}

function Assert-LastExitCode {
    param([string]$Action)

    if ($LASTEXITCODE -ne 0) {
        throw "$Action failed with exit code $LASTEXITCODE."
    }
}

function Get-ProjectVersion {
    $pyproject = Join-Path $RootDir "pyproject.toml"
    $versionLine = Select-String -Path $pyproject -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
    if (-not $versionLine) {
        throw "Could not read project version from pyproject.toml."
    }
    return $versionLine.Matches[0].Groups[1].Value
}

function Get-ArchName {
    switch ($env:PROCESSOR_ARCHITECTURE) {
        "AMD64" { return "x64" }
        "ARM64" { return "arm64" }
        "x86" { return "x86" }
        default { return $env:PROCESSOR_ARCHITECTURE.ToLowerInvariant() }
    }
}

function Compress-WithRetry {
    param(
        [string]$SourcePath,
        [string]$DestinationPath
    )

    $delaySeconds = 1
    for ($attempt = 1; $attempt -le 5; $attempt += 1) {
        try {
            Compress-Archive -Path $SourcePath -DestinationPath $DestinationPath -Force
            return
        }
        catch {
            if ($attempt -eq 5) {
                throw
            }
            Write-Warning "ZIP creation failed; retrying in $delaySeconds second(s). $($_.Exception.Message)"
            Start-Sleep -Seconds $delaySeconds
            $delaySeconds *= 2
        }
    }
}

Push-Location $RootDir
try {
    if ($Clean) {
        if (Test-Path $BuildDir) {
            Remove-Item -LiteralPath $BuildDir -Recurse -Force
        }
        if (Test-Path $DistDir) {
            Remove-Item -LiteralPath $DistDir -Recurse -Force
        }
    }

    New-BuildVenv

    $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
    $PyInstaller = Join-Path $VenvDir "Scripts\pyinstaller.exe"

    & $VenvPython -m pip install --upgrade pip
    Assert-LastExitCode "Upgrading pip"
    & $VenvPython -m pip install ".[windows]" pyinstaller
    Assert-LastExitCode "Installing build dependencies"

    if (-not $SkipTests) {
        & $VenvPython -m unittest discover tests
        Assert-LastExitCode "Running tests"
    }

    & $PyInstaller --noconfirm --clean $SpecPath
    Assert-LastExitCode "Running PyInstaller"

    if (-not (Test-Path $DistDir)) {
        throw "PyInstaller did not create $DistDir."
    }

    Copy-Item -LiteralPath $ReadmePath -Destination (Join-Path $DistDir "README.txt") -Force

    $Version = Get-ProjectVersion
    $Arch = Get-ArchName
    $ZipPath = Join-Path $RootDir "dist\OBSAppleMusicProgressBar-$Version-windows-$Arch.zip"
    if (Test-Path $ZipPath) {
        Remove-Item -LiteralPath $ZipPath -Force
    }

    Compress-WithRetry -SourcePath (Join-Path $DistDir "*") -DestinationPath $ZipPath
    Write-Host "Created $ZipPath"
}
finally {
    Pop-Location
}
