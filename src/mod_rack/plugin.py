"""
Plugin model with control management.

Plugin instances are created when loading into a Slot and provide
dict-like access to control parameters with automatic API synchronization.
"""

from __future__ import annotations
from operator import attrgetter


from mod_rack.mod_client import (
    GraphOutputSetEvent,
    GraphParamSetBypassEvent,
    Client,
    GraphParamSetEvent,
)
from mod_rack.config import Config, PluginConfig
from mod_rack.controls import PortControl, parse_control_ports

from mod_rack.schema.effect import Effect, Port, Ports
from mod_rack.logger import logger

__all__ = ["Plugin"]


_log = logger.getChild(__name__)


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

        effect_data: dict = self.client.effect_get(self.uri)

        self._bypassed = False
        self._config = (
            config if config is not None else PluginConfig(self.label, self.uri)
        )

        self._effect = Effect.model_validate(effect_data)

        self.size: tuple[int, int] = self.client.effect_image_size(
            self.uri, "screenshot.png"
        )

        self._controls: dict[str, PortControl] = {}
        self._load_controls(filter_gui_controls)
        self._subscribe()

    @property
    def name(self) -> str:
        return self._effect.name

    @property
    def join_inputs(self) -> bool:
        return self._config.join_inputs

    @property
    def join_outputs(self) -> bool:
        return self._config.join_outputs

    @property
    def ports(self) -> Ports:
        return self._effect.ports

    @property
    def audio_inputs(self) -> list[Port]:
        return self._filter_and_sort_ports(self._effect.ports.audio.input)

    @property
    def audio_outputs(self) -> list[Port]:
        return self._filter_and_sort_ports(self._effect.ports.audio.output)

    @property
    def midi_inputs(self) -> list[Port]:
        return self._filter_and_sort_ports(self._effect.ports.midi.input)

    @property
    def midi_outputs(self) -> list[Port]:
        return self._filter_and_sort_ports(self._effect.ports.midi.output)

    @property
    def cv_inputs(self) -> list[Port]:
        return self._filter_and_sort_ports(self._effect.ports.cv.input)

    @property
    def cv_outputs(self) -> list[Port]:
        return self._filter_and_sort_ports(self._effect.ports.cv.output)

    @property
    def control_inputs(self) -> list[Port]:
        return self._filter_and_sort_ports(self._effect.ports.control.input)

    @property
    def control_outputs(self) -> list[Port]:
        return self._filter_and_sort_ports(self._effect.ports.control.output)

    def _filter_and_sort_ports(self, ports: list[Port]):
        disabled = set(self._config.disable_ports)  # O(1) lookup instead of O(n)
        return sorted(
            (p for p in ports if p.symbol not in disabled),
            key=attrgetter("index"),  # faster than lambda
        )

    def _subscribe(self) -> None:
        self.client.ws.on(GraphParamSetBypassEvent, self._on_bypass_change)
        self.client.ws.on(GraphParamSetEvent, self._on_control_change)
        self.client.ws.on(GraphOutputSetEvent, self._on_control_change)

    def _on_bypass_change(self, event: GraphParamSetBypassEvent) -> None:
        if self.label == event.label:
            self._bypassed = event.bypassed

    def _on_control_change(
        self, event: GraphParamSetEvent | GraphOutputSetEvent
    ) -> None:
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
        # Check whitelist
        plugin_config = config.get_plugin_by_uri(uri)
        if not plugin_config:
            _log.warning("[PLUGIN] Plugin not in whitelist, ignoring: %uri", uri)
            return None

        plugin = cls(
            client=client,  # Will be set after Slot creation
            uri=uri,
            label=label,
            config=plugin_config,
            filter_gui_controls=config.rack.filter_gui_controls,
        )
        return plugin

    def _load_controls(self, filter_gui_controls: bool = False) -> None:
        """Load and filter plugin ports from effect data.
        Load control metadata from effect_get response.
        """
        # Parse all ports from effect data

        controls = parse_control_ports(
            self.label, self._effect, filter_gui_controls=filter_gui_controls
        )
        self._controls = {
            c.symbol: c for c in sorted(controls, key=attrgetter("index"))
        }

    # --- Dict-like access to control values ---

    @property
    def controls(self) -> dict[str, PortControl]:
        return self._controls

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
