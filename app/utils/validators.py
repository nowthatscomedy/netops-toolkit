from __future__ import annotations

import ipaddress


class ValidationError(ValueError):
    pass


def require_text(value: str, field_name: str) -> str:
    text = value.strip()
    if not text:
        raise ValidationError(f"{field_name} 값을 입력해 주세요.")
    return text


def validate_ipv4(value: str, field_name: str) -> str:
    text = require_text(value, field_name)
    try:
        ipaddress.IPv4Address(text)
    except ipaddress.AddressValueError as exc:
        raise ValidationError(f"{field_name} 값이 올바른 IPv4 주소가 아닙니다.") from exc
    return text


def validate_optional_ipv4(value: str, field_name: str) -> str:
    text = value.strip()
    if not text:
        return ""
    try:
        ipaddress.IPv4Address(text)
    except ipaddress.AddressValueError as exc:
        raise ValidationError(f"{field_name} 값이 올바른 IPv4 주소가 아닙니다.") from exc
    return text


def parse_prefix_value(value: str | int) -> int:
    if isinstance(value, int):
        prefix = value
    else:
        text = str(value).strip()
        if not text:
            raise ValidationError("Prefix 또는 서브넷 마스크를 입력해 주세요.")
        if text.isdigit():
            prefix = int(text)
        else:
            try:
                prefix = ipaddress.IPv4Network(f"0.0.0.0/{text}").prefixlen
            except (ipaddress.NetmaskValueError, ValueError) as exc:
                raise ValidationError("Prefix는 1~32 또는 서브넷 마스크(예: 255.255.255.0) 형식이어야 합니다.") from exc
    if not 1 <= int(prefix) <= 32:
        raise ValidationError("Prefix 길이는 1~32 범위여야 합니다.")
    return int(prefix)


def validate_prefix(prefix: str | int) -> int:
    return parse_prefix_value(prefix)


def prefix_to_netmask(prefix: str | int) -> str:
    prefix_length = parse_prefix_value(prefix)
    return str(ipaddress.IPv4Network(f"0.0.0.0/{prefix_length}").netmask)


def format_prefix(prefix: str | int) -> str:
    prefix_length = parse_prefix_value(prefix)
    return f"{prefix_length} / {prefix_to_netmask(prefix_length)}"


def parse_dns_servers(raw_value: str) -> list[str]:
    servers: list[str] = []
    for part in raw_value.replace("\n", ",").split(","):
        candidate = part.strip()
        if not candidate:
            continue
        validate_ipv4(candidate, "DNS 서버")
        servers.append(candidate)
    return servers


def validate_host_input(value: str) -> str:
    text = require_text(value, "대상")
    if " " in text:
        raise ValidationError("대상 값에는 공백을 포함할 수 없습니다.")
    return text


def parse_positive_int(value: str | int, field_name: str, minimum: int = 1, maximum: int | None = None) -> int:
    text = str(value).strip()
    if not text:
        raise ValidationError(f"{field_name} 값을 입력해 주세요.")
    try:
        parsed = int(text)
    except ValueError as exc:
        raise ValidationError(f"{field_name} 값은 숫자여야 합니다.") from exc
    if parsed < minimum:
        raise ValidationError(f"{field_name} 값은 {minimum} 이상이어야 합니다.")
    if maximum is not None and parsed > maximum:
        raise ValidationError(f"{field_name} 값은 {maximum} 이하여야 합니다.")
    return parsed
