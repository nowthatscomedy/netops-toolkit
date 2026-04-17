from __future__ import annotations

import re

from app.models.network_models import WirelessInfo


def parse_target_entries(raw_text: str) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    for line in raw_text.splitlines():
        text = line.strip()
        if not text:
            continue
        if "," in text:
            name, target = [part.strip() for part in text.split(",", 1)]
            targets.append((name or target, target))
        else:
            targets.append((text, text))
    return targets


def parse_port_list(raw_text: str) -> list[int]:
    ports: list[int] = []
    for part in re.split(r"[\s,;]+", raw_text.strip()):
        if not part:
            continue

        if "-" in part:
            start_text, end_text = [token.strip() for token in part.split("-", 1)]
            if not start_text or not end_text:
                raise ValueError(f"포트 범위 형식이 올바르지 않습니다: {part}")

            start_port = int(start_text)
            end_port = int(end_text)
            if start_port > end_port:
                raise ValueError(f"포트 범위 시작값이 끝값보다 클 수 없습니다: {part}")
            if not 1 <= start_port <= 65535 or not 1 <= end_port <= 65535:
                raise ValueError(f"포트 번호는 1~65535 범위여야 합니다: {part}")

            ports.extend(range(start_port, end_port + 1))
            continue

        port = int(part)
        if not 1 <= port <= 65535:
            raise ValueError(f"포트 번호는 1~65535 범위여야 합니다: {port}")
        ports.append(port)

    if not ports:
        raise ValueError("최소 1개 이상의 포트를 입력해야 합니다.")
    return sorted(set(ports))


def band_from_channel(channel_text: str, radio_type: str = "") -> str:
    try:
        channel = int(re.findall(r"\d+", channel_text)[0])
    except (IndexError, ValueError):
        return "알 수 없음"

    if 1 <= channel <= 14:
        return "2.4 GHz"
    if 32 <= channel <= 177:
        return "5 GHz"
    if 178 <= channel <= 233:
        return "6 GHz"
    if "6" in radio_type and "ax" in radio_type.lower():
        return "6 GHz(추정)"
    return "알 수 없음"


def _normalize_label(label: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", "", label.strip().lower())


FIELD_MAP: dict[str, str] = {
    "name": "interface_name",
    "이름": "interface_name",
    "description": "description",
    "설명": "description",
    "state": "state",
    "status": "state",
    "상태": "state",
    "ssid": "ssid",
    "bssid": "bssid",
    "apbssid": "bssid",
    "radiotype": "radio_type",
    "라디오유형": "radio_type",
    "무선유형": "radio_type",
    "phytype": "radio_type",
    "물리유형": "radio_type",
    "channel": "channel",
    "채널": "channel",
    "band": "band",
    "대역": "band",
    "signal": "signal",
    "신호": "signal",
    "receiveratembps": "receive_rate_mbps",
    "receiverate": "receive_rate_mbps",
    "수신속도mbps": "receive_rate_mbps",
    "수신속도": "receive_rate_mbps",
    "transmitratembps": "transmit_rate_mbps",
    "transmitrate": "transmit_rate_mbps",
    "송신속도mbps": "transmit_rate_mbps",
    "송신속도": "transmit_rate_mbps",
    "rssi": "rssi",
}


STATE_MAP = {
    "connected": "연결됨",
    "disconnected": "연결 안 됨",
    "disconnecting": "연결 해제 중",
    "not ready": "준비 안 됨",
    "authenticating": "인증 중",
    "discovering": "검색 중",
    "associating": "연결 시도 중",
    "ad hoc network formed": "애드혹 구성됨",
}


def localize_wireless_state(value: str) -> str:
    text = value.strip()
    return STATE_MAP.get(text.lower(), text)


def parse_netsh_wlan_output(raw_output: str) -> WirelessInfo:
    info = WirelessInfo(raw_output=raw_output)
    if not raw_output.strip():
        info.parser_message = "netsh 출력이 비어 있습니다."
        return info

    lower_output = raw_output.lower()
    if "there is no wireless interface" in lower_output or "무선 인터페이스가 없습니다" in raw_output:
        info.state = "무선 어댑터 없음"
        info.parser_message = "시스템에서 무선 인터페이스를 찾지 못했습니다."
        return info

    values: dict[str, str] = {}
    for line in raw_output.splitlines():
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        field_name = FIELD_MAP.get(_normalize_label(label))
        if field_name:
            values[field_name] = value.strip()

    info.interface_name = values.get("interface_name", "")
    info.description = values.get("description", "")
    info.state = localize_wireless_state(values.get("state", ""))
    info.ssid = values.get("ssid", "")
    info.bssid = values.get("bssid", "")
    info.radio_type = values.get("radio_type", "")
    info.channel = values.get("channel", "")
    info.band = values.get("band", "") or band_from_channel(info.channel, info.radio_type)
    info.receive_rate_mbps = values.get("receive_rate_mbps", "")
    info.transmit_rate_mbps = values.get("transmit_rate_mbps", "")
    info.rssi = values.get("rssi", "").replace("dBm", "").strip()

    signal_match = re.search(r"(\d+)", values.get("signal", ""))
    info.signal_percent = int(signal_match.group(1)) if signal_match else None

    if not any([info.interface_name, info.state, info.ssid, info.bssid, info.channel, info.receive_rate_mbps]):
        info.parser_message = "일부 Wi-Fi 정보를 파싱하지 못했습니다. 아래 원본 출력을 함께 확인해 주세요."
    return info
