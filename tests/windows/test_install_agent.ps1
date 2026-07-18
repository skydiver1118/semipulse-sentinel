Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$InstallScript = Join-Path $RepoRoot 'scripts\install-agent.ps1'
$UninstallScript = Join-Path $RepoRoot 'scripts\uninstall-agent.ps1'
$TestRoot = Join-Path ([IO.Path]::GetTempPath()) ("semipulse-agent-test-" + [guid]::NewGuid().ToString('N'))
$Destination = Join-Path $TestRoot 'codex\skills\semipulse-sentinel'
$OriginalCodexHome = $env:CODEX_HOME
$OriginalUserProfile = $env:USERPROFILE

function Assert-True {
    param(
        [Parameter(Mandatory = $true)] [bool] $Condition,
        [Parameter(Mandatory = $true)] [string] $Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

function Invoke-ExpectedFailure {
    param(
        [Parameter(Mandatory = $true)] [scriptblock] $Action,
        [Parameter(Mandatory = $true)] [string] $Message,
        [string] $Pattern
    )
    $failed = $false
    $failureMessage = ''
    try {
        & $Action
    }
    catch {
        $failed = $true
        $failureMessage = $_.Exception.Message
    }
    Assert-True $failed $Message
    if (-not [string]::IsNullOrWhiteSpace($Pattern)) {
        Assert-True ($failureMessage -match $Pattern) ("Unexpected guard message: " + $failureMessage)
    }
}

function Get-TestFileSha256 {
    param([Parameter(Mandatory = $true)] [string] $LiteralPath)
    return (Get-FileHash -LiteralPath $LiteralPath -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-TestTextSha256 {
    param([Parameter(Mandatory = $true)] [string] $Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = (New-Object Text.UTF8Encoding($false)).GetBytes($Text)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-TestDescriptor {
    param([Parameter(Mandatory = $true)] [string] $Root)
    $relativePaths = @('SKILL.md', 'agents/openai.yaml', 'references/operations.md')
    $records = @()
    $material = New-Object Text.StringBuilder
    foreach ($relative in $relativePaths) {
        $path = Join-Path $Root ($relative.Replace('/', '\'))
        $length = [IO.FileInfo]::new($path).Length
        $hash = Get-TestFileSha256 $path
        $records += [pscustomobject][ordered]@{ path = $relative; bytes = $length; sha256 = $hash }
        [void]$material.Append($relative)
        [void]$material.Append([char]0)
        [void]$material.Append([string]$length)
        [void]$material.Append([char]0)
        [void]$material.Append($hash)
        [void]$material.Append("`n")
    }
    $packageHash = Get-TestTextSha256 $material.ToString()
    $recordJson = @(
        $records | ForEach-Object {
            '{"path":"' + $_.path + '","bytes":' + $_.bytes + ',"sha256":"' + $_.sha256 + '"}'
        }
    ) -join ','
    $manifestText = '{"schema_version":1,"package":"semipulse-sentinel","files":[' +
        $recordJson + '],"package_sha256":"' + $packageHash + '"}' + "`n"
    return [pscustomobject]@{
        Files = $records
        PackageSha256 = $packageHash
        ManifestText = $manifestText
    }
}

function Write-TestManifest {
    param([Parameter(Mandatory = $true)] [string] $Root)
    $descriptor = Get-TestDescriptor $Root
    $utf8 = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText((Join-Path $Root '.semipulse-manifest.json'), $descriptor.ManifestText, $utf8)
    return $descriptor
}

function Copy-TestPackage {
    param(
        [Parameter(Mandatory = $true)] [string] $Source,
        [Parameter(Mandatory = $true)] [string] $Target
    )
    [void][IO.Directory]::CreateDirectory($Target)
    [void][IO.Directory]::CreateDirectory((Join-Path $Target 'agents'))
    [void][IO.Directory]::CreateDirectory((Join-Path $Target 'references'))
    foreach ($relative in @('SKILL.md', 'agents/openai.yaml', 'references/operations.md')) {
        [IO.File]::Copy(
            (Join-Path $Source ($relative.Replace('/', '\'))),
            (Join-Path $Target ($relative.Replace('/', '\'))),
            $false
        )
    }
}

function New-InstallerHarness {
    param(
        [Parameter(Mandatory = $true)] [string] $Name,
        [Parameter(Mandatory = $true)] [string] $TrustedHash,
        [string] $InstallerMutationPattern,
        [string] $InstallerMutationReplacement
    )
    $root = Join-Path $TestRoot $Name
    $scripts = Join-Path $root 'scripts'
    $source = Join-Path $root 'skill\semipulse-sentinel'
    [void][IO.Directory]::CreateDirectory($scripts)
    Copy-TestPackage (Join-Path $RepoRoot 'skill\semipulse-sentinel') $source
    $installerText = [IO.File]::ReadAllText($InstallScript)
    $trustPattern = '(?m)^\$TrustedPriorPackageHashes = @\((?<values>[^\r\n]*)\)$'
    $trustMatch = [regex]::Match($installerText, $trustPattern)
    Assert-True $trustMatch.Success 'trusted-hash insertion point is missing'
    $values = $trustMatch.Groups['values'].Value.Trim()
    $testValues = if ([string]::IsNullOrWhiteSpace($values)) {
        "'$TrustedHash'"
    }
    else {
        $values + ", '$TrustedHash'"
    }
    $installerText = $installerText.Remove($trustMatch.Index, $trustMatch.Length).Insert(
        $trustMatch.Index,
        ("`$TrustedPriorPackageHashes = @(" + $testValues + ')')
    )
    if (-not [string]::IsNullOrWhiteSpace($InstallerMutationPattern)) {
        $regex = New-Object Text.RegularExpressions.Regex(
            $InstallerMutationPattern,
            [Text.RegularExpressions.RegexOptions]::Multiline
        )
        Assert-True ($regex.IsMatch($installerText)) 'installer mutation point is missing'
        $installerText = $regex.Replace(
            $installerText,
            $InstallerMutationReplacement,
            1
        )
    }
    $installer = Join-Path $scripts 'install-agent.ps1'
    [IO.File]::WriteAllText($installer, $installerText, (New-Object Text.UTF8Encoding($false)))
    $uninstallerText = [IO.File]::ReadAllText($UninstallScript)
    $uninstallTrustMatch = [regex]::Match($uninstallerText, $trustPattern)
    Assert-True $uninstallTrustMatch.Success 'uninstaller trusted-hash insertion point is missing'
    $uninstallValues = $uninstallTrustMatch.Groups['values'].Value.Trim()
    $uninstallTestValues = if ([string]::IsNullOrWhiteSpace($uninstallValues)) {
        "'$TrustedHash'"
    }
    else {
        $uninstallValues + ", '$TrustedHash'"
    }
    $uninstallerText = $uninstallerText.Remove(
        $uninstallTrustMatch.Index,
        $uninstallTrustMatch.Length
    ).Insert(
        $uninstallTrustMatch.Index,
        ("`$TrustedPriorPackageHashes = @(" + $uninstallTestValues + ')')
    )
    $uninstaller = Join-Path $scripts 'uninstall-agent.ps1'
    [IO.File]::WriteAllText($uninstaller, $uninstallerText, (New-Object Text.UTF8Encoding($false)))
    return [pscustomobject]@{
        Root = $root
        Source = $source
        Installer = $installer
        Uninstaller = $uninstaller
    }
}

function New-LegacyTestPackage {
    param(
        [Parameter(Mandatory = $true)] [string] $Source,
        [Parameter(Mandatory = $true)] [string] $Destination
    )
    Copy-TestPackage $Source $Destination
    [IO.File]::AppendAllText((Join-Path $Destination 'SKILL.md'), "`nlegacy-v0")
    return Write-TestManifest $Destination
}

function Get-FileSnapshot {
    param([Parameter(Mandatory = $true)] [string] $Root)
    $snapshot = [ordered]@{}
    Get-ChildItem -LiteralPath $Root -File -Force -Recurse |
        Sort-Object FullName |
        ForEach-Object {
            $relative = $_.FullName.Substring($Root.Length).TrimStart('\').Replace('\', '/')
            $snapshot[$relative] = [Convert]::ToBase64String([IO.File]::ReadAllBytes($_.FullName))
        }
    return $snapshot
}

function Assert-SnapshotEqual {
    param(
        [Parameter(Mandatory = $true)] $Expected,
        [Parameter(Mandatory = $true)] $Actual,
        [Parameter(Mandatory = $true)] [string] $Message
    )
    $expectedJson = $Expected | ConvertTo-Json -Compress -Depth 8
    $actualJson = $Actual | ConvertTo-Json -Compress -Depth 8
    Assert-True ($expectedJson -ceq $actualJson) $Message
}

try {
    New-Item -ItemType Directory -Path $TestRoot | Out-Null

    $trustPattern = '(?m)^\$TrustedPriorPackageHashes = @\([^\r\n]*\)$'
    $installTrust = [regex]::Match([IO.File]::ReadAllText($InstallScript), $trustPattern).Value
    $uninstallTrust = [regex]::Match([IO.File]::ReadAllText($UninstallScript), $trustPattern).Value
    Assert-True (-not [string]::IsNullOrWhiteSpace($installTrust)) 'installer trust allowlist is missing'
    Assert-True ($installTrust -ceq $uninstallTrust) 'install and uninstall trust allowlists differ'

    # A test override must still use the exact package leaf and reject traversal.
    $wrongLeaf = Join-Path $TestRoot 'wrong-name'
    Invoke-ExpectedFailure {
        & $InstallScript -Destination $wrongLeaf | Out-Null
    } 'installer accepted a non-package destination leaf' 'Destination leaf'
    Invoke-ExpectedFailure {
        & $InstallScript -Destination (Join-Path $TestRoot 'x\..\semipulse-sentinel') | Out-Null
    } 'installer accepted destination traversal' 'traversal segments'
    Invoke-ExpectedFailure {
        & $UninstallScript -Destination $wrongLeaf | Out-Null
    } 'uninstaller accepted a non-package destination leaf' 'Destination leaf'
    Invoke-ExpectedFailure {
        & $UninstallScript -Destination (Join-Path $TestRoot 'x\..\semipulse-sentinel') | Out-Null
    } 'uninstaller accepted destination traversal' 'traversal segments'

    # First install must create only the immutable skill and deterministic manifest.
    & $InstallScript -Destination $Destination | Out-Null
    $expectedFiles = @(
        '.semipulse-manifest.json',
        'SKILL.md',
        'agents/openai.yaml',
        'references/operations.md'
    )
    [string[]]$actualFiles = @(
        Get-ChildItem -LiteralPath $Destination -File -Force -Recurse |
            ForEach-Object { $_.FullName.Substring($Destination.Length).TrimStart('\').Replace('\', '/') }
    )
    [Array]::Sort($actualFiles, [StringComparer]::Ordinal)
    Assert-True (($actualFiles -join "`n") -ceq ($expectedFiles -join "`n")) 'installed file tree is not exact'
    [string[]]$actualDirectories = @(
        Get-ChildItem -LiteralPath $Destination -Directory -Force -Recurse |
            ForEach-Object { $_.FullName.Substring($Destination.Length).TrimStart('\').Replace('\', '/') }
    )
    [Array]::Sort($actualDirectories, [StringComparer]::Ordinal)
    Assert-True (($actualDirectories -join "`n") -ceq "agents`nreferences") 'installed directory tree is not exact'

    $manifestPath = Join-Path $Destination '.semipulse-manifest.json'
    $manifestBytes = [IO.File]::ReadAllBytes($manifestPath)
    Assert-True ($manifestBytes.Length -gt 0) 'manifest is empty'
    Assert-True (-not ($manifestBytes.Length -ge 3 -and $manifestBytes[0] -eq 0xEF -and $manifestBytes[1] -eq 0xBB -and $manifestBytes[2] -eq 0xBF)) 'manifest has a UTF-8 BOM'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    Assert-True ($manifest.schema_version -eq 1) 'manifest schema is not version 1'
    Assert-True ($manifest.package -ceq 'semipulse-sentinel') 'manifest package is wrong'
    Assert-True ($manifest.package_sha256 -cmatch '^[0-9a-f]{64}$') 'manifest package hash is invalid'
    Assert-True (($manifest.files.path -join "`n") -ceq "SKILL.md`nagents/openai.yaml`nreferences/operations.md") 'manifest file paths are not stable and sorted'
    Assert-True (($manifest | ConvertTo-Json -Compress -Depth 8) -notmatch [regex]::Escape($TestRoot)) 'manifest leaked a machine path'
    Assert-True (($manifest | ConvertTo-Json -Compress -Depth 8) -notmatch 'timestamp|created|updated') 'manifest contains mutable time state'
    $sourceRoot = Join-Path $RepoRoot 'skill\semipulse-sentinel'
    $sourceDescriptor = Get-TestDescriptor $sourceRoot
    $installedDescriptor = Get-TestDescriptor $Destination
    Assert-True ($installedDescriptor.PackageSha256 -ceq $sourceDescriptor.PackageSha256) 'installed bytes differ from source bytes'
    Assert-True ([IO.File]::ReadAllText($manifestPath) -ceq $sourceDescriptor.ManifestText) 'manifest does not describe installed source bytes'

    # Staged bytes must be re-hashed rather than trusting the pre-copy manifest.
    $raceRepo = Join-Path $TestRoot 'race-repo'
    $raceScripts = Join-Path $raceRepo 'scripts'
    $raceSource = Join-Path $raceRepo 'skill\semipulse-sentinel'
    New-Item -ItemType Directory -Path $raceScripts, $raceSource -Force | Out-Null
    Copy-Item -LiteralPath $sourceRoot -Destination (Join-Path $raceRepo 'skill') -Recurse -Force
    $raceScript = Join-Path $raceScripts 'install-agent.ps1'
    $installerText = [IO.File]::ReadAllText($InstallScript)
    $needle = '        Assert-ExactInstalledTree $stage $Descriptor'
    Assert-True ($installerText.Contains($needle)) 'race test insertion point is missing'
    $installerText = $installerText.Replace($needle, "        Start-Sleep -Seconds 3`r`n" + $needle)
    [IO.File]::WriteAllText($raceScript, $installerText, (New-Object Text.UTF8Encoding($false)))
    $raceDestination = Join-Path $TestRoot 'race-destination\skills\semipulse-sentinel'
    $raceProcess = Start-Process powershell -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $raceScript,
        '-Destination', $raceDestination
    ) -WindowStyle Hidden -PassThru
    $raceStage = $null
    for ($attempt = 0; $attempt -lt 100 -and $null -eq $raceStage; $attempt++) {
        $candidate = Get-ChildItem -LiteralPath (Split-Path -Parent $raceDestination) -Directory -Filter '.semipulse-sentinel.install-*' -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $candidate -and (Test-Path -LiteralPath (Join-Path $candidate.FullName 'SKILL.md'))) {
            $raceStage = $candidate.FullName
            break
        }
        Start-Sleep -Milliseconds 50
    }
    Assert-True ($null -ne $raceStage) 'race test did not observe the staging package'
    [IO.File]::AppendAllText((Join-Path $raceStage 'SKILL.md'), "`nrace-change")
    if (-not $raceProcess.WaitForExit(10000)) {
        Stop-Process -Id $raceProcess.Id -Force
        throw 'staging race child process timed out'
    }
    Assert-True ($raceProcess.ExitCode -ne 0) 'installer accepted staged bytes that did not match the manifest'

    # A final-validation failure must leave no failed package at the canonical path.
    $postRaceHarness = New-InstallerHarness 'post-race-harness' $sourceDescriptor.PackageSha256 '^    Assert-ExactInstalledTree \$destinationFull \$sourceDescriptor\r?$' "    Start-Sleep -Seconds 3`r`n    Assert-ExactInstalledTree `$destinationFull `$sourceDescriptor"
    $postRaceDestination = Join-Path $TestRoot 'post-race\skills\semipulse-sentinel'
    $postRaceProcess = Start-Process powershell -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $postRaceHarness.Installer,
        '-Destination', $postRaceDestination
    ) -WindowStyle Hidden -PassThru
    for ($attempt = 0; $attempt -lt 100 -and -not (Test-Path -LiteralPath (Join-Path $postRaceDestination 'SKILL.md')); $attempt++) {
        Start-Sleep -Milliseconds 50
    }
    Assert-True (Test-Path -LiteralPath (Join-Path $postRaceDestination 'SKILL.md')) 'post-move race test did not observe the destination'
    [IO.File]::AppendAllText((Join-Path $postRaceDestination 'SKILL.md'), "`npost-move-change")
    if (-not $postRaceProcess.WaitForExit(10000)) {
        Stop-Process -Id $postRaceProcess.Id -Force
        throw 'post-move race child process timed out'
    }
    Assert-True ($postRaceProcess.ExitCode -ne 0) 'installer accepted post-move changed bytes'
    Assert-True (-not (Test-Path -LiteralPath $postRaceDestination)) 'failed fresh package remained at the canonical path'
    $freshQuarantines = @(Get-ChildItem -LiteralPath (Split-Path -Parent $postRaceDestination) -Directory -Filter '.semipulse-sentinel.failed-*')
    Assert-True ($freshQuarantines.Count -eq 1) 'failed fresh package was not bounded to one quarantine'

    # A trusted prior package upgrades through staging and a sibling backup.
    $upgradeDestination = Join-Path $TestRoot 'upgrade\skills\semipulse-sentinel'
    $legacy = New-LegacyTestPackage $sourceRoot $upgradeDestination
    $upgradeHarness = New-InstallerHarness 'upgrade-harness' $legacy.PackageSha256
    & $upgradeHarness.Installer -Destination $upgradeDestination | Out-Null
    $upgraded = Get-TestDescriptor $upgradeDestination
    Assert-True ($upgraded.PackageSha256 -ceq $sourceDescriptor.PackageSha256) 'trusted prior package was not upgraded'
    $upgradeSiblings = @(Get-ChildItem -LiteralPath (Split-Path -Parent $upgradeDestination) -Directory -Filter '.semipulse-sentinel.*-*')
    Assert-True ($upgradeSiblings.Count -eq 0) 'successful upgrade left a staging or backup directory'

    $priorUninstallDestination = Join-Path $TestRoot 'prior-uninstall\skills\semipulse-sentinel'
    [void](New-LegacyTestPackage $sourceRoot $priorUninstallDestination)
    & $upgradeHarness.Uninstaller -Destination $priorUninstallDestination | Out-Null
    Assert-True (-not (Test-Path -LiteralPath $priorUninstallDestination)) 'trusted prior package was not uninstalled'

    # A pre-commit failure restores the complete trusted prior package.
    $rollbackDestination = Join-Path $TestRoot 'rollback\skills\semipulse-sentinel'
    $rollbackLegacy = New-LegacyTestPackage $sourceRoot $rollbackDestination
    $rollbackHarness = New-InstallerHarness 'rollback-harness' $rollbackLegacy.PackageSha256 '^    Assert-ExactInstalledTree \$destinationFull \$sourceDescriptor\r?$' "    throw 'simulated pre-commit failure'"
    Invoke-ExpectedFailure {
        & $rollbackHarness.Installer -Destination $rollbackDestination -WarningAction Stop | Out-Null
    } 'installer did not surface a simulated pre-commit failure' 'simulated pre-commit failure'
    $rolledBack = Get-TestDescriptor $rollbackDestination
    Assert-True ($rolledBack.PackageSha256 -ceq $rollbackLegacy.PackageSha256) 'rollback did not restore the prior package'
    $rollbackSiblings = @(Get-ChildItem -LiteralPath (Split-Path -Parent $rollbackDestination) -Directory -Filter '.semipulse-sentinel.*-*')
    Assert-True ($rollbackSiblings.Count -eq 1) 'rollback did not retain exactly one failed-package quarantine'
    Assert-True ($rollbackSiblings[0].Name.StartsWith('.semipulse-sentinel.failed-', [StringComparison]::Ordinal)) 'rollback residue is not a failed-package quarantine'

    # Backup cleanup errors occur after commit and must not restore the old package.
    $cleanupDestination = Join-Path $TestRoot 'cleanup\skills\semipulse-sentinel'
    $cleanupLegacy = New-LegacyTestPackage $sourceRoot $cleanupDestination
    $cleanupHarness = New-InstallerHarness 'cleanup-harness' $cleanupLegacy.PackageSha256 '^        Remove-Item -LiteralPath \$backupPath -Recurse -Force\r?$' "        throw 'simulated backup cleanup failure'"
    & $cleanupHarness.Installer -Destination $cleanupDestination -WarningAction SilentlyContinue | Out-Null
    $afterCleanupFailure = Get-TestDescriptor $cleanupDestination
    Assert-True ($afterCleanupFailure.PackageSha256 -ceq $sourceDescriptor.PackageSha256) 'cleanup failure rolled back the committed package'
    $retainedBackups = @(Get-ChildItem -LiteralPath (Split-Path -Parent $cleanupDestination) -Directory -Filter '.semipulse-sentinel.backup-*')
    Assert-True ($retainedBackups.Count -eq 1) 'cleanup failure did not retain one diagnosable backup'

    $firstSnapshot = Get-FileSnapshot $Destination
    & $InstallScript -Destination $Destination | Out-Null
    $secondSnapshot = Get-FileSnapshot $Destination
    Assert-SnapshotEqual $firstSnapshot $secondSnapshot 'idempotent reinstall changed bytes'

    $originalManifest = [IO.File]::ReadAllBytes($manifestPath)
    [IO.File]::AppendAllText($manifestPath, ' ')
    Invoke-ExpectedFailure {
        & $InstallScript -Destination $Destination | Out-Null
    } 'installer accepted a modified manifest'
    Invoke-ExpectedFailure {
        & $UninstallScript -Destination $Destination | Out-Null
    } 'uninstaller accepted a modified manifest'
    [IO.File]::WriteAllBytes($manifestPath, $originalManifest)

    # A self-consistent but unrecognized package is not proof of ownership.
    $forgedDestination = Join-Path $TestRoot 'forged\skills\semipulse-sentinel'
    & $InstallScript -Destination $forgedDestination | Out-Null
    [IO.File]::AppendAllText((Join-Path $forgedDestination 'SKILL.md'), "`nforged-package")
    [void](Write-TestManifest $forgedDestination)
    Invoke-ExpectedFailure {
        & $InstallScript -Destination $forgedDestination | Out-Null
    } 'installer replaced a self-consistent unrecognized package' 'trusted released package'
    Invoke-ExpectedFailure {
        & $UninstallScript -Destination $forgedDestination | Out-Null
    } 'uninstaller removed a self-consistent unrecognized package' 'trusted released package'
    Assert-True (Test-Path -LiteralPath $forgedDestination) 'unrecognized package was deleted'

    # Unknown, extra, missing, and tampered content must be preserved and refused.
    $unknownDestination = Join-Path $TestRoot 'unknown\semipulse-sentinel'
    New-Item -ItemType Directory -Path $unknownDestination -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $unknownDestination 'owner.txt'), 'keep')
    Invoke-ExpectedFailure {
        & $InstallScript -Destination $unknownDestination | Out-Null
    } 'installer overwrote unknown destination content'
    Assert-True (Test-Path -LiteralPath (Join-Path $unknownDestination 'owner.txt')) 'unknown content was deleted'

    $extraPath = Join-Path $Destination 'extra.txt'
    [IO.File]::WriteAllText($extraPath, 'keep')
    Invoke-ExpectedFailure {
        & $InstallScript -Destination $Destination | Out-Null
    } 'installer accepted an extra file'
    Invoke-ExpectedFailure {
        & $UninstallScript -Destination $Destination | Out-Null
    } 'uninstaller accepted an extra file'
    Remove-Item -LiteralPath $extraPath -Force

    $extraDirectory = Join-Path $Destination 'extra-directory'
    New-Item -ItemType Directory -Path $extraDirectory | Out-Null
    Invoke-ExpectedFailure {
        & $InstallScript -Destination $Destination | Out-Null
    } 'installer accepted an extra directory' 'unexpected directories'
    Invoke-ExpectedFailure {
        & $UninstallScript -Destination $Destination | Out-Null
    } 'uninstaller accepted an extra directory' 'unexpected directories'
    Remove-Item -LiteralPath $extraDirectory -Force

    $skillPath = Join-Path $Destination 'SKILL.md'
    $originalSkill = [IO.File]::ReadAllBytes($skillPath)
    [IO.File]::AppendAllText($skillPath, "`ntampered")
    Invoke-ExpectedFailure {
        & $InstallScript -Destination $Destination | Out-Null
    } 'installer accepted tampered content'
    Invoke-ExpectedFailure {
        & $UninstallScript -Destination $Destination | Out-Null
    } 'uninstaller accepted tampered content'
    [IO.File]::WriteAllBytes($skillPath, $originalSkill)

    $agentPath = Join-Path $Destination 'agents\openai.yaml'
    $originalAgent = [IO.File]::ReadAllBytes($agentPath)
    Remove-Item -LiteralPath $agentPath -Force
    Invoke-ExpectedFailure {
        & $InstallScript -Destination $Destination | Out-Null
    } 'installer accepted a missing tracked file'
    [IO.File]::WriteAllBytes($agentPath, $originalAgent)

    # A reparse-point destination is never traversed or replaced.
    $reparseParent = Join-Path $TestRoot 'reparse-parent'
    $reparseTarget = Join-Path $TestRoot 'reparse-target'
    New-Item -ItemType Directory -Path $reparseParent, $reparseTarget | Out-Null
    $link = Join-Path $reparseParent 'semipulse-sentinel'
    $linkCreated = $false
    try {
        New-Item -ItemType Junction -Path $link -Target $reparseTarget -ErrorAction Stop | Out-Null
        $linkCreated = $true
    }
    catch {
        Write-Verbose 'Junction creation unavailable; reparse behavior test skipped.'
    }
    if ($linkCreated) {
        Invoke-ExpectedFailure {
            & $InstallScript -Destination $link | Out-Null
        } 'installer accepted a reparse-point destination'
        Invoke-ExpectedFailure {
            & $UninstallScript -Destination $link | Out-Null
        } 'uninstaller accepted a reparse-point destination'
        Assert-True (Test-Path -LiteralPath $reparseTarget) 'reparse target was removed'
    }

    # Clean uninstall removes exactly the verified package, and a second is a no-op.
    & $UninstallScript -Destination $Destination | Out-Null
    Assert-True (-not (Test-Path -LiteralPath $Destination)) 'clean uninstall left the package directory'
    & $UninstallScript -Destination $Destination | Out-Null

    # Default resolution prefers CODEX_HOME and never falls through to USERPROFILE.
    $env:CODEX_HOME = Join-Path $TestRoot 'default-codex-home'
    $env:USERPROFILE = Join-Path $TestRoot 'default-user-profile'
    $defaultDestination = Join-Path $env:CODEX_HOME 'skills\semipulse-sentinel'
    $wrongDefault = Join-Path $env:USERPROFILE '.codex\skills\semipulse-sentinel'
    & $InstallScript | Out-Null
    Assert-True (Test-Path -LiteralPath $defaultDestination) 'default install ignored CODEX_HOME'
    Assert-True (-not (Test-Path -LiteralPath $wrongDefault)) 'default install wrote under USERPROFILE despite CODEX_HOME'
    & $UninstallScript | Out-Null
    Assert-True (-not (Test-Path -LiteralPath $defaultDestination)) 'default uninstall left the package directory'

    $env:CODEX_HOME = $null
    $userDefault = Join-Path $env:USERPROFILE '.codex\skills\semipulse-sentinel'
    & $InstallScript | Out-Null
    Assert-True (Test-Path -LiteralPath $userDefault) 'USERPROFILE fallback install failed'
    & $UninstallScript | Out-Null
    Assert-True (-not (Test-Path -LiteralPath $userDefault)) 'USERPROFILE fallback uninstall failed'

    Write-Output 'SemiPulse Sentinel installer acceptance passed.'
}
finally {
    $env:CODEX_HOME = $OriginalCodexHome
    $env:USERPROFILE = $OriginalUserProfile
    if (Test-Path -LiteralPath $TestRoot) {
        Remove-Item -LiteralPath $TestRoot -Recurse -Force
    }
}
