from __future__ import annotations

import logging
import subprocess

from app.models.network_models import WirelessInfo
from app.services.powershell_service import PowerShellService
from app.utils.parser import parse_netsh_wlan_output
from app.utils.process_utils import no_window_creationflags, windows_console_encoding


class WirelessService:
    def __init__(self, powershell: PowerShellService, logger: logging.Logger) -> None:
        self.powershell = powershell
        self.logger = logger

    def get_wireless_info(self) -> WirelessInfo:
        completed = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=no_window_creationflags(),
        )
        raw_output = completed.stdout or completed.stderr
        info = parse_netsh_wlan_output(raw_output)
        if not info.state:
            info.state = "사용 불가" if completed.returncode != 0 else "연결 안 됨"
        if not info.interface_name and info.description:
            info.interface_name = info.description
        return info

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
