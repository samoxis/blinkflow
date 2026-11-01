"""pytest: every test runs offline. A test that opens a network connection fails instead of reaching an API."""
import socket


def _offline(*args, **kwargs):
    raise RuntimeError("the tests run offline: no network, no API")


socket.socket.connect = _offline
socket.create_connection = _offline
