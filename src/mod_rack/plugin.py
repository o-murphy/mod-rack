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

        # io setup
        self.ports: dict[PortType, list[Port | ControlPort]] = {
            PortType.AUDIO: [],
            PortType.MIDI: [],
            PortType.CV: [],
            PortType.CONTROL: [],
        }
        self._controls: dict[str, ControlPort] = {}

        # configuration
        self.join_inputs: bool = config.join_inputs if config is not None else False
        self.join_outputs: bool = config.join_outputs if config is not None else False

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
        """
        ports_info: dict[str, dict] = self._effect_data.get("ports", {})
        label = self.label

        def _get_by_type(pt_str: str, direction_str: str):
            # Отримуємо список портів з JSON: ports_info['audio']['input'] і т.д.
            type_data = ports_info.get(pt_str, {})
            raw_ports = type_data.get(direction_str, [])

            found_ports = []
            for p in raw_ports:
                # Перевірка на відключені порти в конфігу (як у вашому оригіналі)
                if self._config and p["symbol"] in self._config.disable_ports:
                    continue

                graph_path = f"{label}/{p['symbol']}"

                if pt_str == "control":
                    # Спеціальна обробка для ControlPort
                    if filter_gui_controls and "notOnGUI" in p.get("properties", []):
                        continue

                    # Використовуємо існуючу функцію parse_control_ports або direct ініціалізацію
                    ctrl = ControlPort.from_dict(
                        p,
                        graph_path=graph_path,
                        port_type=PortType.CONTROL,
                        direction=PortDirection.INPUT
                        if direction_str == "input"
                        else PortDirection.OUTPUT,
                    )
                    found_ports.append(ctrl)
                else:
                    # Звичайні Audio/MIDI/CV порти
                    found_ports.append(
                        Port(
                            symbol=p["symbol"],
                            name=p.get("name", p["symbol"]),
                            graph_path=graph_path,
                            port_type=PortType(pt_str),
                            direction=PortDirection.INPUT
                            if direction_str == "input"
                            else PortDirection.OUTPUT,
                        )
                    )
            return found_ports

        # Проходимо по всіх типах портів
        for pt_name in ["audio", "midi", "cv", "control"]:
            try:
                pt_enum = PortType(pt_name)
                inputs = _get_by_type(pt_name, "input")
                outputs = _get_by_type(pt_name, "output")

                # Зберігаємо все в один словник
                self.ports[pt_enum] = inputs + outputs

                # # Якщо це контролі, також оновлюємо self._controls для швидкого доступу за символом
                if pt_enum == PortType.CONTROL:
                    self._controls = {c.symbol: c for c in inputs}

            except ValueError as err:
                print(f"Skipping unknown port type {pt_name}: {err}")

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
