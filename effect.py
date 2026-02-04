from typing import Literal, Optional
from pydantic import BaseModel, Field
from pathlib import Path


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
    valid: bool = True
    index: int
    name: str
    symbol: str
    shortName: str = ""
    ranges: Optional[Ranges] = None
    units: Optional[Units] = None
    comment: str = ""
    designation: str = ""
    properties: list[str] = Field(default_factory=list)
    rangeSteps: int = 0
    scalePoints: list[ScalePoint] = Field(default_factory=list)


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
    ranges: Optional[ParameterRanges] = None
    units: Optional[Units] = None
    comment: str = ""
    shortName: str = ""
    fileTypes: list[str] = Field(default_factory=list)
    supportedExtensions: list[str] = Field(default_factory=list)


class Preset(BaseModel):
    valid: bool = True
    uri: str
    label: str
    path: str = ""


PortType = Literal["audio", "midi", "cv", "control"]
PortDirection = Literal["input", "output"]
Stability = Literal["stable", "testing", "unstable", "experimental"]


class Effect(BaseModel):
    valid: bool = True
    uri: str
    name: str
    binary: Optional[Path] = None
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
    author: Optional[Author] = None
    bundles: list[str] = Field(default_factory=list)
    gui: Optional[Gui] = None
    ports: Ports = Field(default_factory=Ports)
    parameters: list[Parameter] = Field(default_factory=list)
    presets: list[Preset] = Field(default_factory=list)
