"""
Simple WebSocket server for RackService order monitoring.

Broadcasts order changes to connected clients and handles get_order requests.

Run with: python -m mod_rack.ws_server
"""

import asyncio
import json
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import websockets
from websockets.server import WebSocketServerProtocol

from mod_rack.client import GraphParamSetEvent, GraphParamSetBypassEvent

if TYPE_CHECKING:
    from mod_rack.rack import Orchestrator, PluginSlot


def _serialize_control(ctrl) -> dict:
    """Serialize a ControlPort to dict for JSON."""
    return {
        "symbol": ctrl.symbol,
        "name": ctrl.name,
        "minimum": ctrl.minimum,
        "maximum": ctrl.maximum,
        "default": ctrl.default,
        "scale_points": [{"value": sp.value, "label": sp.label} for sp in ctrl.scale_points],
        "properties": ctrl.properties.name if ctrl.properties else "NONE",
        "units": {"symbol": ctrl.units.symbol, "label": ctrl.units.label} if ctrl.units else None,
        "range_steps": ctrl.range_steps,
        "value": ctrl.value,
    }


def _serialize_slot(slot: "PluginSlot") -> dict:
    """Serialize a PluginSlot with its controls to dict for JSON."""
    return {
        "label": slot.label,
        "bypassed": slot.plugin.bypassed,
        "controls": [_serialize_control(ctrl) for ctrl in slot.plugin.controls.values()],
    }


class RackWSServer:
    """
    WebSocket server that exposes rack order to clients.

    Protocol:
        Client -> Server:
            {"cmd": "get_order"}

        Server -> Client:
            {"event": "order", "slots": [{label, controls: [...]}]}
    """

    def __init__(self, orchestrator: "Orchestrator", host: str = "0.0.0.0", port: int = 9000):
        self.orchestrator = orchestrator
        self.host = host
        self.port = port
        self._clients: set[WebSocketServerProtocol] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server_task: asyncio.Task | None = None

        # Register for order changes
        orchestrator.on_rack_order_changed(self._on_order_changed)

        # Register for param changes
        orchestrator.client.ws.on(GraphParamSetEvent, self._on_param_changed)
        orchestrator.client.ws.on(GraphParamSetBypassEvent, self._on_bypass_changed)

    def _get_order_data(self) -> list[dict]:
        """Get current order as list of slot data with controls."""
        return [_serialize_slot(slot) for slot in self.orchestrator.slots]

    def _on_order_changed(self, slots: list["PluginSlot"]) -> None:
        """Called when rack order changes - broadcast to all clients."""
        slots_data = [_serialize_slot(slot) for slot in slots]
        message = json.dumps({"event": "order", "slots": slots_data})

        if self._loop and self._clients:
            asyncio.run_coroutine_threadsafe(
                self._broadcast(message),
                self._loop
            )

    def _on_param_changed(self, event: GraphParamSetEvent) -> None:
        """Called when a plugin parameter changes - broadcast to all clients."""
        message = json.dumps({
            "event": "param",
            "label": event.label,
            "symbol": event.symbol,
            "value": event.value,
        })

        if self._loop and self._clients:
            asyncio.run_coroutine_threadsafe(
                self._broadcast(message),
                self._loop
            )

    def _on_bypass_changed(self, event: GraphParamSetBypassEvent) -> None:
        """Called when a plugin bypass state changes - broadcast to all clients."""
        message = json.dumps({
            "event": "bypass",
            "label": event.label,
            "bypassed": event.bypassed,
        })

        if self._loop and self._clients:
            asyncio.run_coroutine_threadsafe(
                self._broadcast(message),
                self._loop
            )

    async def _broadcast(self, message: str) -> None:
        """Send message to all connected clients."""
        if not self._clients:
            return

        dead = set()
        for ws in self._clients:
            try:
                await ws.send(message)
            except websockets.ConnectionClosed:
                dead.add(ws)

        self._clients -= dead

    async def _handle_client(self, websocket: WebSocketServerProtocol) -> None:
        """Handle a single client connection."""
        self._clients.add(websocket)
        print(f"[WS] Client connected: {websocket.remote_address}")

        # Send current order on connect
        slots_data = self._get_order_data()
        await websocket.send(json.dumps({"event": "order", "slots": slots_data}))

        try:
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                    cmd = msg.get("cmd")

                    if cmd == "get_order":
                        slots_data = self._get_order_data()
                        await websocket.send(json.dumps({"event": "order", "slots": slots_data}))
                    else:
                        await websocket.send(json.dumps({"error": f"unknown cmd: {cmd}"}))

                except json.JSONDecodeError:
                    await websocket.send(json.dumps({"error": "invalid json"}))

        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)
            print(f"[WS] Client disconnected: {websocket.remote_address}")

    async def _run_server(self) -> None:
        """Main server coroutine."""
        async with websockets.serve(self._handle_client, self.host, self.port):
            print(f"[WS] RackWSServer listening on ws://{self.host}:{self.port}")
            await asyncio.Future()  # run forever

    def start(self) -> None:
        """Start server in a background thread."""
        def run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._run_server())

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

    def run(self) -> None:
        """Run server in current thread (blocking)."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._run_server())


def main():
    import argparse

    from mod_rack.config import Config
    from mod_rack.client import DEFAULT_SERVER_URL
    from mod_rack.rack import Orchestrator, OrchestratorMode

    # Add src to path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    parser = argparse.ArgumentParser(description="MOD Rack WebSocket Server")
    parser.add_argument(
        "--server", "-s", default=DEFAULT_SERVER_URL, help="MOD server URL"
    )
    parser.add_argument(
        "--config", "-c", help="Config", type=Path, default="config.toml"
    )
    parser.add_argument(
        "--ws-port", "-p", type=int, default=9000, help="WebSocket server port"
    )
    args = parser.parse_args()

    config = Config.load(args.config)

    print(f"Connecting to MOD server at {args.server}...")
    orchestrator = Orchestrator(args.server, config, OrchestratorMode.MANAGER)

    ws_server = RackWSServer(orchestrator, port=args.ws_port)
    ws_server.start()

    try:
        orchestrator.run()
    except KeyboardInterrupt:
        print("Stopping...")


if __name__ == "__main__":
    main()
