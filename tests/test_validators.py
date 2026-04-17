from app.utils.validators import calculate_subnet_details


def test_calculate_subnet_details_slash_24():
    details = calculate_subnet_details("192.168.0.10", 24)
    assert details["network_address"] == "192.168.0.0"
    assert details["broadcast_address"] == "192.168.0.255"
    assert details["usable_hosts"] == "254"


def test_calculate_subnet_details_slash_31():
    details = calculate_subnet_details("10.0.0.0", 31)
    assert details["network_address"] == "10.0.0.0"
    assert details["broadcast_address"] == "10.0.0.1"
    assert details["first_host"] == "10.0.0.0"
    assert details["last_host"] == "10.0.0.1"
    assert details["usable_hosts"] == "2"


def test_calculate_subnet_details_slash_32():
    details = calculate_subnet_details("10.0.0.9", 32)
    assert details["network_address"] == "10.0.0.9"
    assert details["broadcast_address"] == "10.0.0.9"
    assert details["host_range"] == "10.0.0.9"
    assert details["usable_hosts"] == "1"


def test_calculate_subnet_details_mask_input():
    details = calculate_subnet_details("172.16.1.20", "255.255.255.0")
    assert details["prefix_length"] == "24"
    assert details["network_address"] == "172.16.1.0"
    assert details["broadcast_address"] == "172.16.1.255"
