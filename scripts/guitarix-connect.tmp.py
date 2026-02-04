import socket
import json
import time


class GuitarixFinalV:
    def __init__(self, host="localhost", port=7000):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s.connect((host, port))
        # Set small timeout so script doesn't hang on read
        self.s.settimeout(0.5)

    def notify(self, method, params):
        """For methods without response (insert, set, order)"""
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        data = json.dumps(payload, separators=(",", ":")) + "\n"
        print(f"-> NOTIFY: {method}")
        self.s.sendall(data.encode())
        # After notify DO NOT read response to avoid JSONDecodeError

    def run(self):
        # 1. Insert modules
        # According to your file, positions 1 and 2
        self.notify("insert_rack_unit", ["gx_distortion", 1, 0])
        self.notify("insert_rack_unit", ["chorus", 2, 0])

        # 2. Set order
        # IMPORTANT: your version may want list as single object, let's try:
        self.notify("set_rack_unit_order", ["amp", "gx_distortion", "chorus", "cab"])

        # 3. Enable (on_off)
        self.notify("set", ["gx_distortion.on_off", 1])
        self.notify("set", ["chorus.on_off", 1])

        # self.notify("plugin_preset_list_load", [1])

        self.notify("set", ["system.engine_state", 0])
        time.sleep(0.2)
        self.notify("set", ["system.engine_state", 1])

        # 4. "Shake" interface by changing preset
        # This will force GUI to re-read engine state
        self.notify("set", ["system.current_preset", 3])
        time.sleep(0.2)
        self.notify("set", ["system.current_preset", 4])

        print("[OK] Commands sent. Check Rack in Guitarix.")


if __name__ == "__main__":
    try:
        gx = GuitarixFinalV()
        gx.run()
    except Exception as e:
        print(f"Error: {e}")
