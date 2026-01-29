"""
MicroPython WebSocket client for RackService order monitoring.

Usage:
    from rack_client import RackClient

    def on_order(slots):
        for slot in slots:
            print("Slot:", slot["label"])
            for ctrl in slot["controls"]:
                print("  ", ctrl["name"], "=", ctrl["value"])

    client = RackClient("192.168.1.100", 9000)
    client.on_order_change = on_order
    client.connect()

    # Or request manually:
    slots = client.get_order()
"""

import json
import socket


class RackClient:
    """
    Simple WebSocket client for MicroPython.

    Connects to RackWSServer and receives order updates.
    """

    def __init__(self, host, port=9000):
        self.host = host
        self.port = port
        self._sock = None
        self._connected = False
        self._slots = []

        # Callback for order changes (receives list of slot dicts)
        self.on_order_change = None

    def connect(self):
        """Connect to WebSocket server."""
        try:
            addr_info = socket.getaddrinfo(self.host, self.port)[0]
            self._sock = socket.socket(addr_info[0], addr_info[1])
            self._sock.connect(addr_info[-1])

            # WebSocket handshake
            key = b"dGhlIHNhbXBsZSBub25jZQ=="
            host_bytes = self.host.encode() if isinstance(self.host, str) else self.host
            port_bytes = str(self.port).encode()
            request = b"GET / HTTP/1.1\r\nHost: " + host_bytes + b":" + port_bytes + b"\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: " + key + b"\r\nSec-WebSocket-Version: 13\r\n\r\n"
            self._sock.send(request)

            # Read response
            response = self._sock.recv(1024).decode()
            if "101" not in response:
                print("WebSocket handshake failed")
                return False

            self._connected = True
            print("Connected to ws://" + self.host + ":" + str(self.port))
            return True

        except Exception as e:
            print("Connection failed:", e)
            return False

    def disconnect(self):
        """Close connection."""
        if self._sock:
            try:
                self._sock.close()
            except:
                pass
        self._connected = False
        self._sock = None

    def _send_frame(self, data):
        """Send WebSocket frame (masked, as client)."""
        length = len(data)
        frame = bytearray()

        # Opcode 0x81 = text frame, FIN bit set
        frame.append(0x81)

        # Length with mask bit set (0x80)
        if length < 126:
            frame.append(0x80 | length)
        elif length < 65536:
            frame.append(0x80 | 126)
            frame.append((length >> 8) & 0xFF)
            frame.append(length & 0xFF)
        else:
            raise ValueError("Message too long")

        # Mask key (simple fixed mask for simplicity)
        mask = bytes([0x12, 0x34, 0x56, 0x78])
        frame.extend(mask)

        # Masked payload
        for i, b in enumerate(data):
            frame.append(b ^ mask[i % 4])

        self._sock.send(bytes(frame))

    def _recv_frame(self):
        """Receive WebSocket frame."""
        try:
            # Read first 2 bytes
            header = self._sock.recv(2)
            if len(header) < 2:
                return None

            opcode = header[0] & 0x0F
            length = header[1] & 0x7F

            # Handle extended length
            if length == 126:
                ext = self._sock.recv(2)
                length = (ext[0] << 8) | ext[1]
            elif length == 127:
                ext = self._sock.recv(8)
                length = int.from_bytes(ext, "big")

            # Server frames are not masked
            payload = b""
            while len(payload) < length:
                chunk = self._sock.recv(length - len(payload))
                if not chunk:
                    break
                payload += chunk

            if opcode == 0x08:  # Close frame
                self._connected = False
                return None

            if opcode == 0x01:  # Text frame
                return payload.decode()

            return None

        except Exception as e:
            print("Recv error:", e)
            return None

    def _send(self, msg):
        """Send JSON message."""
        self._send_frame(json.dumps(msg).encode())

    def get_order(self):
        """Request current order from server. Returns list of slot dicts."""
        if not self._connected:
            return []

        self._send({"cmd": "get_order"})
        response = self._recv_frame()

        if response:
            data = json.loads(response)
            if data.get("event") == "order":
                self._slots = data.get("slots", [])
                return self._slots

        return []

    @property
    def slots(self):
        """Last known slots list."""
        return self._slots

    @property
    def labels(self):
        """Get just the labels from slots."""
        return [s.get("label", "") for s in self._slots]

    def poll(self):
        """
        Check for incoming messages (non-blocking if socket is non-blocking).

        Returns True if a message was received.
        """
        if not self._connected:
            return False

        response = self._recv_frame()
        if response:
            try:
                data = json.loads(response)
                if data.get("event") == "order":
                    self._slots = data.get("slots", [])
                    if self.on_order_change:
                        self.on_order_change(self._slots)
                    return True
            except:
                pass

        return False

    def run_forever(self):
        """Block and process messages until disconnected."""
        while self._connected:
            self.poll()


if __name__ == "__main__":
    import sys

    host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9000

    def on_order(slots):
        print("Order changed:")
        for slot in slots:
            print(" -", slot.get("label", "?"))

    client = RackClient(host, port)
    client.on_order_change = on_order

    if client.connect():
        print("Initial labels:", client.labels)
        print("Listening for changes... (Ctrl+C to stop)")
        try:
            client.run_forever()
        except KeyboardInterrupt:
            print("Disconnecting...")
            client.disconnect()
