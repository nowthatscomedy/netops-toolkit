from __future__ import annotations

import logging

from app.models.profile_models import WifiAdvancedProfile, WifiPropertySetting
from app.models.result_models import OperationResult
from app.services.powershell_service import PowerShellService


class WifiProfileService:
    def __init__(self, powershell: PowerShellService, logger: logging.Logger) -> None:
        self.powershell = powershell
        self.logger = logger

    def get_advanced_properties(self, adapter_name: str) -> list[dict]:
        alias = self.powershell.quote(adapter_name)
        script = f"""
Get-NetAdapterAdvancedProperty -Name {alias} -ErrorAction Stop |
  Sort-Object DisplayName |
  Select-Object DisplayName, DisplayValue, RegistryKeyword, RegistryValue |
  ConvertTo-Json -Depth 4 -Compress
"""
        data = self.powershell.run_json(script, timeout=20)
        if not data:
            return []
        if isinstance(data, dict):
            return [data]
        return list(data)

    def format_properties(self, properties: list[dict]) -> str:
        if not properties:
            return "No advanced properties found."
        return "\n".join(
            f"{item.get('DisplayName', '-')}: {item.get('DisplayValue', '-')}"
            f"  [{item.get('RegistryKeyword', '-')}]"
            for item in properties
        )

    def apply_profile(self, adapter_name: str, profile: WifiAdvancedProfile) -> OperationResult:
        properties = self.get_advanced_properties(adapter_name)
        by_display = {str(item.get("DisplayName", "")).lower(): item for item in properties}
        by_registry = {str(item.get("RegistryKeyword", "")).lower(): item for item in properties}

        applied: list[str] = []
        failed: list[str] = []

        for setting in profile.settings:
            result = self._apply_setting(adapter_name, setting, by_display, by_registry)
            if result.success:
                applied.append(result.message)
            else:
                failed.append(result.details or result.message)

        restart_result = None
        if applied:
            restart_result = self.powershell.run(
                f"Restart-NetAdapter -Name {self.powershell.quote(adapter_name)} -Confirm:$false -ErrorAction SilentlyContinue",
                timeout=45,
            )

        message = f"Applied {len(applied)} settings, {len(failed)} failed."
        details_parts = []
        if applied:
            details_parts.append("Applied:\n" + "\n".join(applied))
        if failed:
            details_parts.append("Failed:\n" + "\n".join(failed))
        if restart_result and not restart_result.success:
            details_parts.append("Adapter restart warning:\n" + (restart_result.stderr or restart_result.stdout))
        return OperationResult(bool(applied), message, "\n\n".join(details_parts))

    def _apply_setting(
        self,
        adapter_name: str,
        setting: WifiPropertySetting,
        by_display: dict[str, dict],
        by_registry: dict[str, dict],
    ) -> OperationResult:
        display_key = setting.display_name.lower()
        registry_key = setting.registry_keyword.lower()

        if display_key and display_key in by_display:
            script = (
                f"Set-NetAdapterAdvancedProperty -Name {self.powershell.quote(adapter_name)} "
                f"-DisplayName {self.powershell.quote(setting.display_name)} "
                f"-DisplayValue {self.powershell.quote(setting.value)} -NoRestart -ErrorAction Stop"
            )
        elif registry_key and registry_key in by_registry:
            script = (
                f"Set-NetAdapterAdvancedProperty -Name {self.powershell.quote(adapter_name)} "
                f"-RegistryKeyword {self.powershell.quote(setting.registry_keyword)} "
                f"-RegistryValue {self.powershell.quote(setting.value)} -NoRestart -ErrorAction Stop"
            )
        else:
            return OperationResult(
                False,
                "Property not found.",
                f"{setting.display_name or setting.registry_keyword}: property not present on adapter.",
            )

        result = self.powershell.run(script, timeout=20)
        if result.success:
            return OperationResult(True, f"{setting.display_name or setting.registry_keyword} -> {setting.value}")
        return OperationResult(
            False,
            "Failed to apply adapter property.",
            f"{setting.display_name or setting.registry_keyword}: {result.stderr or result.stdout}",
        )
