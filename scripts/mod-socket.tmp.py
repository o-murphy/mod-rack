import websocket
import random
import time
import threading

# MODEP address
WS_URL = "ws://127.0.0.1:18181/websocket"

# Global socket variable
ws_client = None


def send_random_parameters():
    global ws_client
    print(">>> Randomization loop started.")

    while True:
        try:
            if ws_client and ws_client.sock and ws_client.sock.connected:
                val = random.uniform(0.0, 1.0)

                # FORMAT: param_set [path/to/parameter] [value]
                # Note the slash between cs_chorus1_1 and mod_freq_2
                command = f"param_set /graph/cs_chorus1_1/mod_freq_2 {val:.15f}"

                ws_client.send(command)
                print(f"Sent: {command}")
            else:
                # Waiting for connection
                pass
        except Exception as e:
            print(f"Error: {e}")

        time.sleep(1)


def on_message(ws, message):
    # Filter technical info
    if "stats" not in message and "ping" not in message:
        print(f"MODEP: {message}")


def on_open(ws):
    print("--- Connection established! ---")


def run_ws():
    global ws_client
    while True:
        ws_client = websocket.WebSocketApp(
            WS_URL,
            on_open=on_open,
            on_message=on_message,
        )
        # ping_interval keeps connection alive
        ws_client.run_forever(ping_interval=10, ping_timeout=5)
        print("Connection lost. Reconnecting...")
        time.sleep(2)


if __name__ == "__main__":
    # 1. Start logic thread (now without args, via global variable)
    logic_thread = threading.Thread(target=send_random_parameters, daemon=True)
    logic_thread.start()

    # 2. Start main WebSocket loop
    try:
        run_ws()
    except KeyboardInterrupt:
        print("Stopping program...")
