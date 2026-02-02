import json
import socket
import threading
from PySide6.QtCore import QObject, Signal


class RackWSClient(QObject):
    """
    Lightweight WebSocket client for PySide6.
    Sends Qt signals when receiving data from server.
    """

    order_changed = Signal(list)
    param_changed = Signal(str, str, float)  # label, symbol, value
    bypass_changed = Signal(str, bool)  # label, bypassed
    connection_status = Signal(bool)

    def __init__(self, host="localhost", port=9000):
        super().__init__()
        self.host = host
        self.port = port
        self._sock = None
        self._connected = False
        self._running = False

    def connect_server(self):
        try:
            addr_info = socket.getaddrinfo(self.host, self.port)[0]
            self._sock = socket.socket(addr_info[0], addr_info[1])
            self._sock.connect(addr_info[-1])

            # Handshake
            key = b"dGhlIHNhbXBsZSBub25jZQ=="
            request = (
                b"GET / HTTP/1.1\r\nHost: "
                + self.host.encode()
                + b":"
                + str(self.port).encode()
                + b"\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: "
                + key
                + b"\r\nSec-WebSocket-Version: 13\r\n\r\n"
            )
            self._sock.send(request)
            response = self._sock.recv(1024).decode()

            if "101" in response:
                self._connected = True
                self.connection_status.emit(True)
                # Start reading thread
                self._running = True
                threading.Thread(target=self._listen, daemon=True).start()
                # Request initial state
                self.send_cmd({"cmd": "get_order"})
                return True
        except Exception as e:
            print(f"Connection error: {e}")
            self.connection_status.emit(False)
        return False

    def send_cmd(self, data):
        if not self._connected:
            return
        try:
            msg = json.dumps(data).encode()
            length = len(msg)
            frame = bytearray([0x81])
            if length < 126:
                frame.append(0x80 | length)
            else:
                frame.append(0x80 | 126)
                frame.extend(length.to_bytes(2, "big"))

            mask = bytes([0x11, 0x22, 0x33, 0x44])
            frame.extend(mask)
            for i, b in enumerate(msg):
                frame.append(b ^ mask[i % 4])
            self._sock.send(bytes(frame))
        except Exception as err:
            print(err)
            self._connected = False

    def _listen(self):
        while self._running:
            try:
                header = self._sock.recv(2)
                if not header:
                    break
                length = header[1] & 0x7F
                if length == 126:
                    length = int.from_bytes(self._sock.recv(2), "big")

                payload = b""
                while len(payload) < length:
                    payload += self._sock.recv(length - len(payload))

                data = json.loads(payload.decode())
                event = data.get("event")
                if event == "order":
                    self.order_changed.emit(data.get("slots", []))
                elif event == "param":
                    self.param_changed.emit(
                        data["label"], data["symbol"], data["value"]
                    )
                elif event == "bypass":
                    self.bypass_changed.emit(data["label"], data["bypassed"])
            except Exception as err:
                print(err)
                break
        self._connected = False
        self.connection_status.emit(False)
