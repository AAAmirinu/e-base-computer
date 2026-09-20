param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Prepare', 'Verify')]
    [string]$Action
)

$ErrorActionPreference = 'Stop'
$ExpectedCandidate = '7721e6c83db493406ea71a3e0e965d4cdc287a13aa1679dbe67d3259d75fb682'
$Distro = 'EBase-Sandboxes'
$Launcher = '/home/fleet/controller-validation/launch_machine_auth.py'
$EvidenceRoot = Join-Path $PSScriptRoot '..\..\.ai\reboot-evidence\physical-reboot-v1'
$PrePath = Join-Path $EvidenceRoot 'pre.json'
$PostPath = Join-Path $EvidenceRoot 'post.json'

function Get-Sha256([byte[]]$Bytes) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return ([Convert]::ToHexString($sha.ComputeHash($Bytes))).ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function Get-CanonicalBytes($Value) {
    $json = $Value | ConvertTo-Json -Depth 20 -Compress
    return [System.Text.UTF8Encoding]::new($false).GetBytes($json + [Environment]::NewLine)
}

function Write-ExclusiveJson([string]$Path, $Value) {
    $bytes = Get-CanonicalBytes $Value
    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } finally { $stream.Dispose() }
}

function Get-WindowsBootUtc {
    return (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')
}

function Get-WindowsBootFileTime {
    return (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToFileTimeUtc()
}

function Get-WslBootId {
    $value = (& wsl.exe --distribution $Distro --user root --exec /bin/cat /proc/sys/kernel/random/boot_id)
    if ($LASTEXITCODE -ne 0 -or $value -notmatch '^[0-9a-f-]{36}$') {
        throw 'Unable to obtain exact dedicated-WSL boot identity'
    }
    return $value.Trim()
}

function Invoke-Readiness {
    $lines = @(& wsl.exe --distribution $Distro --user root --exec /usr/bin/python3 -E -s $Launcher --check-production-readiness)
    if ($LASTEXITCODE -ne 0) { throw 'Production readiness command failed' }
    $jsonLine = @($lines | Where-Object { $_ -match '^\{' })
    if ($jsonLine.Count -ne 1) { throw 'Exactly one readiness JSON result required' }
    $value = $jsonLine[0] | ConvertFrom-Json -Depth 20
    $roles = @($value.roles.PSObject.Properties)
    if ($value.schema -ne 1 -or $value.phase -ne 'complete' -or
        $value.candidate_sha256 -ne $ExpectedCandidate -or
        $value.role_count -ne 10 -or $roles.Count -ne 10 -or
        $value.all_vms_stopped -ne $true -or $value.network_changed -ne $false -or
        $value.model_executed -ne $false -or $value.activated -ne $false -or
        $value.activation_ready -ne $false -or
        @($roles | Where-Object {
            $_.Value.network_denied -ne $true -or $_.Value.host_boundary_verified -ne $true
        }).Count -ne 0) {
        throw 'Exact non-activating readiness result required'
    }
    return $value
}

if ($Action -eq 'Prepare') {
    if (Test-Path -LiteralPath $EvidenceRoot) {
        throw 'Existing reboot evidence requires manual inspection; overwrite is forbidden'
    }
    [void](New-Item -ItemType Directory -Path $EvidenceRoot)
    $readiness = Invoke-Readiness
    $record = [ordered]@{
        schema = 1
        phase = 'prepared'
        probe_id = [Guid]::NewGuid().ToString()
        candidate_sha256 = $ExpectedCandidate
        windows_boot_utc = Get-WindowsBootUtc
        windows_boot_filetime_utc = Get-WindowsBootFileTime
        wsl_boot_id = Get-WslBootId
        readiness_sha256 = Get-Sha256 (Get-CanonicalBytes $readiness)
        all_vms_stopped = $true
        automatic_resume = $false
        activated = $false
        published = $false
    }
    Write-ExclusiveJson $PrePath $record
    $record | ConvertTo-Json -Depth 20
    exit 0
}

if (-not (Test-Path -LiteralPath $PrePath -PathType Leaf) -or
    (Test-Path -LiteralPath $PostPath)) {
    throw 'One prepared and no completed reboot record required'
}
$preBytes = [System.IO.File]::ReadAllBytes($PrePath)
$pre = [System.Text.Encoding]::UTF8.GetString($preBytes) | ConvertFrom-Json -Depth 20
if ($pre.schema -ne 1 -or $pre.phase -ne 'prepared' -or
    $pre.candidate_sha256 -ne $ExpectedCandidate -or
    $pre.windows_boot_filetime_utc -isnot [long] -or
    $pre.all_vms_stopped -ne $true -or $pre.automatic_resume -ne $false -or
    $pre.activated -ne $false -or $pre.published -ne $false) {
    throw 'Invalid pre-reboot record'
}
$windowsBoot = Get-WindowsBootUtc
$windowsBootFileTime = Get-WindowsBootFileTime
if ($windowsBootFileTime -eq $pre.windows_boot_filetime_utc) {
    throw 'Physical Windows reboot not observed'
}
$wslBoot = Get-WslBootId
if ($wslBoot -eq $pre.wsl_boot_id) {
    throw 'Dedicated WSL reboot not observed'
}
$readiness = Invoke-Readiness
$record = [ordered]@{
    schema = 1
    phase = 'verified'
    probe_id = $pre.probe_id
    candidate_sha256 = $ExpectedCandidate
    pre_sha256 = Get-Sha256 $preBytes
    before_windows_boot_utc = $pre.windows_boot_utc
    after_windows_boot_utc = $windowsBoot
    before_windows_boot_filetime_utc = $pre.windows_boot_filetime_utc
    after_windows_boot_filetime_utc = $windowsBootFileTime
    before_wsl_boot_id = $pre.wsl_boot_id
    after_wsl_boot_id = $wslBoot
    readiness_sha256 = Get-Sha256 (Get-CanonicalBytes $readiness)
    all_vms_stopped = $true
    automatic_resume = $false
    activated = $false
    published = $false
}
Write-ExclusiveJson $PostPath $record
$record | ConvertTo-Json -Depth 20
