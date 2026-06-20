"""Host network diagnostics (Diagnostics page).

The composition is exercised with injected probes — no real host access — covering Wi-Fi,
Ethernet, and the no-interface fallback. `_pct_from_dbm` is checked directly.
"""

from __future__ import annotations

from app.host_network import host_network, _pct_from_dbm


def test_wifi_link_reports_ssid_and_signal():
    net = host_network(
        primary_iface=lambda: "wlan0",
        primary_ip=lambda: "192.168.1.42",
        is_wifi=lambda i: True,
        operstate=lambda i: "up",
        eth_speed=lambda i: None,
        ssid=lambda i: "MyHomeWiFi",
        wifi_signal=lambda i: (62, -48),
    )
    assert net["type"] == "wifi"
    assert net["ip"] == "192.168.1.42"
    assert net["status"] == "up"
    assert net["wifi"] == {"ssid": "MyHomeWiFi", "signal_dbm": -48, "signal_pct": 100, "link_quality": 62}
    assert net["ethernet"] is None


def test_ethernet_link_reports_name_and_speed():
    net = host_network(
        primary_iface=lambda: "eth0",
        primary_ip=lambda: "10.0.0.5",
        is_wifi=lambda i: False,
        operstate=lambda i: "up",
        eth_speed=lambda i: "1000",
        ssid=lambda i: None,
        wifi_signal=lambda i: (None, None),
    )
    assert net["type"] == "ethernet"
    assert net["ethernet"] == {"name": "eth0", "link_speed_mbps": 1000}
    assert net["wifi"] is None


def test_ethernet_unknown_speed_is_none():
    net = host_network(
        primary_iface=lambda: "eth0",
        primary_ip=lambda: "10.0.0.5",
        is_wifi=lambda i: False,
        operstate=lambda i: "down",
        eth_speed=lambda i: "-1",  # kernel reports -1 when the link is down
    )
    assert net["ethernet"]["link_speed_mbps"] is None
    assert net["status"] == "down"


def test_no_interface_falls_back_to_ip_presence():
    assert host_network(primary_iface=lambda: None, primary_ip=lambda: None)["status"] == "disconnected"
    got = host_network(primary_iface=lambda: None, primary_ip=lambda: "172.16.0.9")
    assert got["status"] == "connected" and got["ip"] == "172.16.0.9"


def test_pct_from_dbm():
    assert _pct_from_dbm(None) is None
    assert _pct_from_dbm(-50) == 100  # strong
    assert _pct_from_dbm(-100) == 0   # floor
    assert _pct_from_dbm(-75) == 50
