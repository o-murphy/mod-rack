"""
Plugin model with control management.

Plugin instances are created when loading into a Slot and provide
dict-like access to control parameters with automatic API synchronization.
"""

from __future__ import annotations

from typing import Any, Iterator

from mod_rack.client import (
    GraphOutputSetEvent,
    GraphParamSetBypassEvent,
    Client,
    Port,
    GraphParamSetEvent,
    PortDirection,
    PortType,
)
from mod_rack.config import Config, PluginConfig
from mod_rack.controls import ControlPort, parse_control_ports


__all__ = ["Plugin"]


class Plugin:
    """
    A loaded plugin instance with control management.

    Provides dict-like access to controls:
        plugin['Dist']          # Get current value

    Attributes:
        uri: Plugin URI
        label: Unique instance label (e.g., "DS1_0")
        name: Display name
    """

    def __init__(
        self,
        client: Client,
        uri: str,
        label: str,
        config: PluginConfig | None = None,
        *,
        filter_gui_controls: bool = True,
    ):
        self.client = client
        self.uri = uri
        self.label = label

        self._bypassed = False
        self._config = (
            config if config is not None else PluginConfig(self.label, self.uri)
        )
        self._controls: dict[str, ControlPort] = {}

        # io setup
        self.audio_inputs: list[Port] = []
        self.audio_outputs: list[Port] = []
        self.midi_inputs: list[Port] = []
        self.midi_outputs: list[Port] = []
        self.cv_inputs: list[Port] = []
        self.cv_outputs: list[Port] = []

        # configuration
        self.join_audio_inputs: bool = (
            config.join_audio_inputs if config is not None else False
        )
        self.join_audio_outputs: bool = (
            config.join_audio_outputs if config is not None else False
        )

        self._effect_data: dict = self.client.effect_get(self.uri)
        self.name = self._effect_data.get("name", self.label)

        self.size: tuple[int, int] = self.client.effect_image_size(
            self.uri, "screenshot.png"
        )
        self._load_plugin_ports(filter_gui_controls)
        self._subscribe()

    def _subscribe(self):
        self.client.ws.on(GraphParamSetBypassEvent, self._on_bypass_change)
        self.client.ws.on(GraphParamSetEvent, self._on_control_change)
        self.client.ws.on(GraphOutputSetEvent, self._on_control_change)

    def _on_bypass_change(self, event: GraphParamSetBypassEvent):
        if self.label == event.label:
            self._bypassed = event.bypassed

    def _on_control_change(self, event: GraphParamSetEvent | GraphOutputSetEvent):
        if self.label == event.label and event.symbol in self.controls:
            self.set_cached_value(event.symbol, event.value)

    @classmethod
    def load_supported(
        cls,
        client: Client,
        uri: str,
        label: str,
        config: Config,
    ) -> Plugin | None:
        # Перевіряємо whitelist
        plugin_config = config.get_plugin_by_uri(uri)
        if not plugin_config:
            print(f"  Plugin {uri} not in whitelist, ignoring")
            return None

        plugin = cls(
            client=client,  # Буде встановлено після створення Slot
            uri=uri,
            label=label,
            config=plugin_config,
            filter_gui_controls=config.rack.filter_gui_controls,
        )
        return plugin

    def _load_plugin_ports(self, filter_gui_controls: bool = False) -> None:
        """Load and filter plugin ports from effect data.
        Load control metadata from effect_get response.

        Args:
            label: Plugin label for graph paths
            effect_data: Data from effect_get API

        Returns:
            Tuple of (inputs, outputs) Port lists
        """
        # Parse all ports from effect data

        ports: dict[str, dict] = self._effect_data.get("ports", {})

        config = self._config
        label = self.label

        def _get_ports(port_type: str, direction: str):
            try:
                ports_: dict = ports[port_type]
            except KeyError:
                return []
            
            found = []
            for p in ports_.get(direction, []):
                if config is not None and p["symbol"] in config.disable_ports:
                    continue
                try:
                    found.append(
                        Port(
                            symbol=p["symbol"],
                            name=p.get("name", p["symbol"]),
                            graph_path=f"{label}/{p['symbol']}",
                            port_type=PortType(port_type),
                            direction=PortDirection.INPUT
                            if direction == "input"
                            else PortDirection.OUTPUT,
                        )
                    )
                except ValueError as err:
                    print(f"Can't parse port_type or directio: {err}")
            return found

        self.audio_inputs = _get_ports("audio", "input")
        self.audio_outputs = _get_ports("audio", "output")
        self.midi_inputs = _get_ports("midi", "input")
        self.midi_outputs = _get_ports("midi", "output")
        self.cv_inputs = _get_ports("cv", "input")
        self.cv_outputs = _get_ports("cv", "output")

        print(
            f"Parsed audio ports: inputs={self.audio_inputs}, outputs={self.audio_outputs}"
        )
        print(
            f"Parsed midi ports: inputs={self.midi_inputs}, outputs={self.midi_outputs}"
        )
        print(f"Parsed cv ports: inputs={self.cv_inputs}, outputs={self.cv_inputs}")

        controls = parse_control_ports(
            self.label, self._effect_data, filter_gui_controls=filter_gui_controls
        )
        self._controls = {c.symbol: c for c in controls}

        print(f"Parsed controls: {self._controls}")

    # --- Dict-like access to control values ---

    @property
    def controls(self):
        return self._controls

    def keys(self):
        return self._controls.keys()

    def values(self):
        return self._controls.values()

    def items(self):
        return self._controls.items()

    def __getitem__(self, symbol: str) -> ControlPort:
        """Get current cached control value."""
        if symbol not in self._controls:
            raise KeyError(
                f"Control '{symbol}' not found. Available: {list(self._controls.keys())}"
            )
        return self._controls[symbol]

    def __contains__(self, symbol: str) -> bool:
        return symbol in self._controls

    def __iter__(self) -> Iterator[str]:
        return iter(self._controls)

    # --- Convenience methods ---

    @property
    def bypassed(self) -> bool:
        """Whether plugin is currently bypassed."""
        return self._bypassed

    def bypass(self, bypass: bool = True) -> bool:
        """Enable/disable bypass for this plugin. Set bypass via Client API."""
        self.client.ws.effect_bypass(self.label, bypass)
        return self.client.effect_bypass(self.label, bypass)

    def param_set(self, symbol: str, value: float) -> bool:
        """Set parameter via Client API."""
        if symbol not in self._controls:
            raise KeyError(
                f"Control '{symbol}' not found. Available: {list(self._controls.keys())}"
            )

        # Sync to API via POST
        self.client.ws.effect_param_set(self.label, symbol, value)
        return self.client.effect_param_set(self.label, symbol, value)

    def set_cached_value(self, symbol: str, value: float) -> None:
        """Set control value locally without API call (for WS sync)."""
        if symbol in self._controls:
            self._controls[symbol].value = value

    def __repr__(self) -> str:
        items = [f"{k}={v.format_value()}" for k, v in self._controls.items()]
        return f"Plugin({self.label}, controls={', '.join(items)})"
