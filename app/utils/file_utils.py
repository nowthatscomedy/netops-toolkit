from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_UPDATE_REPO = "nowthatscomedy/netops-toolkit"
DEFAULT_UPDATE_ASSET_PATTERN = r"NetOpsToolkit-setup.*\.exe$"


@dataclass(slots=True)
class AppPaths:
    root: Path
    data_root: Path
    config_dir: Path
    logs_dir: Path
    exports_dir: Path
    app_config: Path
    ip_profiles: Path
    vendor_presets: Path
    wifi_profiles: Path
    public_iperf_cache: Path
    oui_cache: Path
    app_log: Path


def detect_root_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resolve_asset_path(*parts: str) -> Path:
    return detect_root_path() / "assets" / Path(*parts)


def default_data_root() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "NetOps Toolkit"
    return Path.home() / "AppData" / "Local" / "NetOps Toolkit"


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False


def _is_protected_install_root(root: Path) -> bool:
    for env_name in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        base_dir = os.environ.get(env_name)
        if base_dir and _is_relative_to(root, Path(base_dir)):
            return True
    return False


def _is_writable_directory(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".netops_write_test_{os.getpid()}"
        probe.write_text("", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def detect_data_root(root: Path) -> Path:
    if _is_protected_install_root(root):
        return default_data_root()
    if _is_writable_directory(root):
        return root
    return default_data_root()


def build_app_paths(root_dir: Path | None = None) -> AppPaths:
    root = Path(root_dir) if root_dir else detect_root_path()
    data_root = detect_data_root(root)
    config_dir = data_root / "config"
    logs_dir = data_root / "logs"
    exports_dir = logs_dir / "exports"
    return AppPaths(
        root=root,
        data_root=data_root,
        config_dir=config_dir,
        logs_dir=logs_dir,
        exports_dir=exports_dir,
        app_config=config_dir / "app_config.json",
        ip_profiles=config_dir / "ip_profiles.json",
        vendor_presets=config_dir / "vendor_presets.json",
        wifi_profiles=config_dir / "wifi_profiles.json",
        public_iperf_cache=config_dir / "public_iperf_servers_cache.json",
        oui_cache=config_dir / "oui_cache.json",
        app_log=logs_dir / "app.log",
    )


def default_app_config() -> dict[str, Any]:
    return {
        "app_name": "NetOps Toolkit",
        "default_ping_count": 4,
        "default_ping_timeout_ms": 4000,
        "default_ping_workers": 8,
        "default_tcp_timeout_ms": 1000,
        "default_tcp_workers": 32,
        "wireless_refresh_interval_sec": 2,
        "default_nslookup_type": "A",
        "update": default_update_config(),
    }


def default_update_config() -> dict[str, Any]:
    return {
        "github_repo": DEFAULT_UPDATE_REPO,
        "installer_asset_pattern": DEFAULT_UPDATE_ASSET_PATTERN,
        "check_on_startup": True,
        "include_prerelease": False,
        "release_channel": "stable",
    }


def normalize_update_config(update_config: Any) -> dict[str, Any]:
    config = default_update_config()
    if isinstance(update_config, dict):
        config["check_on_startup"] = bool(update_config.get("check_on_startup", config["check_on_startup"]))
        channel = str(update_config.get("release_channel", "") or "").strip().lower()
        if channel in {"stable", "prerelease"}:
            config["release_channel"] = channel
            config["include_prerelease"] = channel == "prerelease"
        else:
            # Migrate older configs to the safer stable channel by default.
            config["release_channel"] = "stable"
            config["include_prerelease"] = False
    return config


def default_ip_profiles() -> list[dict[str, Any]]:
    return [
        {
            "name": "DHCP Auto",
            "mode": "dhcp",
            "interface_name": "",
            "local_ip": "",
            "prefix": 24,
            "gateway": "",
            "dns": [],
            "target_vendor": "",
            "target_ip": "",
            "notes": "Reset selected adapter to DHCP and automatic DNS.",
        },
        {
            "name": "Lab Access 192.168.1.10/24",
            "mode": "static",
            "interface_name": "",
            "local_ip": "192.168.1.10",
            "prefix": 24,
            "gateway": "",
            "dns": ["8.8.8.8", "1.1.1.1"],
            "target_vendor": "Lab",
            "target_ip": "192.168.1.1",
            "notes": "Example profile for initial device access work.",
        },
    ]


def default_vendor_presets() -> list[dict[str, Any]]:
    return []


def default_wifi_profiles() -> list[dict[str, Any]]:
    return [
        {
            "name": "Default-like",
            "adapter_patterns": ["Wi-Fi", "Wireless", "802.11"],
            "settings": [
                {
                    "display_name": "Roaming Aggressiveness",
                    "registry_keyword": "*RoamingAggressiveness",
                    "value": "3. Medium",
                },
                {
                    "display_name": "Transmit Power",
                    "registry_keyword": "*TransmitPower",
                    "value": "5. Highest",
                },
            ],
            "notes": "Balanced baseline. Properties can vary by vendor and driver package.",
        },
        {
            "name": "Max performance test",
            "adapter_patterns": ["Wi-Fi", "Wireless", "802.11"],
            "settings": [
                {
                    "display_name": "Roaming Aggressiveness",
                    "registry_keyword": "*RoamingAggressiveness",
                    "value": "1. Lowest",
                },
                {
                    "display_name": "Transmit Power",
                    "registry_keyword": "*TransmitPower",
                    "value": "5. Highest",
                },
                {
                    "display_name": "MIMO Power Save Mode",
                    "registry_keyword": "MIMOPowerSaveMode",
                    "value": "No SMPS",
                },
            ],
            "notes": "Use for temporary throughput testing. Some property names may differ per adapter.",
        },
    ]


def ensure_runtime_files(paths: AppPaths) -> None:
    for directory in (paths.config_dir, paths.logs_dir, paths.exports_dir):
        directory.mkdir(parents=True, exist_ok=True)

    defaults = {
        paths.app_config: (default_app_config(), paths.root / "config" / "app_config.json"),
        paths.ip_profiles: (default_ip_profiles(), paths.root / "config" / "ip_profiles.json"),
        paths.vendor_presets: (default_vendor_presets(), paths.root / "config" / "vendor_presets.json"),
        paths.wifi_profiles: (default_wifi_profiles(), paths.root / "config" / "wifi_profiles.json"),
    }
    for file_path, (default_value, source_path) in defaults.items():
        if not file_path.exists():
            if source_path.exists():
                try:
                    shutil.copyfile(source_path, file_path)
                    continue
                except OSError:
                    pass
            save_json(file_path, default_value)

    gitkeep = paths.logs_dir / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.write_text("", encoding="utf-8")

    if not paths.app_log.exists():
        paths.app_log.touch()


def load_json(file_path: Path, default: Any) -> Any:
    if not file_path.exists():
        return default
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def save_json(file_path: Path, data: Any) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def timestamped_export_path(directory: Path, prefix: str, extension: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return directory / f"{prefix}_{timestamp}.{extension.lstrip('.')}"


def open_in_explorer(path: Path) -> None:
    os.startfile(str(path))
