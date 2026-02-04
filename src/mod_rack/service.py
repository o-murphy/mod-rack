"""
Simple WebSocket server for RackService order monitoring.

Broadcasts order changes to connected clients and handles get_order requests.

Run with: python -m mod_rack.ws_server
"""

import asyncio
import json
import logging

# import sys
import threading
from pathlib import Path

import websockets
from websockets.asyncio.server import ServerConnection

from mod_rack.mod_client import (
    GraphOutputSetEvent,
    GraphParamSetEvent,
    GraphParamSetBypassEvent,
)
from mod_rack.schema.config import Config
from mod_rack.rack import OrchestratorMode, PluginSlot, Rack
from mod_rack.controls import PortControl
from mod_rack.mod_client import DEFAULT_SERVER_URL
from mod_rack.logger import logger


__all__ = ["main", "get_argparser", "RackWSServer"]


_log = logger.getChild(__name__)


def _serialize_control(ctrl: PortControl) -> dict:
    """Serialize a ControlPort to dict for JSON."""
    return {
        "symbol": ctrl.symbol,
        "name": ctrl.name,
        "port_type": ctrl.port_type.name,
        "direction": ctrl.direction.name,
        "minimum": ctrl.minimum,
        "maximum": ctrl.maximum,
        "default": ctrl.default,
        "scale_points": [{"value": sp.value, "label": sp.label} for sp in ctrl.scale_points],
        "properties": ctrl.properties,
        "units": {"symbol": ctrl.units.symbol, "label": ctrl.units.label} if ctrl.units else None,
        "range_steps": ctrl.range_steps,
        "value": ctrl.value,
    }


def _serialize_slot(slot: PluginSlot) -> dict:
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
            {"cmd": "order"}

        Server -> Client:
            {"event": "order", "slots": [{label, controls: [...]}]}
    """

    def __init__(self, rack: Rack, host: str = "0.0.0.0", port: int = 9000):
        self.rack = rack
        self.host = host
        self.port = port
        self._clients: set[ServerConnection] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server_task: asyncio.Task | None = None

        # Register for order changes
        rack.on_rack_order_changed(self._on_order_changed)

        # Register for param changes
        rack.client.ws.on(GraphParamSetEvent, self._on_control_changed)
        rack.client.ws.on(GraphParamSetBypassEvent, self._on_bypass_changed)
        rack.client.ws.on(GraphOutputSetEvent, self._on_control_changed)

    def _get_list(self):
        data = self.rack.installed_plugins
        return [
            {
                "uri": effect.get("uri"),
                "name": effect.get("name"),
                "brand": effect.get("brand"),
                "label": effect.get("label"),
                "category": effect.get("category"),
            }
            for effect in data
        ]

    def _get_order_data(self) -> list[dict]:
        """Get current order as list of slot data with controls."""
        return [_serialize_slot(slot) for slot in self.rack.slots]

    def _move_slot(self, from_idx: int, to_idx: int):
        return self.rack.request_move_slot(from_idx, to_idx)

    def _set_param(self, label: str, symbol: str, value: float) -> None:
        """Set a plugin parameter. Only works for INPUT controls."""
        from mod_rack.mod_client import PortDirection

        _log.debug("[RACK WS] _set_param: %s/%s = %s", label, symbol, value)

        slot = self.rack.get_slot_by_label(label)
        if not slot:
            _log.debug("[RACK WS] slot not found: %s", label)
            return

        plugin = slot.plugin
        if symbol not in plugin.controls:
            _log.debug("[RACK WS] symbol not found: %s", symbol)
            return

        control = plugin.controls[symbol]
        if control.direction != PortDirection.INPUT:
            _log.debug("[RACK WS] not INPUT: %s", symbol)
            return

        plugin.param_set(symbol, value)
        _log.debug("[RACK WS] param_set done")

        # Manually broadcast since MOD doesn't echo back our own changes
        message = json.dumps(
            {
                "event": "param",
                "label": label,
                "symbol": symbol,
                "value": value,
            }
        )
        if self._loop and self._clients:
            asyncio.run_coroutine_threadsafe(self._broadcast(message), self._loop)

    def _set_bypass(self, label: str, bypassed: bool) -> None:
        """Set plugin bypass state."""
        slot = self.rack.get_slot_by_label(label)
        if slot:
            slot.plugin.bypass(bypassed)

    def _on_order_changed(self, slots: list["PluginSlot"]) -> None:
        """Called when rack order changes - broadcast to all clients."""
        slots_data = [_serialize_slot(slot) for slot in slots]
        message = json.dumps({"event": "order", "slots": slots_data})

        if self._loop and self._clients:
            asyncio.run_coroutine_threadsafe(self._broadcast(message), self._loop)

    def _on_control_changed(self, event: GraphParamSetEvent | GraphOutputSetEvent) -> None:
        """Called when a plugin parameter changes - broadcast to all clients."""
        _log.debug(
            "[RACK WS] param changed: %s/%s = %s",
            event.label,
            event.symbol,
            event.value,
        )
        message = json.dumps(
            {
                "event": "param",
                "label": event.label,
                "symbol": event.symbol,
                "value": event.value,
            }
        )

        if self._loop and self._clients:
            asyncio.run_coroutine_threadsafe(self._broadcast(message), self._loop)

    def _on_bypass_changed(self, event: GraphParamSetBypassEvent) -> None:
        """Called when a plugin bypass state changes - broadcast to all clients."""
        message = json.dumps(
            {
                "event": "bypass",
                "label": event.label,
                "bypassed": event.bypassed,
            }
        )

        if self._loop and self._clients:
            asyncio.run_coroutine_threadsafe(self._broadcast(message), self._loop)

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

    async def _handle_client(self, websocket: ServerConnection) -> None:
        """Handle a single client connection."""
        self._clients.add(websocket)
        _log.debug("[RACK WS] Client connected: %s", websocket.remote_address)

        # Send current order on connect
        slots_data = self._get_order_data()
        await websocket.send(json.dumps({"event": "order", "slots": slots_data}))

        try:
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                    cmd = msg.get("cmd")

                    if cmd == "order":
                        slots_data = self._get_order_data()
                        await websocket.send(json.dumps({"event": "order", "slots": slots_data}))

                    elif cmd == "list":
                        effects_list = self._get_list()
                        await websocket.send(json.dumps({"event": "list", "effects": effects_list}))

                    elif cmd == "param":
                        label = msg.get("label")
                        symbol = msg.get("symbol")
                        value = msg.get("value")
                        self._set_param(label, symbol, value)

                    elif cmd == "bypass":
                        label = msg.get("label")
                        bypassed = msg.get("bypassed", False)
                        self._set_bypass(label, bypassed)

                    elif cmd == "mv":
                        from_idx = msg.get("from_idx")
                        to_idx = msg.get("to_idx")
                        if from_idx is None or to_idx is None:
                            return
                        self._move_slot(from_idx, to_idx)

                    else:
                        await websocket.send(json.dumps({"error": f"unknown cmd: {cmd}"}))

                except json.JSONDecodeError:
                    await websocket.send(json.dumps({"error": "invalid json"}))

        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)
            _log.debug("[RACK WS] Client disconnected: %s", websocket.remote_address)

    async def _run_server(self) -> None:
        """Main server coroutine."""
        async with websockets.serve(self._handle_client, self.host, self.port):
            _log.debug("[RACK WS] RackWSServer listening on ws://%s:%s", self.host, self.port)
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


def get_argparser():
    import argparse

    parser = argparse.ArgumentParser(description="MOD Rack WebSocket Server")
    parser.add_argument("--server", "-s", default=DEFAULT_SERVER_URL, help="MOD server URL")
    parser.add_argument("--config", "-c", help="Config", type=Path, default="config.toml")
    parser.add_argument(
        "--rack-ws-port",
        "-p",
        type=int,
        nargs="?",
        const=9000,
        default=None,
        help="Rack WebSocket server on port (default: 9000 if flag present)",
    )
    parser.add_argument("--slave", help="Slave", action="store_true")

    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    return parser


def main():
    parser = get_argparser()
    ns = parser.parse_args()

    if ns.verbose:
        logger.setLevel(logging.DEBUG)

    config = Config.load(ns.config)

    logger.info("Connecting to MOD server at %s...", ns.server)

    mode = OrchestratorMode.OBSERVER if ns.slave else OrchestratorMode.MANAGER
    orchestrator = Rack(ns.server, config, mode)

    # Now the logic works exactly as you wanted:
    if ns.rack_ws_port is not None:
        logger.info("Starting Rack WebSocket server on port %s...", ns.rack_ws_port)
        ws_server = RackWSServer(orchestrator, port=ns.rack_ws_port)
        ws_server.start()
    else:
        logger.info("Rack WebSocket server disabled (no rack-ws-port flag provided).")

    try:
        orchestrator.run()
    except KeyboardInterrupt:
        logger.info("Stopping...")


if __name__ == "__main__":
    main()
