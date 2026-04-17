# NetOps Toolkit

Windows 10/11 field network engineers can use this PySide6 desktop application to manage interfaces, switch between DHCP and static addressing, run multi-target diagnostics, inspect Wi-Fi link quality, and launch iperf3 from one practical GUI.

## Highlights

- Interface/IP workflow focused on real field work
  - Enumerates Windows adapters with name, description, MAC, status, IPv4, prefix, gateway, DNS, DHCP
  - Switch selected interface to DHCP
  - Apply static IPv4, gateway, and DNS
  - Save/load reusable IP profiles
- Common diagnostics
  - Multi-target ping with parallel execution and row-by-row updates
  - Multi-target / multi-port TCP checks using Python sockets
  - nslookup/Resolve-DnsName integration
  - tracert and pathping streaming output with cancel support
  - ipconfig /all, route print, arp -a, DNS flush
- Wireless operations
  - Current SSID/BSSID/channel/band/signal/rx/tx/state view
  - Periodic refresh mode
  - Change log for BSSID/channel/link changes
  - iperf3 integration if `iperf3.exe` exists in the app root
  - Wi-Fi advanced adapter profile apply flow backed by JSON
- Operational quality
  - Log file at [logs/app.log](/C:/Users/PC/Desktop/python/netops-toolkit/logs/app.log)
  - Export directory at [logs/exports](/C:/Users/PC/Desktop/python/netops-toolkit/logs/exports)
  - JSON-based configuration and presets in [config](/C:/Users/PC/Desktop/python/netops-toolkit/config)
  - Background workers to keep UI responsive
  - GitHub Releases based update check with SHA-256 verification before installer launch

## Project Structure

```text
netops-toolkit/
  main.py
  requirements.txt
  README.md
  app/
    app_state.py
    main_window.py
    models/
    services/
    ui/
      dialogs/
      tabs/
    utils/
  config/
    app_config.json
    ip_profiles.json
    vendor_presets.json
    wifi_profiles.json
  logs/
    .gitkeep
    exports/
```

## Architecture

### 1. UI layer

- [app/main_window.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/main_window.py)
  - Main window, toolbar, status bar, bottom log dock
- [app/ui/tabs/interface_tab.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/ui/tabs/interface_tab.py)
  - Interface selection, DHCP/static/DNS apply, IP profiles
- [app/ui/tabs/diagnostics_tab.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/ui/tabs/diagnostics_tab.py)
  - Multi ping, TCP check, DNS, tracert/pathping, helper commands
- [app/ui/tabs/wireless_tab.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/ui/tabs/wireless_tab.py)
  - Wi-Fi status view, auto-refresh, iperf3, advanced adapter profiles
- [app/ui/tabs/settings_tab.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/ui/tabs/settings_tab.py)
  - GitHub update settings, config/log folder shortcuts

### 2. Service layer

- [app/services/powershell_service.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/services/powershell_service.py)
  - Shared PowerShell runner with timeout, stdout/stderr separation, JSON parsing
- [app/services/network_interface_service.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/services/network_interface_service.py)
  - Adapter inventory, DHCP/static/DNS apply, `netsh` fallback
- [app/services/ping_service.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/services/ping_service.py)
  - Parallel `Test-Connection` runs and statistics
- [app/services/tcp_check_service.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/services/tcp_check_service.py)
  - Parallel TCP socket checks
- [app/services/dns_service.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/services/dns_service.py)
  - `Resolve-DnsName` + `nslookup` fallback
- [app/services/trace_service.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/services/trace_service.py)
  - Streaming `tracert`, `pathping`, and helper command execution
- [app/services/wireless_service.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/services/wireless_service.py)
  - `netsh wlan show interfaces` collection and parsing
- [app/services/iperf_service.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/services/iperf_service.py)
  - Local `iperf3.exe` process management
- [app/services/wifi_profile_service.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/services/wifi_profile_service.py)
  - Advanced adapter property read/apply flow

### 3. Shared foundations

- [app/app_state.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/app_state.py)
  - Runtime state, config loading, service wiring
- [app/utils/threading_utils.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/utils/threading_utils.py)
  - QRunnable-based background worker helper
- [app/utils/file_utils.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/utils/file_utils.py)
  - App paths, JSON defaults, export path helpers
- [app/models](/C:/Users/PC/Desktop/python/netops-toolkit/app/models)
  - Typed dataclasses for adapters, profiles, and results

## Run

### 1. Create and activate a virtual environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. Install requirements

```powershell
pip install -r requirements.txt
```

### 3. Start the application

```powershell
python main.py
```

## Packaging

### PyInstaller example

```powershell
pip install pyinstaller
pyinstaller --noconfirm --windowed --name NetOpsToolkit ^
  --add-data "config;config" ^
  --add-data "logs;logs" ^
  main.py
```

After packaging:

- Place `iperf3.exe` next to the executable if you want iperf3 integration.
- Keep the `config` folder writable so profiles and presets can be edited.

## GitHub Updates

The app can check a public GitHub repository's Releases feed and offer an update when a newer release exists.

- The updater checks the latest release tag such as `v1.0.1`.
- It looks for a release asset whose filename matches the configured regex.
- It downloads the installer only after the user confirms.
- It verifies SHA-256 before launching the installer.
- Verification prefers the GitHub Releases asset `digest` exposed by the Releases API.
- If the asset digest is unavailable, it falls back to a checksum file such as `your-installer.exe.sha256` or `SHA256SUMS.txt`.
- The app does not silently update in the background.

Recommended release structure:

- Git tag: `v1.0.1`
- Release asset: `NetOpsToolkit-setup-1.0.1.exe`
- Optional fallback checksum asset: `NetOpsToolkit-setup-1.0.1.exe.sha256`

What you need to prepare on GitHub:

- Create or choose a public repository for distribution.
- Publish GitHub Releases from version tags.
- Upload the packaged installer asset to each release.
- In the app Settings tab, set `owner/repo` and the installer filename regex.

Current limitations:

- Private repositories are not supported by the current updater flow because that would require secure token handling.
- The updater launches the installer but does not perform a silent unattended upgrade.

## Configuration Files

- [config/app_config.json](/C:/Users/PC/Desktop/python/netops-toolkit/config/app_config.json)
  - UI defaults, persisted tab state, GitHub update settings
- [config/ip_profiles.json](/C:/Users/PC/Desktop/python/netops-toolkit/config/ip_profiles.json)
  - Saved reusable IP profiles
- [config/wifi_profiles.json](/C:/Users/PC/Desktop/python/netops-toolkit/config/wifi_profiles.json)
  - Wi-Fi advanced property profiles

## Administrator Rights

The following features should be run with administrator rights:

- DHCP / static IP / gateway / DNS changes
- Wi-Fi advanced adapter property apply
- Some adapter restart operations after applying Wi-Fi profiles
- DNS flush may require elevation depending on system policy

The following features can generally run without admin:

- Interface inventory
- Multi ping
- TCP port checks
- nslookup
- tracert / pathping
- Wi-Fi status monitoring
- iperf3

Use the toolbar `Restart As Admin` action when elevation is needed.

## Notes About Wireless Parsing

`netsh wlan show interfaces` output varies by Windows language. The parser is structured around field aliases and will fall back to showing raw command output when a field cannot be parsed cleanly. That gives engineers the raw source text even if a localized system uses a different label format.

## Future Extension Points

- Customer-specific preset packs or deployment bundles
- Better Wi-Fi adapter vendor normalization by registry keyword maps
- Export reports to CSV/TXT bundles per job
- Command history and saved test sets
- Additional interface safety checks before applying IP changes
- Optional secure credential storage for customer-specific workflows
- Signed installer verification and trusted publisher policy checks
- Private GitHub Releases support with encrypted token storage

## Validation Performed

- Static compile check:

```powershell
python -m compileall main.py app
```

This confirms the current codebase is syntactically valid. GUI runtime testing still depends on the target Windows environment having PySide6 installed and the expected Windows networking cmdlets available.
