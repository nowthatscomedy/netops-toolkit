from __future__ import annotations

from types import SimpleNamespace

from app.models.network_models import NetworkAdapterInfo, OuiRecord, PublicIperfServer
from app.models.result_models import OperationResult
from app.ui.tabs.diagnostics_tab import DiagnosticsTab


class SyncThreadPool:
    def start(self, worker) -> None:
        worker.run()


class FakeNetworkInterfaceService:
    def list_adapters(self):
        return [
            NetworkAdapterInfo(
                name="Ethernet",
                interface_description="Intel Ethernet",
                mac_address="00-11-22-33-44-55",
                status="Up",
                ipv4="192.168.0.10",
                prefix_length=24,
            )
        ]

    def format_adapter_snapshot(self, adapters) -> str:
        return f"{len(adapters)} adapters"


class FakeArpScanService:
    def list_candidate_subnets(self, adapters):
        return [("Ethernet - 192.168.0.0/24", "192.168.0.0/24")]

    def run_scan(self, *args, **kwargs):
        return OperationResult(True, "scan complete", payload=[])


class FakeOuiService:
    def cache_summary(self) -> str:
        return "로컬 캐시 1건"

    def split_label_and_mac(self, value: str):
        if "," in value:
            name, mac = [part.strip() for part in value.split(",", 1)]
            return name, mac
        return value, value

    def normalize_mac(self, mac_address: str) -> str:
        return "".join(ch for ch in mac_address.upper() if ch in "0123456789ABCDEF")

    def lookup(self, mac_address: str):
        normalized = self.normalize_mac(mac_address)
        if len(normalized) >= 6:
            return OuiRecord(prefix=normalized[:6], prefix_bits=24, organization="Vendor", registry="MA-L")
        return None

    def refresh_cache(self, *args, **kwargs):
        return OperationResult(True, "cache refreshed")


class FakeDnsService:
    def lookup(self, *args, **kwargs):
        return OperationResult(True, "dns ok", "details")

    def flush_dns_cache(self):
        return OperationResult(True, "flush ok")


class FakeTraceService:
    def run_tracert(self, *args, **kwargs):
        return OperationResult(True, "trace ok")

    def run_pathping(self, *args, **kwargs):
        return OperationResult(True, "pathping ok")

    def run_ipconfig_all(self):
        return OperationResult(True, "ipconfig", "details")

    def run_route_print(self):
        return OperationResult(True, "route", "details")

    def run_arp_table(self):
        return OperationResult(True, "arp", "details")


class FakeIperfService:
    def executable_details(self):
        return (None, "")

    def managed_install_state(self):
        return {
            "available": False,
            "installed": False,
            "update_available": False,
            "button_enabled": False,
            "action_label": "winget 없음",
            "package_id": "fake.iperf3",
            "package_url": "https://example.com",
        }

    def executable_version(self, executable_path=None):
        return None

    def managed_package_page(self):
        return "https://example.com"

    def install_or_update_managed(self, *args, **kwargs):
        return OperationResult(True, "install ok")

    def run_test(self, *args, **kwargs):
        return OperationResult(True, "iperf ok")


class FakePublicIperfService:
    def __init__(self):
        self.server = PublicIperfServer(
            name="Seoul",
            host="iperf.example.com",
            port_spec="5201",
            default_port=5201,
            region="asia",
            site="Seoul",
            country_code="KR",
        )

    def load_cached_servers(self):
        return OperationResult(
            True,
            "cached",
            payload={
                "servers": [self.server],
                "fetched_at": "2026-04-18T00:00:00Z",
                "from_cache": True,
                "stale": False,
            },
        )

    def fetch_public_servers(self, force_refresh: bool = False):
        return OperationResult(
            True,
            "fetched",
            payload={
                "servers": [self.server],
                "fetched_at": "2026-04-18T00:00:00Z",
                "from_cache": False,
                "stale": False,
            },
        )


def build_fake_state(tmp_path):
    return SimpleNamespace(
        thread_pool=SyncThreadPool(),
        app_config={
            "default_ping_count": 4,
            "default_ping_timeout_ms": 4000,
            "default_ping_workers": 8,
            "default_tcp_timeout_ms": 1000,
            "default_tcp_workers": 32,
        },
        paths=SimpleNamespace(exports_dir=tmp_path),
        network_interface_service=FakeNetworkInterfaceService(),
        arp_scan_service=FakeArpScanService(),
        oui_service=FakeOuiService(),
        dns_service=FakeDnsService(),
        trace_service=FakeTraceService(),
        iperf_service=FakeIperfService(),
        public_iperf_service=FakePublicIperfService(),
        ping_service=SimpleNamespace(),
        tcp_check_service=SimpleNamespace(),
    )


def test_diagnostics_state_save_and_restore_shape(qapp, tmp_path):
    state = build_fake_state(tmp_path)
    tab = DiagnosticsTab(state)

    tab.subnet_calc_ip_edit.setText("192.168.0.10")
    tab.subnet_calc_prefix_edit.setText("24")
    tab.arp_subnet_edit.setText("192.168.0.0/24")
    tab.arp_timeout_edit.setText("900")
    tab.arp_workers_edit.setText("10")
    tab.oui_mac_edit.setPlainText("AP,00:11:22:33:44:55")
    tab.ping_targets_edit.setPlainText("GW,192.168.0.1")
    tab.tcp_targets_edit.setPlainText("GW,192.168.0.1")
    tab.tcp_ports_edit.setText("443")
    tab.dns_query_edit.setText("example.com")
    tab.trace_target_edit.setText("8.8.8.8")
    tab.iperf_use_public_server_check.setChecked(True)
    tab.iperf_server_edit.setText("iperf.example.com")

    saved = tab.save_ui_state()

    assert set(saved) == {"current_tab", "tools", "ping", "tcp", "dns", "trace", "iperf"}
    assert saved["tools"]["version"] == 2
    assert saved["tools"]["subnet_ip"] == "192.168.0.10"
    assert saved["tools"]["oui_targets"] == "AP,00:11:22:33:44:55"
    assert saved["iperf"]["public_server_key"] == "iperf.example.com|5201"

    legacy_state = {
        "current_tab": 0,
        "tools": {
            "version": 1,
            "current_subtab": 2,
            "subnet_ip": "10.0.0.5",
            "subnet_prefix": "24",
            "arp_subnet": "10.0.0.0/24",
            "arp_timeout_ms": "700",
            "arp_workers": "5",
            "oui_mac": "Legacy,AA:BB:CC:DD:EE:FF",
        },
        "ping": {"targets": "A,1.1.1.1", "count": "5", "timeout_ms": "1000", "workers": "2", "continuous": True},
        "tcp": {
            "targets": "B,2.2.2.2",
            "ports": "80",
            "count": "3",
            "timeout_ms": "900",
            "workers": "4",
            "continuous": False,
        },
        "dns": {"query": "openai.com", "record_type": "AAAA", "server": "8.8.8.8"},
        "trace": {"target": "9.9.9.9", "no_resolve": True},
        "iperf": {
            "mode": "client",
            "use_public_server": True,
            "public_region": "asia",
            "public_server_key": "iperf.example.com|5201",
            "server": "iperf.example.com",
            "port": "5201",
            "streams": "2",
            "duration": "15",
            "reverse": True,
            "udp": False,
            "ipv6": False,
        },
    }

    tab.restore_ui_state(legacy_state)

    assert tab.tools_inner_tab.currentIndex() == 3
    assert tab.subnet_calc_ip_edit.text() == "10.0.0.5"
    assert tab.arp_subnet_edit.text() == "10.0.0.0/24"
    assert tab.oui_mac_edit.toPlainText() == "Legacy,AA:BB:CC:DD:EE:FF"
    assert tab.ping_targets_edit.toPlainText() == "A,1.1.1.1"
    assert tab.tcp_ports_edit.text() == "80"
    assert tab.dns_query_edit.text() == "openai.com"
    assert tab.trace_no_resolve_check.isChecked() is True
    assert tab.iperf_public_region_combo.currentData() == "asia"
    assert tab.iperf_public_server_combo.currentData() == "iperf.example.com|5201"

    restored_saved = tab.save_ui_state()
    assert restored_saved["tools"]["version"] == 2
    assert restored_saved["tools"]["oui_targets"] == "Legacy,AA:BB:CC:DD:EE:FF"
