[CmdletBinding()]
param(
    [string] $Destination
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$PackageName = 'semipulse-sentinel'
$ManifestName = '.semipulse-manifest.json'
$PackageFiles = @(
    'SKILL.md',
    'agents/openai.yaml',
    'references/operations.md'
)
$PackageDirectories = @('agents', 'references')
# Add exact package hashes here only after a previous version has been released.
$TrustedPriorPackageHashes = @()
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Get-NormalizedPackagePath {
    param([Parameter(Mandatory = $true)] [string] $Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw 'Destination must not be empty.'
    }
    if ([System.Management.Automation.WildcardPattern]::ContainsWildcardCharacters($Path)) {
        throw 'Destination must not contain wildcard characters.'
    }
    $segments = $Path.Replace('/', '\').Split('\')
    if ($segments -contains '.' -or $segments -contains '..') {
        throw 'Destination must not contain traversal segments.'
    }
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $root = [IO.Path]::GetPathRoot($full).TrimEnd('\', '/')
    if ($full -ceq $root) {
        throw 'Destination must not be a filesystem root.'
    }
    if ([IO.Path]::GetFileName($full) -cne $PackageName) {
        throw "Destination leaf must be '$PackageName'."
    }
    $parent = [IO.Path]::GetDirectoryName($full)
    if ([string]::IsNullOrWhiteSpace($parent) -or $parent.TrimEnd('\', '/') -ceq $root) {
        throw 'Destination must have a non-root parent directory.'
    }
    return $full
}

function Assert-NoReparseAncestors {
    param([Parameter(Mandatory = $true)] [string] $Path)

    $cursor = [IO.Path]::GetFullPath($Path)
    while (-not [string]::IsNullOrWhiteSpace($cursor)) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Reparse points are not allowed in package paths: $cursor"
            }
        }
        $parent = [IO.Path]::GetDirectoryName($cursor)
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -ceq $cursor) {
            break
        }
        $cursor = $parent
    }
}

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)] [string] $LiteralPath)

    $stream = [IO.File]::Open($LiteralPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
        $stream.Dispose()
    }
}

function Get-TextSha256 {
    param([Parameter(Mandatory = $true)] [string] $Text)

    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $Utf8NoBom.GetBytes($Text)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-PackageDescriptor {
    param([Parameter(Mandatory = $true)] [string] $Root)

    $records = @()
    $hashMaterial = New-Object Text.StringBuilder
    foreach ($relative in $PackageFiles) {
        $path = Join-Path $Root ($relative.Replace('/', '\'))
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Installed package file is missing: $relative"
        }
        $item = Get-Item -LiteralPath $path -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Installed file is a reparse point: $path"
        }
        $length = [IO.FileInfo]::new($path).Length
        $hash = Get-FileSha256 $path
        $records += [pscustomobject][ordered]@{
            path = $relative
            bytes = $length
            sha256 = $hash
        }
        [void]$hashMaterial.Append($relative)
        [void]$hashMaterial.Append([char]0)
        [void]$hashMaterial.Append([string]$length)
        [void]$hashMaterial.Append([char]0)
        [void]$hashMaterial.Append($hash)
        [void]$hashMaterial.Append("`n")
    }
    $packageHash = Get-TextSha256 $hashMaterial.ToString()
    $recordJson = @(
        $records | ForEach-Object {
            '{"path":"' + $_.path + '","bytes":' + $_.bytes + ',"sha256":"' + $_.sha256 + '"}'
        }
    ) -join ','
    $manifest = '{"schema_version":1,"package":"' + $PackageName + '","files":[' +
        $recordJson + '],"package_sha256":"' + $packageHash + '"}' + "`n"
    return [pscustomobject]@{
        PackageSha256 = $packageHash
        ManifestText = $manifest
    }
}

function Assert-ExactSourceTree {
    param([Parameter(Mandatory = $true)] [string] $Root)

    Assert-NoReparseAncestors $Root
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        throw "Skill source is missing: $Root"
    }
    [string[]]$actualFiles = @(
        Get-ChildItem -LiteralPath $Root -File -Force -Recurse | ForEach-Object {
            if (($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Source file is a reparse point: $($_.FullName)"
            }
            $_.FullName.Substring($Root.Length).TrimStart('\').Replace('\', '/')
        }
    )
    [Array]::Sort($actualFiles, [StringComparer]::Ordinal)
    [string[]]$actualDirectories = @(
        Get-ChildItem -LiteralPath $Root -Directory -Force -Recurse | ForEach-Object {
            if (($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Source directory is a reparse point: $($_.FullName)"
            }
            $_.FullName.Substring($Root.Length).TrimStart('\').Replace('\', '/')
        }
    )
    [Array]::Sort($actualDirectories, [StringComparer]::Ordinal)
    if (($actualFiles -join "`n") -cne ($PackageFiles -join "`n")) {
        throw 'Skill source contains missing or unexpected files.'
    }
    if (($actualDirectories -join "`n") -cne ($PackageDirectories -join "`n")) {
        throw 'Skill source contains missing or unexpected directories.'
    }
}

function Assert-ManagedPackage {
    param([Parameter(Mandatory = $true)] [string] $Root)

    Assert-NoReparseAncestors $Root
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        throw 'Installed package directory is missing.'
    }
    [string[]]$expectedFiles = @($ManifestName) + $PackageFiles
    [Array]::Sort($expectedFiles, [StringComparer]::Ordinal)
    [string[]]$actualFiles = @(
        Get-ChildItem -LiteralPath $Root -File -Force -Recurse | ForEach-Object {
            if (($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Installed file is a reparse point: $($_.FullName)"
            }
            $_.FullName.Substring($Root.Length).TrimStart('\').Replace('\', '/')
        }
    )
    [Array]::Sort($actualFiles, [StringComparer]::Ordinal)
    [string[]]$actualDirectories = @(
        Get-ChildItem -LiteralPath $Root -Directory -Force -Recurse | ForEach-Object {
            if (($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Installed directory is a reparse point: $($_.FullName)"
            }
            $_.FullName.Substring($Root.Length).TrimStart('\').Replace('\', '/')
        }
    )
    [Array]::Sort($actualDirectories, [StringComparer]::Ordinal)
    if (($actualFiles -join "`n") -cne ($expectedFiles -join "`n")) {
        throw 'Installed package contains missing or unexpected files.'
    }
    if (($actualDirectories -join "`n") -cne ($PackageDirectories -join "`n")) {
        throw 'Installed package contains missing or unexpected directories.'
    }
    $descriptor = Get-PackageDescriptor $Root
    $manifestPath = Join-Path $Root $ManifestName
    $manifestText = [IO.File]::ReadAllText($manifestPath, $Utf8NoBom)
    if ($manifestText -cne $descriptor.ManifestText) {
        throw 'Installed manifest or file hashes do not match package content.'
    }
    return $descriptor
}

if ([string]::IsNullOrWhiteSpace($Destination)) {
    if (-not [string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
        $Destination = Join-Path $env:CODEX_HOME 'skills\semipulse-sentinel'
    }
    elseif (-not [string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
        $Destination = Join-Path $env:USERPROFILE '.codex\skills\semipulse-sentinel'
    }
    else {
        throw 'Neither CODEX_HOME nor USERPROFILE is available.'
    }
}

$destinationFull = Get-NormalizedPackagePath $Destination
Assert-NoReparseAncestors ([IO.Path]::GetDirectoryName($destinationFull))
if (-not (Test-Path -LiteralPath $destinationFull)) {
    Write-Output "SemiPulse Sentinel is not installed at $destinationFull"
    return
}

$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$sourceRoot = Join-Path $repositoryRoot 'skill\semipulse-sentinel'
Assert-ExactSourceTree $sourceRoot
$sourceDescriptor = Get-PackageDescriptor $sourceRoot
$installedDescriptor = Assert-ManagedPackage $destinationFull
$trustedPackageHashes = @($sourceDescriptor.PackageSha256) + $TrustedPriorPackageHashes
if ($trustedPackageHashes -cnotcontains $installedDescriptor.PackageSha256) {
    throw 'Destination is self-consistent but is not a trusted released package.'
}
Assert-NoReparseAncestors $destinationFull
Remove-Item -LiteralPath $destinationFull -Recurse -Force
Write-Output "Uninstalled SemiPulse Sentinel from $destinationFull"
