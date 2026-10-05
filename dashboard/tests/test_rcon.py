"""RCON client against a tiny in-process server speaking the real protocol."""

import socket
import struct
import threading

import pytest

from mcdash.rcon import Rcon, RconAuthError, RconError

PASSWORD = "s3cret"


def read_packet(conn):
    (length,) = struct.unpack("<i", conn.recv(4, socket.MSG_WAITALL))
    data = conn.recv(length, socket.MSG_WAITALL)
    request_id, ptype = struct.unpack("<ii", data[:8])
    return request_id, ptype, data[8:-2].decode()


def send_packet(conn, request_id, ptype, body):
    payload = struct.pack("<ii", request_id, ptype) + body.encode() + b"\x00\x00"
    conn.sendall(struct.pack("<i", len(payload)) + payload)


@pytest.fixture
def server():
    """Accepts one connection; replies to commands with 'echo: <command>'."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    received = []

    def serve():
        conn, _ = sock.accept()
        with conn:
            request_id, ptype, body = read_packet(conn)
            assert ptype == 3
            if body != PASSWORD:
                send_packet(conn, -1, 2, "")
                return
            send_packet(conn, request_id, 2, "")
            while True:
                try:
                    request_id, ptype, body = read_packet(conn)
                except (struct.error, OSError):
                    return
                received.append((ptype, body))
                send_packet(conn, request_id, 0, f"echo: {body}")

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield sock.getsockname()[1], received
    sock.close()


def test_login_and_command(server):
    port, received = server
    with Rcon("127.0.0.1", port, PASSWORD) as rcon:
        assert rcon.command("whitelist add Steve") == "echo: whitelist add Steve"
        assert rcon.command("list") == "echo: list"
    assert received == [(2, "whitelist add Steve"), (2, "list")]


def test_wrong_password(server):
    port, _ = server
    with pytest.raises(RconAuthError):
        Rcon("127.0.0.1", port, "wrong").connect()


def test_connection_refused():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    with pytest.raises(RconError):
        Rcon("127.0.0.1", port, PASSWORD, timeout=1).connect()


def test_rejects_oversized_command(server):
    port, _ = server
    with Rcon("127.0.0.1", port, PASSWORD) as rcon:
        with pytest.raises(RconError):
            rcon.command("say " + "x" * 2000)
