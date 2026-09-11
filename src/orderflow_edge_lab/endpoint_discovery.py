"""Credential-free discovery of remote endpoints used by DeepCharts/Volumetrica.

The module intentionally inspects only process metadata and established TCP peers. It
never reads process memory, command lines, environment variables, config files, or
credentials.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import ipaddress
import json
import socket
import subprocess
from typing import Callable, Iterable


DEFAULT_PROCESS_NAMES = ("VolumetricaBridge", "DeepChart", "DeepCharts")


@dataclass(frozen=True)
class EndpointObservation:
    process_name: str
    pid: int
    remote_address: str
    remote_port: int
    state: str
    reverse_dns: str | None
    likely_dxfeed: bool


def _safe_ip(value: str) -> str:
    """Return a normalized IP address or raise ValueError."""
    return str(ipaddress.ip_address(value.strip()))


def classify_dxfeed(hostname: str | None, remote_port: int) -> bool:
    """Conservatively label endpoints that look like dxFeed infrastructure.

    Hostname evidence is preferred. Port 7300 is treated as a weak native dxFeed
    indicator because it is used by dxFeed's public native demo service, but callers
    must not treat this classification as proof of provider identity.
    """
    host = (hostname or "").rstrip(".").lower()
    return "dxfeed" in host or remote_port == 7300


def _reverse_dns(address: str, resolver: Callable[[str], tuple] = socket.gethostbyaddr) -> str | None:
    try:
        hostname = resolver(address)[0].rstrip(".").lower()
    except (OSError, socket.herror, socket.gaierror, TimeoutError):
        return None
    return hostname or None


def normalize_rows(rows: Iterable[dict], *, resolver: Callable[[str], tuple] = socket.gethostbyaddr) -> list[EndpointObservation]:
    """Validate PowerShell rows, resolve PTR records, and de-duplicate observations."""
    observations: dict[tuple[str, int, str, int], EndpointObservation] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            process_name = str(row["ProcessName"]).strip()
            pid = int(row["PID"])
            address = _safe_ip(str(row["RemoteAddress"]))
            port = int(row["RemotePort"])
            state = str(row.get("State", "Unknown")).strip() or "Unknown"
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if not process_name or pid <= 0 or not 1 <= port <= 65535:
            continue
        hostname = _reverse_dns(address, resolver)
        item = EndpointObservation(
            process_name=process_name,
            pid=pid,
            remote_address=address,
            remote_port=port,
            state=state,
            reverse_dns=hostname,
            likely_dxfeed=classify_dxfeed(hostname, port),
        )
        observations[(process_name.lower(), pid, address, port)] = item
    return sorted(observations.values(), key=lambda x: (not x.likely_dxfeed, x.process_name.lower(), x.remote_address, x.remote_port))


def _powershell_script(process_names: tuple[str, ...]) -> str:
    quoted = ",".join("'" + name.replace("'", "''") + "'" for name in process_names)
    return rf"""
$ErrorActionPreference = 'Stop'
$names = @({quoted})
$rows = @()
foreach ($name in $names) {{
  Get-Process -Name $name -ErrorAction SilentlyContinue | ForEach-Object {{
    $proc = $_
    Get-NetTCPConnection -OwningProcess $proc.Id -State Established -ErrorAction SilentlyContinue | ForEach-Object {{
      $rows += [PSCustomObject]@{{
        ProcessName = $proc.ProcessName
        PID = $proc.Id
        RemoteAddress = $_.RemoteAddress
        RemotePort = $_.RemotePort
        State = $_.State.ToString()
      }}
    }}
  }}
}}
$rows | ConvertTo-Json -Compress
""".strip()


def discover_windows_endpoints(
    process_names: tuple[str, ...] = DEFAULT_PROCESS_NAMES,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    resolver: Callable[[str], tuple] = socket.gethostbyaddr,
) -> list[EndpointObservation]:
    """Inspect established TCP peers for known DeepCharts/Volumetrica processes."""
    if not process_names or any(not name.strip() for name in process_names):
        raise ValueError("at least one non-empty process name is required")
    completed = runner(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _powershell_script(process_names)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("endpoint discovery failed; PowerShell diagnostics were intentionally not persisted")
    raw = completed.stdout.strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("endpoint discovery returned invalid structured output") from exc
    rows = parsed if isinstance(parsed, list) else [parsed]
    return normalize_rows(rows, resolver=resolver)


def discovery_report(observations: Iterable[EndpointObservation]) -> dict:
    items = list(observations)
    return {
        "schema_version": 1,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": "windows_established_tcp_peers",
        "credential_access": False,
        "endpoint_count": len(items),
        "likely_dxfeed_count": sum(item.likely_dxfeed for item in items),
        "observations": [asdict(item) for item in items],
        "limitations": [
            "A matching hostname or port is an indicator, not cryptographic proof of provider identity.",
            "Only established TCP peers visible while the target process is running are reported.",
            "No credentials, process memory, environment variables, command lines, or config files are inspected.",
        ],
    }
