from __future__ import annotations
from enum import Enum
from typing import Literal
from typing_extensions import Self
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pathlib import Path

__all__ = [
    "PortType",
    "PortDirection",
    "Stability",
    "ControlProperty",
    "Author",
    "GuiPort",
    "Gui",
    "Ranges",
    "Units",
    "ScalePoint",
    "Port",
    "PortGroup",
    "Ports",
    "ParameterRanges",
    "Parameter",
    "Preset",
    "Effect",
]


class PortType(str, Enum):
    AUDIO = "audio"
    MIDI = "midi"
    CV = "cv"
    CONTROL = "control"
    UNKNOWN = "unknown"


class PortDirection(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    UNKNOWN = "unknown"

    @staticmethod
    def from_int(v: int):
        match v:
            case 0:
                return PortDirection.INPUT
            case 1:
                return PortDirection.OUTPUT
            case _:
                return PortDirection.UNKNOWN


class Stability(str, Enum):
    STABLE = "stable"
    TESTING = "testing"
    UNSTABLE = "unstable"
    EXPERIMENTAL = "experimental"


ControlProperty = (
    Literal[
        "toggled",  # On/off switch (0.0 or 1.0)
        "integer",  # Discrete integer values
        "logarithmic",  # Logarithmic scale
        "enumeration",  # Selector with scale points
        "trigger",  # Momentary button (resets to default)
        "hasStrictBounds",  # Value must stay within min/max
        "notOnGUI",  # Hidden from GUI
    ]
    | str
)


class Author(BaseModel):
    name: str
    homepage: str = ""
    email: str = ""


class GuiPort(BaseModel):
    valid: bool = True
    index: int
    name: str
    symbol: str


class Gui(BaseModel):
    resourcesDirectory: str = ""
    iconTemplate: str = ""
    settingsTemplate: str = ""
    javascript: str = ""
    stylesheet: str = ""
    screenshot: str = ""
    thumbnail: str = ""
    discussionURL: str = ""
    documentation: str = ""
    brand: str = ""
    label: str = ""
    model: str = ""
    panel: str = ""
    color: str = ""
    knob: str = ""
    ports: list[GuiPort] = Field(default_factory=list)
    monitoredOutputs: list[str] = Field(default_factory=list)


class Ranges(BaseModel):
    minimum: float = 0.0
    maximum: float = 0.0
    default: float = 0.0


class Units(BaseModel):
    label: str = ""
    render: str = ""
    symbol: str = ""
    custom: bool = Field(default=False, alias="_custom")


class ScalePoint(BaseModel):
    valid: bool = True
    value: float
    label: str


class Port(BaseModel):
    model_config: ConfigDict = ConfigDict(arbitrary_types_allowed=True)

    valid: bool = True
    index: int
    name: str
    symbol: str
    shortName: str = ""
    ranges: Ranges | None = None
    units: Units | None = None
    comment: str = ""
    designation: str = ""
    properties: list[ControlProperty] = Field(default_factory=list)
    rangeSteps: int = 0
    scalePoints: list[ScalePoint] = Field(default_factory=list)

    # Back-references populated by Effect.model_validator (excluded from serialization)
    effect: Effect | None = Field(default=None, exclude=True)
    port_type: PortType = Field(default=PortType.UNKNOWN, exclude=True)
    direction: PortDirection = Field(default=PortDirection.UNKNOWN, exclude=True)

    @property
    def graph_path(self) -> str:
        if self.effect is None:
            return self.symbol
        return f"{self.effect.label}/{self.symbol}"


class PortGroup(BaseModel):
    input: list[Port] = Field(default_factory=list)
    output: list[Port] = Field(default_factory=list)


class Ports(BaseModel):
    audio: PortGroup = Field(default_factory=PortGroup)
    control: PortGroup = Field(default_factory=PortGroup)
    cv: PortGroup = Field(default_factory=PortGroup)
    midi: PortGroup = Field(default_factory=PortGroup)


class ParameterRanges(BaseModel):
    minimum: str = ""
    maximum: str = ""
    default: str = ""


class Parameter(BaseModel):
    valid: bool = True
    readable: bool = False
    writable: bool = True
    uri: str
    label: str
    type: str = ""
    ranges: ParameterRanges | None = None
    units: Units | None = None
    comment: str = ""
    shortName: str = ""
    fileTypes: list[str] = Field(default_factory=list)
    supportedExtensions: list[str] = Field(default_factory=list)


class Preset(BaseModel):
    valid: bool = True
    uri: str
    label: str
    path: str = ""


class Effect(BaseModel):
    valid: bool = True
    uri: str
    name: str
    binary: Path | None = None
    brand: str = ""
    label: str = ""
    license: str = ""
    comment: str = ""
    buildEnvironment: str = ""
    category: list[str] = Field(default_factory=list)
    microVersion: int = 0
    minorVersion: int = 0
    release: int = 0
    builder: int = 0
    licensed: int = 0
    iotype: int = 0
    hasExternalUI: bool = False
    version: str = ""
    stability: str = "stable"
    author: Author | None = None
    bundles: list[str] = Field(default_factory=list)
    gui: Gui | None = None
    ports: Ports = Field(default_factory=Ports)
    parameters: list[Parameter] = Field(default_factory=list)
    presets: list[Preset] = Field(default_factory=list)

    @model_validator(mode="after")
    def populate_port_refs(self) -> Self:
        """Populate back-references on all ports."""
        port_groups = [
            (PortType.AUDIO, self.ports.audio),
            (PortType.CONTROL, self.ports.control),
            (PortType.CV, self.ports.cv),
            (PortType.MIDI, self.ports.midi),
        ]
        for port_type, group in port_groups:
            for port in group.input:
                port.effect = self
                port.port_type = port_type
                port.direction = PortDirection.INPUT
            for port in group.output:
                port.effect = self
                port.port_type = port_type
                port.direction = PortDirection.OUTPUT
        return self
