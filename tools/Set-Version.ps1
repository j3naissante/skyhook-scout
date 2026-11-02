<#
.SYNOPSIS
Update the app version, release date and public documentation. Does not build or push.
.EXAMPLE
.\tools\Set-Version.ps1 1.1.1
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory, Position = 0)]
    [ValidatePattern('^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$')]
    [string]$Version
)
$ErrorActionPreference = 'Stop'
$parts = $Version.Split('.')
if ([decimal]$parts[0] -gt 255 -or [decimal]$parts[1] -gt 255 -or [decimal]$parts[2] -gt 65535) {
    throw 'Use major.minor.patch within MSI limits: 255.255.65535.'
}
$projectRoot = Split-Path -Parent $PSScriptRoot
$versionFile = Join-Path $projectRoot 'skyhook_scout/__init__.py'
$source = [IO.File]::ReadAllText($versionFile)
$match = [regex]::Match($source, '(?m)^__version__ = "([0-9]+\.[0-9]+\.[0-9]+)"\r?$')
if (-not $match.Success) { throw 'Cannot find __version__ in skyhook_scout/__init__.py.' }
$previous = $match.Groups[1].Value
if ($previous -eq $Version) {
    Write-Host "Version is already $Version; no files changed."
    return
}
$releaseDate = Get-Date -Format 'yyyy-MM-dd'
$updated = $source.Replace('__version__ = "' + $previous + '"', '__version__ = "' + $Version + '"')
if ($updated -notmatch '(?m)^__release_date__ = "[0-9-]+"\r?$') { throw 'Cannot find __release_date__.' }
$updated = [regex]::Replace($updated, '(?m)^__release_date__ = "[0-9-]+"', '__release_date__ = "' + $releaseDate + '"')
# Read and validate all inputs before changing any files.
$changes = @(@{ Path = $versionFile; Text = $updated })
foreach ($name in @('README.md', 'BUILD.md')) {
    $path = Join-Path $projectRoot $name
    $text = [IO.File]::ReadAllText($path)
    $changes += @{ Path = $path; Text = $text.Replace($previous, $Version) }
}
if ($PSCmdlet.ShouldProcess($projectRoot, "Change version $previous to $Version")) {
    $encoding = New-Object System.Text.UTF8Encoding($false)
    foreach ($change in $changes) {
        [IO.File]::WriteAllText($change.Path, $change.Text, $encoding)
    }
    Write-Host "Version updated: $previous -> $Version (release date $releaseDate)."
    Write-Host 'App, Python package and build filenames now use this version. Rebuild before uploading release files.'
}
