[CmdletBinding()]
param(
    [string[]]$ProcessName,
    [ValidateRange(1, 600)]
    [int]$DurationSeconds = 45,
    [ValidateRange(250, 10000)]
    [int]$IntervalMilliseconds = 750,
    [string]$OutputPath = "deepcharts_dxfeed_endpoints.json"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Get-CandidateProcesses {
    param([string[]]$ExplicitNames)

    if ($ExplicitNames -and $ExplicitNames.Count -gt 0) {
        $wanted = @{}
        foreach ($name in $ExplicitNames) {
            if (-not [string]::IsNullOrWhiteSpace($name)) {
                $wanted[$name.Trim().ToLowerInvariant()] = $true
            }
        }
        return @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
            $wanted.ContainsKey($_.ProcessName.ToLowerInvariant())
        })
    }

    return @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessName -match '(?i)(deepchart|deepcharts|deepdom|volumetrica|dxfeed)'
    })
}

function Resolve-ReverseDns {
    param([string]$Address)
    try {
        $entry = [System.Net.Dns]::GetHostEntry($Address)
        if ($entry -and -not [string]::IsNullOrWhiteSpace($entry.HostName)) {
            return $entry.HostName.TrimEnd('.').ToLowerInvariant()
        }
    }
    catch {
        return $null
    }
    return $null
}

function Get-Evidence {
    param([string]$HostName, [int]$RemotePort)

    $items = [System.Collections.Generic.List[string]]::new()
    if ($HostName -and $HostName -match '(?i)dxfeed') {
        $items.Add('reverse_dns_contains_dxfeed')
    }
    if ($RemotePort -eq 7300) {
        $items.Add('remote_port_7300')
    }
    if ($RemotePort -eq 443) {
        $items.Add('tls_port_443')
    }
    return @($items)
}

function Get-Confidence {
    param([string[]]$Evidence)
    if ($Evidence -contains 'reverse_dns_contains_dxfeed') { return 'high' }
    if ($Evidence -contains 'remote_port_7300') { return 'medium' }
    if ($Evidence -contains 'tls_port_443') { return 'low' }
    return 'unclassified'
}

$started = [DateTimeOffset]::UtcNow
$deadline = $started.AddSeconds($DurationSeconds)
$observed = @{}
$matchedProcessNames = @{}
$sampleCount = 0

Write-Host "Watching DeepCharts-related established TCP connections for $DurationSeconds seconds..."
Write-Host "For best isolation, disconnect and reconnect only the dxFeed connection once while this runs."

while ([DateTimeOffset]::UtcNow -lt $deadline) {
    $sampleCount++
    $processes = Get-CandidateProcesses -ExplicitNames $ProcessName

    foreach ($proc in $processes) {
        $matchedProcessNames[$proc.ProcessName] = $true
        $connections = @(Get-NetTCPConnection -OwningProcess $proc.Id -State Established -ErrorAction SilentlyContinue)
        foreach ($connection in $connections) {
            $remoteAddress = [string]$connection.RemoteAddress
            $remotePort = [int]$connection.RemotePort
            if ([string]::IsNullOrWhiteSpace($remoteAddress) -or $remotePort -lt 1 -or $remotePort -gt 65535) {
                continue
            }

            $key = "$($proc.ProcessName)|$($proc.Id)|$remoteAddress|$remotePort"
            $now = [DateTimeOffset]::UtcNow
            if (-not $observed.ContainsKey($key)) {
                $hostName = Resolve-ReverseDns -Address $remoteAddress
                $evidence = @(Get-Evidence -HostName $hostName -RemotePort $remotePort)
                $observed[$key] = [ordered]@{
                    process_name = $proc.ProcessName
                    pid = [int]$proc.Id
                    remote_address = $remoteAddress
                    remote_port = $remotePort
                    reverse_dns = $hostName
                    confidence = Get-Confidence -Evidence $evidence
                    evidence = $evidence
                    first_seen_utc = $now.ToString('o')
                    last_seen_utc = $now.ToString('o')
                    samples_seen = 1
                }
            }
            else {
                $item = $observed[$key]
                $item.last_seen_utc = $now.ToString('o')
                $item.samples_seen = [int]$item.samples_seen + 1
            }
        }
    }

    Start-Sleep -Milliseconds $IntervalMilliseconds
}

$ended = [DateTimeOffset]::UtcNow
$items = @($observed.Values | Sort-Object @{Expression={
    switch ($_.confidence) {
        'high' { 0 }
        'medium' { 1 }
        'low' { 2 }
        default { 3 }
    }
}}, process_name, remote_address, remote_port)

$report = [ordered]@{
    schema_version = 1
    method = 'powershell_established_tcp_watch'
    started_at_utc = $started.ToString('o')
    ended_at_utc = $ended.ToString('o')
    duration_seconds = $DurationSeconds
    interval_milliseconds = $IntervalMilliseconds
    sample_count = $sampleCount
    credential_access = $false
    process_memory_access = $false
    command_line_access = $false
    matched_process_names = @($matchedProcessNames.Keys | Sort-Object)
    endpoint_count = $items.Count
    observations = $items
    interpretation = @(
        'High confidence means reverse DNS explicitly contained dxfeed.',
        'Medium confidence means port 7300 was observed; this is an indicator, not proof.',
        'Low confidence means ordinary TLS port 443; correlate appearance with dxFeed reconnect timing.',
        'No credentials, process memory, command lines, environment variables, or configuration files are inspected.'
    )
}

$json = $report | ConvertTo-Json -Depth 8
$json | Set-Content -LiteralPath $OutputPath -Encoding UTF8
$json

if ($items.Count -eq 0) {
    Write-Warning "No established TCP peers were observed for matching processes."
    Write-Warning "If DeepCharts is open under a different executable name, rerun with -ProcessName <exact-process-name>."
    exit 1
}

exit 0
