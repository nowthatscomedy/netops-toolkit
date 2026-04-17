from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QThreadPool, Signal

from app.models.profile_models import IPProfile, WifiAdvancedProfile
from app.services.dns_service import DnsService
from app.services.iperf_service import IperfService
from app.services.logging_service import configure_logging
from app.services.network_interface_service import NetworkInterfaceService
from app.services.ping_service import PingService
from app.services.powershell_service import PowerShellService
from app.services.tcp_check_service import TcpCheckService
from app.services.trace_service import TraceService
from app.services.update_service import UpdateService
from app.services.wifi_profile_service import WifiProfileService
from app.services.wireless_service import WirelessService
from app.utils.admin import is_running_as_admin
from app.utils.file_utils import (
    AppPaths,
    build_app_paths,
    default_app_config,
    ensure_runtime_files,
    load_json,
    normalize_update_config,
    save_json,
)


class AppState(QObject):
    log_message = Signal(str)
    config_reloaded = Signal()

    def __init__(self, root_dir: Path | None = None) -> None:
        super().__init__()
        self.paths: AppPaths = build_app_paths(root_dir)
        ensure_runtime_files(self.paths)

        self.logger: logging.Logger = configure_logging(self.paths.app_log, self._emit_log_message)
        self.thread_pool = QThreadPool.globalInstance()
        self.is_admin = is_running_as_admin()

        self.app_config: dict = {}
        self.ip_profiles: list[IPProfile] = []
        self.wifi_profiles: list[WifiAdvancedProfile] = []
        self.reload_config_files()

        self.powershell_service = PowerShellService(self.logger)
        self.network_interface_service = NetworkInterfaceService(self.powershell_service, self.logger)
        self.ping_service = PingService(self.logger)
        self.tcp_check_service = TcpCheckService(self.logger)
        self.dns_service = DnsService(self.powershell_service, self.logger)
        self.trace_service = TraceService(self.logger)
        self.wireless_service = WirelessService(self.powershell_service, self.logger)
        self.iperf_service = IperfService(self.paths, self.logger)
        self.wifi_profile_service = WifiProfileService(self.powershell_service, self.logger)
        self.update_service = UpdateService(self.logger)

    def _emit_log_message(self, message: str) -> None:
        self.log_message.emit(message)

    def reload_config_files(self) -> None:
        loaded_config = load_json(self.paths.app_config, {})
        base_config = default_app_config()
        if isinstance(loaded_config, dict):
            base_config.update({key: value for key, value in loaded_config.items() if key != "update"})
            base_config["update"] = normalize_update_config(loaded_config.get("update", {}))
        self.app_config = base_config
        profiles = [IPProfile.from_dict(item) for item in load_json(self.paths.ip_profiles, [])]
        legacy_presets = load_json(self.paths.vendor_presets, [])
        migrated_legacy = bool(legacy_presets)
        existing_names = {profile.name.casefold() for profile in profiles if profile.name}
        for item in legacy_presets:
            migrated = IPProfile.from_vendor_preset_dict(item)
            if migrated.name and migrated.name.casefold() not in existing_names:
                profiles.append(migrated)
                existing_names.add(migrated.name.casefold())
        self.ip_profiles = profiles
        if migrated_legacy:
            save_json(self.paths.ip_profiles, [profile.to_dict() for profile in self.ip_profiles])
            save_json(self.paths.vendor_presets, [])
        self.wifi_profiles = [
            WifiAdvancedProfile.from_dict(item) for item in load_json(self.paths.wifi_profiles, [])
        ]
        self.config_reloaded.emit()
        if hasattr(self, "logger"):
            if migrated_legacy:
                self.logger.info("Migrated legacy vendor presets into ip_profiles.json")
            self.logger.info("Configuration reloaded from disk.")

    def save_app_config(self, config: dict) -> None:
        normalized = dict(config)
        normalized["update"] = normalize_update_config(config.get("update", {}))
        self.app_config = normalized
        save_json(self.paths.app_config, self.app_config)
        self.logger.info("Saved app_config.json")

    def get_ui_state(self) -> dict:
        ui_state = self.app_config.get("ui_state", {})
        return dict(ui_state) if isinstance(ui_state, dict) else {}

    def save_ip_profiles(self, profiles: list[IPProfile]) -> None:
        self.ip_profiles = profiles
        save_json(self.paths.ip_profiles, [profile.to_dict() for profile in self.ip_profiles])
        self.logger.info("Saved %s IP profiles.", len(self.ip_profiles))
        self.config_reloaded.emit()

    def save_wifi_profiles(self, profiles: list[WifiAdvancedProfile]) -> None:
        self.wifi_profiles = profiles
        save_json(self.paths.wifi_profiles, [profile.to_dict() for profile in self.wifi_profiles])
        self.logger.info("Saved %s Wi-Fi profiles.", len(self.wifi_profiles))
        self.config_reloaded.emit()
