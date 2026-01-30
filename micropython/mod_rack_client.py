"""
MicroPython WebSocket client for RackService order monitoring.

Usage:
    from rack_client import RackClient

    def on_order(slots):
        for slot in slots:
            print("Slot:", slot["label"])
            for ctrl in slot["controls"]:
                print("  ", ctrl["name"], "=", ctrl["value"])

    def on_param(label, symbol, value):
        print("Param changed:", label, symbol, "=", value)

    client = RackClient("192.168.1.100", 9000)
    client.on_order_change = on_order
    client.on_param_change = on_param
    client.connect()

    # Or request manually:
    slots = client.get_order()

    # Local state auto-updates on param events
    client.run_forever()
"""

import json
import socket
import time


class RackClient:
    """
    Simple WebSocket client for MicroPython.

    Connects to RackWSServer and receives order updates.
    """

    def __init__(self, host, port=9000, reconnect_delay=1):
        self.host = host
        self.port = port
        self.reconnect_delay = reconnect_delay
        self._sock = None
        self._connected = False
        self._slots = []

        # Callback for order changes (receives list of slot dicts)
        self.on_order_change = None
        # Callback for param changes (receives label, symbol, value)
        self.on_param_change = None
        # Callback for bypass changes (receives label, bypassed)
        self.on_bypass_change = None
        # Callback for connection state changes
        self.on_connect = None
        self.on_disconnect = None

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
            request = (
                b"GET / HTTP/1.1\r\nHost: "
                + host_bytes
                + b":"
                + port_bytes
                + b"\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: "
                + key
                + b"\r\nSec-WebSocket-Version: 13\r\n\r\n"
            )
            self._sock.send(request)

            # Read response
            response = self._sock.recv(1024).decode()
            if "101" not in response:
                print("WebSocket handshake failed")
                return False

            self._connected = True
            print("Connected to ws://" + self.host + ":" + str(self.port))
            if self.on_connect:
                self.on_connect()
            return True

        except Exception as e:
            print("Connection failed:", e)
            return False

    def disconnect(self):
        """Close connection."""
        was_connected = self._connected
        if self._sock:
            try:
                self._sock.close()
            except Exception as e:
                print(e)
                pass
        self._connected = False
        self._sock = None
        if was_connected and self.on_disconnect:
            self.on_disconnect()

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
        """Receive WebSocket frame. Raises OSError on timeout/EAGAIN."""
        # Read first 2 bytes (may raise OSError EAGAIN in non-blocking mode)
        header = self._sock.recv(2)
        if not header or len(header) < 2:
            self.disconnect()
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
                self.disconnect()
                return None
            payload += chunk

        if opcode == 0x08:  # Close frame
            self._connected = False
            return None

        if opcode == 0x01:  # Text frame
            return payload.decode()

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

    def set_param(self, label, symbol, value):
        """Set a plugin parameter (only INPUT controls). Fire and forget."""
        if not self._connected:
            return
        self._send(
            {"cmd": "set_param", "label": label, "symbol": symbol, "value": value}
        )

    def set_bypass(self, label, bypassed):
        """Set plugin bypass state. Fire and forget."""
        if not self._connected:
            return
        self._send({"cmd": "set_bypass", "label": label, "bypassed": bypassed})

    @property
    def slots(self):
        """Last known slots list."""
        return self._slots

    @property
    def labels(self):
        """Get just the labels from slots."""
        return [s.get("label", "") for s in self._slots]

    def _update_param(self, label, symbol, value):
        """Update a control value in local state."""
        for slot in self._slots:
            if slot.get("label") == label:
                for ctrl in slot.get("controls", []):
                    if ctrl.get("symbol") == symbol:
                        ctrl["value"] = value
                        return True
        return False

    def _update_bypass(self, label, bypassed):
        """Update bypass state in local state."""
        for slot in self._slots:
            if slot.get("label") == label:
                slot["bypassed"] = bypassed
                return True
        return False

    def poll(self, timeout=0):
        """
        Check for incoming messages (non-blocking by default).

        Returns True if a message was received.
        """
        if not self._connected or not self._sock:
            return False

        # Set timeout for non-blocking read
        self._sock.settimeout(timeout)
        try:
            response = self._recv_frame()
        except OSError:
            # No data available (timeout)
            return False
        finally:
            # Restore blocking mode for other operations
            self._sock.settimeout(None)
        if response:
            try:
                data = json.loads(response)
                event = data.get("event")

                if event == "order":
                    self._slots = data.get("slots", [])
                    if self.on_order_change:
                        self.on_order_change(self._slots)
                    return True

                elif event == "param":
                    label = data.get("label")
                    symbol = data.get("symbol")
                    value = data.get("value")
                    self._update_param(label, symbol, value)
                    if self.on_param_change:
                        self.on_param_change(label, symbol, value)
                    return True

                elif event == "bypass":
                    label = data.get("label")
                    bypassed = data.get("bypassed")
                    self._update_bypass(label, bypassed)
                    if self.on_bypass_change:
                        self.on_bypass_change(label, bypassed)
                    return True
            except Exception as e:
                print("Error", e)
                pass

        return False

    def run_forever(self, auto_reconnect=True):
        """Block and process messages. Auto-reconnects on disconnect."""
        while True:
            while self._connected:
                self.poll()

            if not auto_reconnect:
                break

            print("Reconnecting in", self.reconnect_delay, "seconds...")
            time.sleep(self.reconnect_delay)
            self.connect()


if __name__ == "__main__":
    import sys

    host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9000

    def on_order(slots):
        print("Order changed:")
        for slot in slots:
            print(" -", slot.get("label", "?"))

    def on_param(label, symbol, value):
        print("Param:", label, symbol, "=", value)

    def on_bypass(label, bypassed):
        print("Bypass:", label, "=", bypassed)

    def on_connect():
        print("Connected!")

    def on_disconnect():
        print("Disconnected!")

    client = RackClient(host, port)
    client.on_order_change = on_order
    client.on_param_change = on_param
    client.on_bypass_change = on_bypass
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    print("Connecting... (Ctrl+C to stop)")
    try:
        if not client.connect():
            print("Failed to connect")
            sys.exit(1)

        # Get initial order
        slots = client.get_order()
        if not slots:
            print("No slots found")
            sys.exit(1)

        # Find first slot with an INPUT control
        test_label = None
        test_symbol = None
        test_min = 0.0
        test_max = 1.0
        test_value = 0.5

        for slot in slots:
            for ctrl in slot.get("controls", []):
                if ctrl.get("direction") == "INPUT":
                    test_label = slot.get("label")
                    test_symbol = ctrl.get("symbol")
                    test_min = ctrl.get("minimum", 0.0)
                    test_max = ctrl.get("maximum", 1.0)
                    test_value = ctrl.get("value", (test_min + test_max) / 2)
                    break
            if test_label:
                break

        if not test_label:
            print("No INPUT control found")
            sys.exit(1)

        print("Testing control:", test_label, test_symbol)
        print("Range:", test_min, "-", test_max)

        # Test loop: oscillate by +-0.5
        direction = 1
        step = 0.5

        while True:
            # Calculate new value
            new_value = test_value + (step * direction)

            # Clamp to range and reverse direction if needed
            if new_value > test_max:
                new_value = test_max
                direction = -1
            elif new_value < test_min:
                new_value = test_min
                direction = 1

            # Set the parameter
            print("Setting", test_symbol, "=", new_value)
            client.set_param(test_label, test_symbol, new_value)
            test_value = new_value

            # Poll for responses
            time.sleep(0.2)
            client.poll()
            time.sleep(0.2)

    except KeyboardInterrupt:
        print("Stopping...")
        client.disconnect()
