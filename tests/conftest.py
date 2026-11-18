"""pytest: every test runs offline. A test that opens a network connection fails instead of reaching an API.
Only this machine stays reachable: UNIX sockets and loopback TCP (the QNX bridge's round trip)."""
import ipaddress
import socket

_connect, _create_connection = socket.socket.connect, socket.create_connection


def _local(host) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _offline(*args, **kwargs):
    raise RuntimeError("the tests run offline: no network, no API")


def connect(self, address):
    if self.family == socket.AF_UNIX or _local(address[0]):
        return _connect(self, address)
    _offline()


def create_connection(address, *args, **kwargs):
    if _local(address[0]):
        return _create_connection(address, *args, **kwargs)
    _offline()


socket.socket.connect = connect
socket.create_connection = create_connection
