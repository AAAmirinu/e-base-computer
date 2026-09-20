param(
    [ValidateSet('Start', 'Resume', 'RunOnce', 'Status', 'Stop', 'StopAndWait', 'Drain')]
    [string]$Action = 'Status',
    [string]$RunRoot = (Join-Path $PSScriptRoot '../../.ai/devin-fleet-run'),
    [ValidateNotNullOrEmpty()]
    [string]$RetryRole
)
$ErrorActionPreference = 'Stop'
if ($PSBoundParameters.ContainsKey('RetryRole') -and $Action -ne 'Resume') {
    throw '-RetryRole is valid only with Resume. It clears a role hold; it does not grant permissions.'
}
$fleetRoot = (Resolve-Path -LiteralPath $RunRoot).Path
$fleetSettings = Get-Content -LiteralPath (Join-Path $fleetRoot 'settings.json') -Raw | ConvertFrom-Json
$fleetScript = Join-Path $PSScriptRoot 'fleet.py'

function Invoke-Fleet {
    param([string[]]$FleetArguments)
    & $fleetSettings.python $fleetScript @FleetArguments
    if ($LASTEXITCODE -ne 0) {
        throw ('Fleet command failed with exit code ' + $LASTEXITCODE + ': ' + $FleetArguments[0])
    }
}

function Start-FleetBackground {
    $fleetArgs = '"' + $fleetScript + '" run --root "' + $fleetRoot + '" --cycles 0'
    $fleetStamp = (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + [Guid]::NewGuid().ToString('N')
    $fleetOutputLog = Join-Path $fleetRoot ($fleetStamp + '-runner.log')
    $fleetErrorLog = Join-Path $fleetRoot ($fleetStamp + '-runner-error.log')
    $fleetProcess = Start-Process -FilePath $fleetSettings.python -ArgumentList $fleetArgs `
        -WorkingDirectory $fleetRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $fleetOutputLog -RedirectStandardError $fleetErrorLog
    Write-Output ('Launched runner PID ' + $fleetProcess.Id + '. Use Status to verify its process lock and startup result.')
    Write-Output ('Output log: ' + $fleetOutputLog)
    Write-Output ('Error log: ' + $fleetErrorLog)
}

switch ($Action) {
    'Status' {
        Invoke-Fleet -FleetArguments @('status', '--root', $fleetRoot)
    }
    'Stop' {
        Invoke-Fleet -FleetArguments @('stop', '--root', $fleetRoot)
    }
    'StopAndWait' {
        Invoke-Fleet -FleetArguments @('stop', '--root', $fleetRoot)
        $fleetWait = [System.Diagnostics.Stopwatch]::StartNew()
        do {
            $fleetStatusJson = Invoke-Fleet -FleetArguments @('status', '--root', $fleetRoot)
            $fleetStatus = ($fleetStatusJson -join [Environment]::NewLine) | ConvertFrom-Json
            if ($fleetStatus.runner_lock_held -isnot [bool]) {
                throw 'Status did not include a boolean runner_lock_held; stop confirmation is unavailable.'
            }
            if (-not $fleetStatus.runner_lock_held) {
                Write-Output 'Runner lock released. STOP remains set; use Resume after inspecting Status.'
                break
            }
            if ($fleetWait.Elapsed.TotalSeconds -ge 60) {
                throw 'Stop requested, but runner lock remained held for 60 seconds. STOP remains set. Inspect Status and logs; no process was forcibly killed.'
            }
            Start-Sleep -Milliseconds 500
        } while ($true)
    }
    'Drain' {
        Invoke-Fleet -FleetArguments @('drain', '--root', $fleetRoot)
    }
    'RunOnce' {
        Invoke-Fleet -FleetArguments @('prepare', '--root', $fleetRoot)
        Invoke-Fleet -FleetArguments @('run', '--root', $fleetRoot, '--cycles', '1')
    }
    'Start' {
        Invoke-Fleet -FleetArguments @('prepare', '--root', $fleetRoot)
        Start-FleetBackground
    }
    'Resume' {
        $fleetPrepareArgs = @('prepare', '--root', $fleetRoot, '--resume')
        if ($PSBoundParameters.ContainsKey('RetryRole')) {
            $fleetPrepareArgs += @('--retry-role', $RetryRole)
        }
        Invoke-Fleet -FleetArguments $fleetPrepareArgs
        Start-FleetBackground
    }
}
