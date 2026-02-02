from enum import Enum
from pathlib import Path
from pydantic import BaseModel, Field

from mod_rack.logger import logger

try:
    import tomllib  # type: ignore[import-not-found]  # Python 3.11+
except ImportError:
    import tomli as tomllib  # pip install tomli for Python < 3.11


__all__ = [
    "PluginConfig",
    "HardwareConfig",
    "RoutingMode",
    "RackConfig",
    "Config",
]


_log = logger.getChild(__name__)


class PluginConfig(BaseModel):
    name: str
    uri: str
    category: list[str] = Field(default_factory=list)
    # Optional override for ports (for mono/stereo conversion)
    disable_ports: list[str] = Field(default_factory=list)
    # All-to-all routing: connect all inputs/outputs to each other
    join_inputs: bool = False
    join_outputs: bool = False


class HardwareConfig(BaseModel):
    # None = auto-detect from MOD-UI, list = override with specific ports
    disable_ports: list[str] = Field(default_factory=list)
    # All-to-all routing for hardware ports
    join_inputs: bool = False  # Join all hardware inputs to first plugin
    join_outputs: bool = False  # Join last plugin outputs to all hardware outputs


class RoutingMode(str, Enum):
    LINEAR = "linear"  # Strict 1->2->3 (with risk of breaks)
    # Each output looks for nearest next input (parallelism)
    HARD_BYPASS = "hard_bypass"
    TRIPPLE_TRACK = "tripple_track"  # Independent audio and MIDI chains
    PATCHBAY = "patchbay"  # Disable auto-routing completely


class RackConfig(BaseModel):
    # Maximum number of slots allowed (None = unlimited)
    routing_mode: RoutingMode = RoutingMode.HARD_BYPASS
    filter_gui_controls: bool = True


class Config(BaseModel):
    hardware: HardwareConfig = Field(default_factory=HardwareConfig)
    rack: RackConfig = Field(default_factory=RackConfig)
    plugins: list[PluginConfig] = Field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path = "config.toml") -> "Config":
        """Load configuration from TOML file"""
        path = Path(path)

        if not path.exists():
            _log.warning("[CONFIG] Config file %s not found, using defaults", path)
            return cls()

        with open(path, "r") as fp:
            data = fp.read()

        return cls.parse(data)

    @classmethod
    def parse(cls, data: str) -> "Config":
        parsed = tomllib.loads(data)
        return Config.model_validate(parsed)

    def get_plugin_by_name(self, name: str) -> PluginConfig | None:
        """Find plugin by name (case-insensitive)"""
        name_lower = name.lower()
        for plugin in self.plugins:
            if plugin.name.lower() == name_lower:
                return plugin
        return None

    def get_plugin_by_uri(self, uri: str) -> PluginConfig | None:
        """Find plugin by URI"""
        for plugin in self.plugins:
            if plugin.uri == uri:
                return plugin
        return None

    def is_supported(self, uri: str) -> bool:
        """Check if plugin is supported (exists in config)"""
        return self.get_plugin_by_uri(uri) is not None

    def get_plugins_by_category(self, category: str) -> list[PluginConfig]:
        """Get all plugins of specific category"""
        return [p for p in self.plugins if category in p.category]

    def list_categories(self) -> list[str]:
        """Get list of all categories"""
        categories = set()
        for p in self.plugins:
            for category in p.category:
                if category not in categories:
                    categories.add(category)
        return sorted(categories)
