from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class NetworkAdapterInfo:
    name: str
    interface_description: str
    mac_address: str
    status: str
    link_speed: str = ""
    interface_index: int = 0
    ipv4: str = ""
    prefix_length: int | None = None
    gateway: str = ""
    dns_servers: list[str] = field(default_factory=list)
    dhcp_enabled: bool = False
    interface_type: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "NetworkAdapterInfo":
        dns_servers = data.get("DNS") or data.get("Dns") or data.get("dns_servers") or []
        if isinstance(dns_servers, str):
            dns_servers = [item.strip() for item in dns_servers.split(",") if item.strip()]
        return cls(
            name=data.get("Name", ""),
            interface_description=data.get("InterfaceDescription", ""),
            mac_address=data.get("MacAddress", ""),
            status=data.get("Status", ""),
            link_speed=data.get("LinkSpeed", ""),
            interface_index=int(data.get("InterfaceIndex", 0) or 0),
            ipv4=data.get("IPv4", "") or "",
            prefix_length=int(data["PrefixLength"]) if data.get("PrefixLength") else None,
            gateway=data.get("Gateway", "") or "",
            dns_servers=list(dns_servers),
            dhcp_enabled=bool(data.get("DhcpEnabled", False)),
            interface_type=data.get("InterfaceType", "") or "",
        )

    def dns_text(self) -> str:
        return ", ".join(self.dns_servers)


@dataclass(slots=True)
class WirelessInfo:
    interface_name: str = ""
    description: str = ""
    state: str = ""
    ssid: str = ""
    bssid: str = ""
    radio_type: str = ""
    channel: str = ""
    band: str = ""
    signal_percent: int | None = None
    rssi: str = ""
    receive_rate_mbps: str = ""
    transmit_rate_mbps: str = ""
    raw_output: str = ""
    parser_message: str = ""

    @property
    def signal_text(self) -> str:
        if self.signal_percent is not None and self.rssi:
            return f"{self.signal_percent}% / {self.rssi} dBm"
        if self.signal_percent is not None:
            return f"{self.signal_percent}%"
        if self.rssi:
            return f"{self.rssi} dBm"
        return "-"
