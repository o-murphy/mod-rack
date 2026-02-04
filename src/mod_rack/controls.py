"""
Control port models for MOD Audio plugins.

Provides typed dataclasses for plugin control ports with support for:
- Knobs (continuous, logarithmic)
- Toggles (on/off switches)
- Enumerations (selectors with scale points)
- Triggers (momentary buttons)
- Integer controls (discrete steps)
"""

import math
from dataclasses import dataclass, field

from mod_rack.schema.effect import (
    Effect,
    ScalePoint,
    Units,
    PortDirection,
    Port,
    PortType,
)


__all__ = [
    "ScalePoint",
    "Units",
    "PortControl",
    "parse_control_ports",
]


@dataclass(slots=True)
class PortControl:
    """
    A plugin control port with full metadata.

    Supports various control types:
    - Knob: continuous value with min/max/default
    - Toggle: on/off (toggled property, values 0.0/1.0)
    - Selector: enumeration with scale_points
    - Trigger: momentary button that resets to default
    """

    port: Port
    port_type: PortType
    direction: PortDirection

    # Runtime state (mutable)
    _value: float | None = field(default=None, repr=False)

    @property
    def index(self) -> int:
        return self.port.index

    @property
    def name(self) -> str:
        return self.port.name

    @property
    def symbol(self) -> str:
        return self.port.symbol

    @property
    def properties(self) -> list[str]:
        return self.port.properties

    @property
    def default(self) -> float:
        if self.port.ranges:
            return self.port.ranges.default
        return 0.0

    @property
    def maximum(self) -> float:
        if self.port.ranges:
            return self.port.ranges.maximum
        return 0.0

    @property
    def minimum(self) -> float:
        if self.port.ranges:
            return self.port.ranges.minimum
        return 0.0

    @property
    def units(self) -> Units | None:
        return self.port.units

    @property
    def range_steps(self) -> int:
        return self.port.rangeSteps

    @property
    def scale_points(self) -> list[ScalePoint]:
        return self.port.scalePoints

    @property
    def value(self) -> float:
        """Current value (default if not set)."""
        return self._value if self._value is not None else self.default

    @value.setter
    def value(self, val: float) -> None:
        """Set value with bounds checking."""
        self._value = self.clamp(val)

    # --- Type checks ---

    @property
    def is_toggled(self) -> bool:
        """Is this an on/off switch?"""
        return "toggled" in self.properties

    @property
    def is_integer(self) -> bool:
        """Does this use discrete integer values?"""
        return "integer" in self.properties

    @property
    def is_logarithmic(self) -> bool:
        """Does this use logarithmic scaling?"""
        return "logarithmic" in self.properties

    @property
    def is_enumeration(self) -> bool:
        """Is this a selector with named options?"""
        return "enumeration" in self.properties

    @property
    def is_trigger(self) -> bool:
        """Is this a momentary trigger button?"""
        return "trigger" in self.properties

    @property
    def is_continuous(self) -> bool:
        """Is this a continuous knob (not toggle/enum/trigger)?"""
        return not (self.is_toggled or self.is_enumeration or self.is_trigger)

    # --- Value helpers ---

    def clamp(self, val: float) -> float:
        """Clamp value to valid range, respecting integer and rangeSteps."""
        clamped = max(self.minimum, min(self.maximum, val))

        # Quantize to discrete steps if rangeSteps > 0
        if self.range_steps > 1:
            step_size = (self.maximum - self.minimum) / (self.range_steps - 1)
            steps = round((clamped - self.minimum) / step_size)
            clamped = self.minimum + steps * step_size

        # Round to integer if integer property
        if self.is_integer:
            clamped = round(clamped)

        return clamped

    def normalize(self, val: float | None = None) -> float:
        """
        Get value as 0.0-1.0 normalized range.
        For logarithmic controls, applies log scaling.
        """
        v = val if val is not None else self.value
        if self.maximum == self.minimum:
            return 0.0

        if self.is_logarithmic and self.minimum > 0:
            # Log scaling: normalized = log(v/min) / log(max/min)
            return math.log(v / self.minimum) / math.log(self.maximum / self.minimum)

        return (v - self.minimum) / (self.maximum - self.minimum)

    def denormalize(self, normalized: float) -> float:
        """
        Convert 0.0-1.0 normalized value to actual range.
        For logarithmic controls, applies exponential scaling.
        """
        normalized = max(0.0, min(1.0, normalized))

        if self.is_logarithmic and self.minimum > 0:
            # Exponential scaling: v = min * (max/min)^normalized
            val = self.minimum * math.pow(self.maximum / self.minimum, normalized)
        else:
            val = self.minimum + normalized * (self.maximum - self.minimum)

        return self.clamp(val)

    def get_scale_point_label(self, val: float | None = None) -> str | None:
        """Get label for current value if enumeration."""
        if not self.scale_points:
            return None
        v = val if val is not None else self.value
        for sp in self.scale_points:
            if sp.value == v:
                return sp.label
        return None

    def format_value(self, val: float | None = None) -> str:
        """Format value for display with units."""
        v = val if val is not None else self.value

        # Enumeration: show label
        if self.is_enumeration:
            label = self.get_scale_point_label(v)
            if label:
                return label

        # Toggle: show On/Off
        if self.is_toggled:
            return "On" if v >= 0.5 else "Off"

        # Numeric with units
        if self.is_integer:
            formatted = str(int(v))
        else:
            formatted = f"{v:.2f}".rstrip("0").rstrip(".")

        if self.units:
            return f"{formatted} {self.units.symbol}"
        return formatted


def parse_control_ports(
    plugin_label: str, effect: Effect, *, filter_gui_controls: bool = True
) -> list[PortControl]:
    """
    Parse all control input ports from effect_get response.

    Args:
        effect_data: Full response from /effect/get API

    Returns:
        List of ControlPort objects for all control inputs
    """
    control_ports = effect.ports.control
    inputs = control_ports.input
    outputs = control_ports.output

    def _filter_gui_controls(controls_list: list[Port]):
        return [
            control for control in controls_list if "notOnGUI" not in control.properties
        ]

    if filter_gui_controls:
        inputs = _filter_gui_controls(inputs)
        outputs = _filter_gui_controls(outputs)

    controls = []

    controls.extend(
        [
            PortControl(
                port_data,
                port_type=PortType.CONTROL,
                direction=PortDirection.INPUT,
            )
            for port_data in inputs
            if port_data.valid
        ]
    )

    controls.extend(
        [
            PortControl(
                port_data,
                port_type=PortType.CONTROL,
                direction=PortDirection.OUTPUT,
            )
            for port_data in outputs
            if port_data.valid
        ]
    )

    return controls
