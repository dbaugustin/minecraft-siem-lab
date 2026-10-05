"""A small RCON client for Minecraft.

RCON is the Source engine's remote console protocol, which Minecraft speaks
on port 25575. It runs over a plain TCP connection, and every message in
either direction is one packet:

    int32 length      bytes that follow this field (little-endian)
    int32 request_id  chosen by the client, echoed back in the reply
    int32 type        3 = login, 2 = run a command, 0 = command output
    bytes body        UTF-8 text, then a NUL
    byte  0           one more NUL (an empty second string)

A session is: connect, send a login packet with the password, read the reply
(request_id -1 means the password was wrong), then send command packets and
read one reply packet per command.

Nothing is encrypted, including the password. That's acceptable here only
because each world's RCON port lives on the internal Docker network and is
never published on the host.
"""

import socket
import struct

TYPE_LOGIN = 3
TYPE_COMMAND = 2
TYPE_RESPONSE = 0

# Minecraft rejects command packets with a body longer than this.
MAX_COMMAND = 1446
# Largest packet we accept; Minecraft's replies are at most 4096 bytes of body.
MAX_PACKET = 4096 + 10


class RconError(Exception):
    pass


class RconAuthError(RconError):
    pass


class Rcon:
    def __init__(self, host, port, password, timeout=5.0):
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self._sock = None
        self._next_id = 0

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    def connect(self):
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as e:
            raise RconError(f"cannot connect to {self.host}:{self.port}: {e}") from e
        request_id = self._send(TYPE_LOGIN, self.password)
        reply_id, _, _ = self._read()
        if reply_id == -1:
            self.close()
            raise RconAuthError("RCON password rejected")
        if reply_id != request_id:
            self.close()
            raise RconError("unexpected reply to RCON login")

    def close(self):
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def command(self, text):
        """Run one console command and return its output as text.

        Output longer than one packet (4096 bytes) is cut off; none of the
        commands the dashboard uses come close to that.
        """
        if self._sock is None:
            raise RconError("not connected")
        if len(text.encode("utf-8")) > MAX_COMMAND or "\x00" in text:
            raise RconError("command too long or contains NUL")
        request_id = self._send(TYPE_COMMAND, text)
        reply_id, _, body = self._read()
        if reply_id != request_id:
            raise RconError("RCON reply did not match the command sent")
        return body

    def _send(self, packet_type, body):
        self._next_id += 1
        payload = struct.pack("<ii", self._next_id, packet_type) + body.encode("utf-8") + b"\x00\x00"
        try:
            self._sock.sendall(struct.pack("<i", len(payload)) + payload)
        except OSError as e:
            raise RconError(f"send failed: {e}") from e
        return self._next_id

    def _recv_exact(self, n):
        data = b""
        while len(data) < n:
            try:
                chunk = self._sock.recv(n - len(data))
            except OSError as e:
                raise RconError(f"receive failed: {e}") from e
            if not chunk:
                raise RconError("connection closed by server")
            data += chunk
        return data

    def _read(self):
        (length,) = struct.unpack("<i", self._recv_exact(4))
        if not 10 <= length <= MAX_PACKET:
            raise RconError(f"bad RCON packet length {length}")
        data = self._recv_exact(length)
        request_id, packet_type = struct.unpack("<ii", data[:8])
        body = data[8:-2].decode("utf-8", errors="replace")
        return request_id, packet_type, body
