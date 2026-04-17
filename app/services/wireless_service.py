from __future__ import annotations

import logging
import subprocess

from app.models.network_models import NearbyAccessPoint, WirelessInfo
from app.services.oui_service import OuiService
from app.services.powershell_service import PowerShellService
from app.utils.parser import parse_netsh_wlan_networks_output, parse_netsh_wlan_output
from app.utils.process_utils import decode_windows_command_output, no_window_creationflags


class WirelessService:
    def __init__(
        self,
        powershell: PowerShellService,
        logger: logging.Logger,
        oui_service: OuiService | None = None,
    ) -> None:
        self.powershell = powershell
        self.logger = logger
        self.oui_service = oui_service

    def get_wireless_info(self) -> WirelessInfo:
        completed = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            text=False,
            creationflags=no_window_creationflags(),
        )
        raw_output = decode_windows_command_output(completed.stdout or completed.stderr)
        info = parse_netsh_wlan_output(raw_output)
        if not info.state:
            info.state = "사용 불가" if completed.returncode != 0 else "연결 안 됨"
        if not info.interface_name and info.description:
            info.interface_name = info.description
        return info

    def scan_nearby_access_points(self) -> list[NearbyAccessPoint]:
        completed = subprocess.run(
            ["netsh", "wlan", "show", "networks", "mode=bssid"],
            capture_output=True,
            text=False,
            creationflags=no_window_creationflags(),
        )
        raw_output = decode_windows_command_output(completed.stdout or completed.stderr)
        access_points = parse_netsh_wlan_networks_output(raw_output)
        if self.oui_service is not None:
            for access_point in access_points:
                access_point.vendor = self.oui_service.lookup_vendor(access_point.bssid)
        return access_points

    def list_wireless_adapters(self) -> list[str]:
        script = """
Get-NetAdapter -Physical -ErrorAction SilentlyContinue |
  Where-Object {
    $_.Name -match 'Wi-?Fi|Wireless|WLAN|802\\.11' -or
    $_.InterfaceDescription -match 'Wi-?Fi|Wireless|WLAN|802\\.11'
  } |
  Select-Object -ExpandProperty Name |
  ConvertTo-Json -Compress
"""
        data = self.powershell.run_json(script, timeout=15)
        if not data:
            return []
        if isinstance(data, str):
            return [data]
        return [str(item) for item in data]
