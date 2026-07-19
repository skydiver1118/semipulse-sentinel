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
$TrustedPriorPackageHashes = @('017c615c077db7e173dbcc685aecb4e3d1b28d9f2f22ef1a25259f15b429f4f2','6fb15cef1ad7451b4da68bbf2f7f5d2491092a6a3482e97aae1db22bff358aad','0441ae4b5802a7aa528b313a38d1c02c7df80d0cbb6d6132023bd439d7dbe024','88b42cc493cce0060857178d59f49876a42490814b0e09a38b1a816501fff55b')
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

function Get-PackageDescriptor {
    param([Parameter(Mandatory = $true)] [string] $Root)

    Assert-NoReparseAncestors $Root
    $records = @()
    $hashMaterial = New-Object Text.StringBuilder
    foreach ($relative in $PackageFiles) {
        $path = Join-Path $Root ($relative.Replace('/', '\'))
        $item = Get-Item -LiteralPath $path -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Package file is a reparse point: $path"
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
        Files = $records
        PackageSha256 = $packageHash
        ManifestText = $manifest
    }
}

function Get-SourceDescriptor {
    param([Parameter(Mandatory = $true)] [string] $Root)

    Assert-ExactSourceTree $Root
    return Get-PackageDescriptor $Root
}

function Assert-ExactInstalledTree {
    param(
        [Parameter(Mandatory = $true)] [string] $Root,
        [Parameter(Mandatory = $true)] $Descriptor
    )

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
    $actualDescriptor = Get-PackageDescriptor $Root
    if ($actualDescriptor.PackageSha256 -cne $Descriptor.PackageSha256 -or
        $actualDescriptor.ManifestText -cne $Descriptor.ManifestText) {
        throw 'Installed files do not match the expected package hashes.'
    }
    $manifestPath = Join-Path $Root $ManifestName
    $manifestText = [IO.File]::ReadAllText($manifestPath, $Utf8NoBom)
    if ($manifestText -cne $Descriptor.ManifestText) {
        throw 'Installed manifest or file hashes do not match package content.'
    }
}

function Get-InstalledDescriptor {
    param([Parameter(Mandatory = $true)] [string] $Root)

    if (-not (Test-Path -LiteralPath (Join-Path $Root $ManifestName) -PathType Leaf)) {
        throw 'Destination exists but is not a managed SemiPulse Sentinel package.'
    }

    foreach ($relative in $PackageFiles) {
        $path = Join-Path $Root ($relative.Replace('/', '\'))
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Installed package file is missing: $relative"
        }
    }
    $descriptor = Get-PackageDescriptor $Root
    Assert-ExactInstalledTree $Root $descriptor
    return $descriptor
}

function New-StagedPackage {
    param(
        [Parameter(Mandatory = $true)] [string] $Parent,
        [Parameter(Mandatory = $true)] [string] $Source,
        [Parameter(Mandatory = $true)] $Descriptor
    )

    $stage = Join-Path $Parent ('.semipulse-sentinel.install-' + [guid]::NewGuid().ToString('N'))
    if (Test-Path -LiteralPath $stage) {
        throw 'Staging path unexpectedly exists.'
    }
    [void][IO.Directory]::CreateDirectory($stage)
    try {
        foreach ($directory in $PackageDirectories) {
            [void][IO.Directory]::CreateDirectory((Join-Path $stage $directory))
        }
        foreach ($relative in $PackageFiles) {
            $sourcePath = Join-Path $Source ($relative.Replace('/', '\'))
            $targetPath = Join-Path $stage ($relative.Replace('/', '\'))
            [IO.File]::Copy($sourcePath, $targetPath, $false)
        }
        [IO.File]::WriteAllText((Join-Path $stage $ManifestName), $Descriptor.ManifestText, $Utf8NoBom)
        Assert-ExactInstalledTree $stage $Descriptor
        return $stage
    }
    catch {
        if (Test-Path -LiteralPath $stage) {
            Remove-Item -LiteralPath $stage -Recurse -Force
        }
        throw
    }
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
$destinationParent = [IO.Path]::GetDirectoryName($destinationFull)
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$sourceRoot = Join-Path $repositoryRoot 'skill\semipulse-sentinel'
Assert-NoReparseAncestors $sourceRoot
Assert-NoReparseAncestors $destinationParent
[void][IO.Directory]::CreateDirectory($destinationParent)
Assert-NoReparseAncestors $destinationParent
$sourceDescriptor = Get-SourceDescriptor $sourceRoot

if (Test-Path -LiteralPath $destinationFull) {
    $installedDescriptor = Get-InstalledDescriptor $destinationFull
    $trustedPackageHashes = @($sourceDescriptor.PackageSha256) + $TrustedPriorPackageHashes
    if ($trustedPackageHashes -cnotcontains $installedDescriptor.PackageSha256) {
        throw 'Destination is self-consistent but is not a trusted released package.'
    }
    if ($installedDescriptor.PackageSha256 -ceq $sourceDescriptor.PackageSha256) {
        Write-Output "SemiPulse Sentinel is already installed at $destinationFull"
        return
    }
}

$stagePath = New-StagedPackage $destinationParent $sourceRoot $sourceDescriptor
$backupPath = $null
$quarantinePath = $null
$newDestinationMoved = $false
try {
    if (Test-Path -LiteralPath $destinationFull) {
        $backupPath = Join-Path $destinationParent ('.semipulse-sentinel.backup-' + [guid]::NewGuid().ToString('N'))
        [IO.Directory]::Move($destinationFull, $backupPath)
    }
    [IO.Directory]::Move($stagePath, $destinationFull)
    $newDestinationMoved = $true
    $stagePath = $null
    Assert-ExactInstalledTree $destinationFull $sourceDescriptor
}
catch {
    $installFailure = $_
    if ($newDestinationMoved -and (Test-Path -LiteralPath $destinationFull)) {
        $quarantinePath = Join-Path $destinationParent (
            '.semipulse-sentinel.failed-' + [guid]::NewGuid().ToString('N')
        )
        try {
            [IO.Directory]::Move($destinationFull, $quarantinePath)
        }
        catch {
            throw 'Install failed and the new destination could not be quarantined.'
        }
    }
    if ($null -ne $backupPath -and (Test-Path -LiteralPath $backupPath)) {
        if (Test-Path -LiteralPath $destinationFull) {
            throw 'Install failed and the canonical destination is occupied during rollback.'
        }
        Assert-ExactInstalledTree $backupPath $installedDescriptor
        [IO.Directory]::Move($backupPath, $destinationFull)
        Assert-ExactInstalledTree $destinationFull $installedDescriptor
        $backupPath = $null
    }
    if ($null -ne $quarantinePath) {
        Write-Warning "Failed new package was quarantined at $quarantinePath" -WarningAction Continue
    }
    throw $installFailure
}
finally {
    if ($null -ne $stagePath -and (Test-Path -LiteralPath $stagePath)) {
        Assert-NoReparseAncestors $stagePath
        Remove-Item -LiteralPath $stagePath -Recurse -Force
    }
}

if ($null -ne $backupPath -and (Test-Path -LiteralPath $backupPath)) {
    try {
        Assert-ExactInstalledTree $backupPath $installedDescriptor
        Remove-Item -LiteralPath $backupPath -Recurse -Force
        $backupPath = $null
    }
    catch {
        Write-Warning (
            'The new package is installed, but an old backup could not be fully removed: ' +
            $backupPath
        )
    }
}

Write-Output "Installed SemiPulse Sentinel at $destinationFull"
