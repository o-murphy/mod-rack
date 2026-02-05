"""
PySide6 UI for MOD Rack control.

Run with: python qrack.py
"""

import logging
import re
import signal
import sys

from mod_rack.mod_client import (
    GraphOutputSetEvent,
    GraphParamSetBypassEvent,
    GraphParamSetEvent,
)
from mod_rack.plugin import Plugin
from mod_rack.service import RackWSServer, get_argparser
from mod_rack.schema.config import Config
from mod_rack.rack import Rack
from mod_rack.controls import PortControl
from mod_rack.mod_client import PortDirection
from mod_rack.rack import OrchestratorMode
from mod_rack.logger import logger

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QPushButton,
    QLabel,
    QDial,
    QComboBox,
    QCheckBox,
    QGroupBox,
    QScrollArea,
    QFrame,
    QDialog,
    QListWidget,
    QListWidgetItem,
    QDialogButtonBox,
    QLineEdit,
)
from PySide6.QtCore import Qt, Signal, QTimer, QRect, QSize, QPoint, QMimeData
from PySide6.QtGui import QPainter, QColor, QPolygon, QPen, QFont, QDrag, QPixmap


_log = logger.getChild(__name__)


# Color mapping for plugin categories
CATEGORY_COLORS = {
    "Reverb": "#5B9BD5",  # Blue
    "Delay": "#70AD47",  # Green
    "Distortion": "#C00000",  # Red
    "Filter": "#FFC000",  # Orange/Yellow
    "Modulator": "#7030A0",  # Purple
    "Chorus": "#7030A0",  # Purple
    "Phaser": "#9966CC",  # Light purple
    "Flanger": "#8B008B",  # Dark magenta
    "Dynamics": "#ED7D31",  # Orange
    "Compressor": "#ED7D31",  # Orange
    "Gate": "#C55A11",  # Dark orange
    "MIDI": "#00B0F0",  # Cyan
    "Utility": "#808080",  # Gray
    "Generator": "#00B050",  # Bright green
    "Instrument": "#00B050",  # Bright green
    "Simulator": "#BF8F00",  # Gold/Brown
    "ControlVoltage": "#FF6699",  # Pink
    "Spectral": "#9933FF",  # Violet
    "Pitch Shifter": "#9933FF",  # Violet
    "Spatial": "#00CED1",  # Dark turquoise
    "Equaliser": "#DAA520",  # Goldenrod
    "Waveshaper": "#DC143C",  # Crimson
    "Analyser": "#4682B4",  # Steel blue
    "Mixer": "#696969",  # Dim gray
}
DEFAULT_COLOR = "#A0A0A0"  # Default gray


def get_category_color(categories: list[str]) -> str:
    """Get color for first matching category."""
    for cat in categories:
        if cat in CATEGORY_COLORS:
            return CATEGORY_COLORS[cat]
    return DEFAULT_COLOR


def abbreviate_name(name: str) -> str:
    """Create abbreviated name: capital letters or first 4 chars."""
    # Extract capital letters (excluding first if it's the only capital)
    capitals = "".join(c for c in name if c.isupper())
    if len(capitals) >= 2:
        return capitals[:4]
    # Fall back to first 4 characters
    return name[:4]


class CableView(QWidget):
    """Visual representation of the effect chain as colored boxes on a cable."""

    slot_clicked = Signal(str)  # label
    add_clicked = Signal()  # add button clicked
    bypass_toggled = Signal(str, bool)  # label, new_bypassed_state
    remove_clicked = Signal(str)  # label - remove slot
    slot_dropped = Signal(str, int)  # source_label, destination_index

    BOX_WIDTH = 44
    BOX_HEIGHT = 88
    BOX_SPACING_MIN = 8
    BOX_SPACING_MAX = 40
    CABLE_HEIGHT = 4
    MARGIN = 16
    TOGGLE_SIZE = 16
    CLOSE_SIZE = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self._slots: list[dict] = []  # [{label, name, categories, selected}]
        self._hovered_index: int | None = None
        self._drag_start_pos = None
        self._dragging_index: int | None = None
        self._drop_indicator_index: int | None = None  # Where to show drop indicator
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setMinimumHeight(self.BOX_HEIGHT + self.MARGIN * 2)
        self.setMaximumHeight(self.BOX_HEIGHT + self.MARGIN * 2)

    def set_slots(self, slots: list[dict]):
        """Update slots data. Each dict: {label, name, categories, selected}"""
        self._slots = slots
        self.setMinimumWidth(self._get_content_width())
        self.updateGeometry()
        self.update()

    def set_selected(self, label: str | None):
        """Mark a slot as selected."""
        for slot in self._slots:
            slot["selected"] = slot["label"] == label
        self.update()

    def set_bypassed(self, label: str, bypassed: bool):
        """Update bypass state for a slot."""
        for slot in self._slots:
            if slot["label"] == label:
                slot["bypassed"] = bypassed
                self.update()
                break

    def _get_dynamic_spacing(self) -> int:
        """Calculate spacing based on available width."""
        num_slots = len(self._slots)
        if num_slots == 0:
            return self.BOX_SPACING_MIN

        num_items = num_slots + 1  # slots + add button
        min_content_width = num_items * self.BOX_WIDTH + num_slots * self.BOX_SPACING_MIN
        available_width = self.width() - self.MARGIN * 2

        if available_width <= min_content_width:
            return self.BOX_SPACING_MIN

        # Distribute extra space
        extra_space = available_width - min_content_width
        extra_per_gap = extra_space // num_slots if num_slots > 0 else 0
        return min(self.BOX_SPACING_MIN + extra_per_gap, self.BOX_SPACING_MAX)

    def _get_content_start_x(self) -> int:
        """Get x position to start content (for centering)."""
        num_slots = len(self._slots)
        num_items = num_slots + 1  # slots + add button
        spacing = self._get_dynamic_spacing()
        total_width = num_items * self.BOX_WIDTH + num_slots * spacing
        return max(self.MARGIN, (self.width() - total_width) // 2)

    def _get_add_button_x(self) -> int:
        """Get x position of the add button."""
        start_x = self._get_content_start_x()
        spacing = self._get_dynamic_spacing()
        return start_x + len(self._slots) * (self.BOX_WIDTH + spacing)

    def _get_content_width(self) -> int:
        """Get minimum width of content (slots + add button + margins)."""
        num_slots = len(self._slots)
        num_items = num_slots + 1  # slots + add button
        return num_items * self.BOX_WIDTH + num_slots * self.BOX_SPACING_MIN + self.MARGIN * 2

    def sizeHint(self):
        return QSize(self._get_content_width(), self.BOX_HEIGHT + self.MARGIN * 2)

    def minimumSizeHint(self):
        return QSize(self._get_content_width(), self.BOX_HEIGHT + self.MARGIN * 2)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()
        center_y = height // 2
        spacing = self._get_dynamic_spacing()

        # Draw cable (horizontal line)
        cable_color = QColor("#333333")
        painter.setPen(QPen(cable_color, self.CABLE_HEIGHT))
        painter.drawLine(0, center_y, width, center_y)

        # Center boxes horizontally
        start_x = self._get_content_start_x()

        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)

        y = center_y - self.BOX_HEIGHT // 2

        # Draw slot boxes
        for i, slot in enumerate(self._slots):
            x = start_x + i * (self.BOX_WIDTH + spacing)

            # Box color from category
            color = QColor(get_category_color(slot.get("categories", [])))

            # Draw box
            if slot.get("selected"):
                painter.setPen(QPen(QColor("#FFFFFF"), 3))
            else:
                painter.setPen(QPen(color.darker(150), 1))

            painter.setBrush(color)
            painter.drawRoundedRect(x, y, self.BOX_WIDTH, self.BOX_HEIGHT, 6, 6)

            # Draw abbreviated name (upper part)
            painter.setPen(QColor("#FFFFFF"))
            abbrev = abbreviate_name(slot.get("name", "?"))
            text_rect = QRect(x, y + 4, self.BOX_WIDTH, 30)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, abbrev)

            # Draw bypass toggle button (bottom) - clickable
            toggle_x = x + (self.BOX_WIDTH - self.TOGGLE_SIZE) // 2
            toggle_y = y + self.BOX_HEIGHT - self.TOGGLE_SIZE - 6

            # Toggle button style - outline circle
            painter.setPen(QPen(QColor("#FFFFFF"), 2))
            painter.setBrush(QColor("#00000000"))  # Transparent
            painter.drawEllipse(toggle_x, toggle_y, self.TOGGLE_SIZE, self.TOGGLE_SIZE)
            # Inner fill based on state - red when active (not bypassed)
            inner_margin = 4
            if not slot.get("bypassed"):
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#FF0000"))
                painter.drawEllipse(
                    toggle_x + inner_margin,
                    toggle_y + inner_margin,
                    self.TOGGLE_SIZE - inner_margin * 2,
                    self.TOGGLE_SIZE - inner_margin * 2,
                )

            # Draw close button (top right corner) - only on hover
            if i == self._hovered_index:
                close_x = x + self.BOX_WIDTH - self.CLOSE_SIZE - 2
                close_y = y + 2
                painter.setPen(QPen(QColor("#FFFFFF"), 1))
                painter.setBrush(QColor("#C00000"))
                painter.drawEllipse(close_x, close_y, self.CLOSE_SIZE, self.CLOSE_SIZE)
                # Draw X
                painter.setPen(QPen(QColor("#FFFFFF"), 2))
                xmargin = 4
                painter.drawLine(
                    close_x + xmargin,
                    close_y + xmargin,
                    close_x + self.CLOSE_SIZE - xmargin,
                    close_y + self.CLOSE_SIZE - xmargin,
                )
                painter.drawLine(
                    close_x + self.CLOSE_SIZE - xmargin,
                    close_y + xmargin,
                    close_x + xmargin,
                    close_y + self.CLOSE_SIZE - xmargin,
                )

        # Draw add button (+) - square, centered vertically
        add_x = self._get_add_button_x()
        add_size = self.BOX_WIDTH  # Square button
        add_y = center_y - add_size // 2
        add_color = QColor("#666666")  # Gray
        painter.setPen(QPen(add_color.darker(120), 2))
        painter.setBrush(add_color)
        painter.drawRoundedRect(add_x, add_y, add_size, add_size, 6, 6)

        # Draw + sign
        painter.setPen(QPen(QColor("#FFFFFF"), 3))
        plus_margin = 10
        painter.drawLine(
            add_x + plus_margin, add_y + add_size // 2, add_x + add_size - plus_margin, add_y + add_size // 2
        )
        painter.drawLine(
            add_x + add_size // 2, add_y + plus_margin, add_x + add_size // 2, add_y + add_size - plus_margin
        )

        # Draw drop indicator
        if self._drop_indicator_index is not None:
            indicator_x = start_x + self._drop_indicator_index * (self.BOX_WIDTH + spacing) - spacing // 2
            painter.setPen(QPen(QColor("#00AAFF"), 3))
            painter.drawLine(indicator_x, y - 4, indicator_x, y + self.BOX_HEIGHT + 4)
            # Draw triangles at top and bottom
            painter.setBrush(QColor("#00AAFF"))
            painter.setPen(Qt.PenStyle.NoPen)
            # Top triangle

            top_tri = QPolygon(
                [
                    QPoint(indicator_x - 6, y - 8),
                    QPoint(indicator_x + 6, y - 8),
                    QPoint(indicator_x, y - 2),
                ]
            )
            painter.drawPolygon(top_tri)
            # Bottom triangle
            bot_tri = QPolygon(
                [
                    QPoint(indicator_x - 6, y + self.BOX_HEIGHT + 8),
                    QPoint(indicator_x + 6, y + self.BOX_HEIGHT + 8),
                    QPoint(indicator_x, y + self.BOX_HEIGHT + 2),
                ]
            )
            painter.drawPolygon(bot_tri)

    def mousePressEvent(self, event):
        """Handle click on a slot box, toggle, or add button."""
        click_x = event.position().x()
        click_y = event.position().y()
        start_x = self._get_content_start_x()
        spacing = self._get_dynamic_spacing()
        center_y = self.height() // 2
        y = center_y - self.BOX_HEIGHT // 2

        # Reset drag state
        self._drag_start_pos = None
        self._dragging_index = None

        # Check slot boxes
        for i, slot in enumerate(self._slots):
            x = start_x + i * (self.BOX_WIDTH + spacing)
            if x <= click_x <= x + self.BOX_WIDTH:
                # Check if click is on close button (top right)
                close_x = x + self.BOX_WIDTH - self.CLOSE_SIZE - 2
                close_y = y + 2
                if close_x <= click_x <= close_x + self.CLOSE_SIZE and close_y <= click_y <= close_y + self.CLOSE_SIZE:
                    self.remove_clicked.emit(slot["label"])
                    return
                # Check if click is on toggle button
                toggle_x = x + (self.BOX_WIDTH - self.TOGGLE_SIZE) // 2
                toggle_y = y + self.BOX_HEIGHT - self.TOGGLE_SIZE - 6
                if (
                    toggle_x <= click_x <= toggle_x + self.TOGGLE_SIZE
                    and toggle_y <= click_y <= toggle_y + self.TOGGLE_SIZE
                ):
                    # Toggle bypass
                    new_state = not slot.get("bypassed", False)
                    self.bypass_toggled.emit(slot["label"], new_state)
                else:
                    # Select slot and prepare for potential drag
                    self.slot_clicked.emit(slot["label"])
                    self._drag_start_pos = event.position()
                    self._dragging_index = i
                return

        # Check add button (square, centered)
        add_x = self._get_add_button_x()
        add_size = self.BOX_WIDTH
        add_y = center_y - add_size // 2
        if add_x <= click_x <= add_x + add_size and add_y <= click_y <= add_y + add_size:
            self.add_clicked.emit()

    def mouseMoveEvent(self, event):
        """Track hover state and handle drag initiation."""
        pos_x = event.position().x()
        start_x = self._get_content_start_x()
        spacing = self._get_dynamic_spacing()

        # Handle drag initiation
        if (
            event.buttons() & Qt.MouseButton.LeftButton
            and self._drag_start_pos is not None
            and self._dragging_index is not None
        ):
            distance = (event.position() - self._drag_start_pos).manhattanLength()
            if distance >= QApplication.startDragDistance():
                self._start_drag()
                return

        # Track hover state for close button visibility
        new_hovered = None
        for i in range(len(self._slots)):
            x = start_x + i * (self.BOX_WIDTH + spacing)
            if x <= pos_x <= x + self.BOX_WIDTH:
                new_hovered = i
                break

        if new_hovered != self._hovered_index:
            self._hovered_index = new_hovered
            self.update()

    def _start_drag(self):
        """Initiate drag operation for the current slot."""
        if self._dragging_index is None or self._dragging_index >= len(self._slots):
            return

        slot = self._slots[self._dragging_index]
        label = slot["label"]

        drag = QDrag(self)
        mime = QMimeData()
        mime.setData("application/x-slot-label", label.encode("utf-8"))
        mime.setText(label)
        drag.setMimeData(mime)

        # Create a pixmap of the slot being dragged
        pix = QPixmap(self.BOX_WIDTH, self.BOX_HEIGHT)
        pix.fill(QColor(get_category_color(slot.get("categories", []))))
        drag.setPixmap(pix)

        QApplication.setOverrideCursor(Qt.CursorShape.ClosedHandCursor)
        drag.exec(Qt.DropAction.MoveAction)
        QApplication.restoreOverrideCursor()

        # Reset drag state
        self._drag_start_pos = None
        self._dragging_index = None

    def leaveEvent(self, event):
        """Clear hover state when mouse leaves widget."""
        if self._hovered_index is not None:
            self._hovered_index = None
            self.update()

    def dragEnterEvent(self, event):
        """Accept drag if it contains slot label data."""
        mime = event.mimeData()
        if mime.hasFormat("application/x-slot-label") or mime.hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        """Accept drag move and update drop indicator."""
        mime = event.mimeData()
        if mime.hasFormat("application/x-slot-label") or mime.hasText():
            event.acceptProposedAction()

            # Auto-scroll when near edges
            scroll_area = self.parent().parent() if self.parent() else None
            if scroll_area and hasattr(scroll_area, "horizontalScrollBar"):
                scrollbar = scroll_area.horizontalScrollBar()
                viewport = scroll_area.viewport()
                # Get position relative to viewport
                local_pos = self.mapTo(viewport, event.position().toPoint())
                edge_margin = 50
                scroll_step = 20

                if local_pos.x() < edge_margin:
                    scrollbar.setValue(scrollbar.value() - scroll_step)
                elif local_pos.x() > viewport.width() - edge_margin:
                    scrollbar.setValue(scrollbar.value() + scroll_step)

            # Update drop indicator position
            drop_x = event.position().x()
            start_x = self._get_content_start_x()
            spacing = self._get_dynamic_spacing()

            new_indicator = len(self._slots)  # Default to end
            for i in range(len(self._slots)):
                x = start_x + i * (self.BOX_WIDTH + spacing)
                slot_center = x + self.BOX_WIDTH // 2
                if drop_x < slot_center:
                    new_indicator = i
                    break

            if new_indicator != self._drop_indicator_index:
                self._drop_indicator_index = new_indicator
                self.update()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        """Clear drop indicator when drag leaves."""
        if self._drop_indicator_index is not None:
            self._drop_indicator_index = None
            self.update()

    def dropEvent(self, event):
        """Handle drop - reorder slots."""
        mime = event.mimeData()
        if not (mime.hasFormat("application/x-slot-label") or mime.hasText()):
            event.ignore()
            return

        # Clear drop indicator
        self._drop_indicator_index = None

        # Get source label
        if mime.hasFormat("application/x-slot-label"):
            src_label = bytes(mime.data("application/x-slot-label")).decode("utf-8")
        else:
            src_label = mime.text()

        # Find source index
        src_index = None
        for i, slot in enumerate(self._slots):
            if slot["label"] == src_label:
                src_index = i
                break

        if src_index is None:
            event.ignore()
            self.update()
            return

        # Find destination index based on drop position
        drop_x = event.position().x()
        start_x = self._get_content_start_x()
        spacing = self._get_dynamic_spacing()

        dest_index = len(self._slots)  # Default to end
        for i in range(len(self._slots)):
            x = start_x + i * (self.BOX_WIDTH + spacing)
            slot_center = x + self.BOX_WIDTH // 2
            if drop_x < slot_center:
                dest_index = i
                break

        # Adjust for removal when moving right
        if src_index < dest_index:
            dest_index -= 1

        if src_index == dest_index:
            event.ignore()
            self.update()
            return

        self.slot_dropped.emit(src_label, dest_index)
        event.acceptProposedAction()

    def wheelEvent(self, event):
        """Redirect vertical wheel to horizontal scroll."""
        # Parent is viewport, its parent is QScrollArea
        scroll_area = self.parent().parent() if self.parent() else None
        if scroll_area and hasattr(scroll_area, "horizontalScrollBar"):
            scrollbar = scroll_area.horizontalScrollBar()
            delta = event.angleDelta().y()
            scrollbar.setValue(scrollbar.value() - delta)
            event.accept()
        else:
            super().wheelEvent(event)


class ControlWidget(QWidget):
    """Base widget for a plugin control."""

    value_changed = Signal(str, float)  # symbol, value

    # Ignore incoming WS updates for this duration after a local change
    LOCAL_CHANGE_COOLDOWN_MS = 100

    def __init__(self, control: PortControl, parent=None):
        super().__init__(parent)
        self.control = control
        self._local_change_timer = QTimer(self)
        self._local_change_timer.setSingleShot(True)

    def set_value_silent(self, value: float):
        """Set value from server without emitting signal.
        Ignored while user is actively interacting (cooldown)."""
        if self._local_change_timer.isActive():
            return
        self._set_widget_value(value)

    def _set_widget_value(self, value: float):
        """Override in subclass."""
        pass

    def _emit_change(self, value: float):
        """Emit value change and start cooldown to ignore WS echo."""
        self._local_change_timer.start(self.LOCAL_CHANGE_COOLDOWN_MS)
        self.value_changed.emit(self.control.symbol, value)


class KnobControl(ControlWidget):
    """Slider control for continuous values."""

    SLIDER_STEPS = 1000

    def __init__(self, control: PortControl, parent=None):
        super().__init__(control, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Label
        self.label = QLabel(control.name)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)

        # Dial
        self.dial = QDial()
        self.dial.setNotchesVisible(True)
        self.dial.setNotchTarget(100.0)
        self.dial.setWrapping(False)
        self.dial.setRange(0, self.SLIDER_STEPS)
        self.dial.setValue(self._value_to_slider(control.value))
        self.dial.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self.dial)

        # Value display
        self.value_label = QLabel(control.format_value())
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.value_label)

    def _value_to_slider(self, value: float) -> int:
        """Convert actual value to slider position using normalize."""
        normalized = self.control.normalize(value)
        return int(normalized * self.SLIDER_STEPS)

    def _slider_to_value(self, pos: int) -> float:
        """Convert slider position to actual value using denormalize."""
        normalized = pos / self.SLIDER_STEPS
        return self.control.denormalize(normalized)

    def _on_slider_changed(self, pos: int):
        value = self._slider_to_value(pos)
        self.value_label.setText(self.control.format_value(value))
        self._emit_change(value)

    def _set_widget_value(self, value: float):
        self.dial.blockSignals(True)
        self.dial.setValue(self._value_to_slider(value))
        self.dial.blockSignals(False)
        self.value_label.setText(self.control.format_value(value))


class ToggleControl(ControlWidget):
    """Checkbox for toggle controls."""

    def __init__(self, control: PortControl, parent=None):
        super().__init__(control, parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.checkbox = QCheckBox(control.name)
        self.checkbox.setChecked(control.value >= 0.5)
        self.checkbox.stateChanged.connect(self._on_state_changed)
        layout.addWidget(self.checkbox)

    def _on_state_changed(self, state):
        value = 1.0 if state == Qt.Checked else 0.0
        self.control.value = value
        self._emit_change(value)

    def _set_widget_value(self, value: float):
        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(value >= 0.5)
        self.checkbox.blockSignals(False)


class EnumControl(ControlWidget):
    """ComboBox for enumeration controls."""

    def __init__(self, control: PortControl, parent=None):
        super().__init__(control, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Label
        self.label = QLabel(control.name)
        layout.addWidget(self.label)

        # ComboBox
        self.combo = QComboBox()
        for sp in control.scale_points:
            self.combo.addItem(sp.label, sp.value)

        # Set current value
        current_idx = self._value_to_index(control.value)
        if current_idx >= 0:
            self.combo.setCurrentIndex(current_idx)

        self.combo.currentIndexChanged.connect(self._on_index_changed)
        layout.addWidget(self.combo)

    def _value_to_index(self, value: float) -> int:
        for i, sp in enumerate(self.control.scale_points):
            if sp.value == value:
                return i
        return 0

    def _on_index_changed(self, index: int):
        if index >= 0:
            value = self.combo.itemData(index)
            self.control.value = value
            self._emit_change(value)

    def _set_widget_value(self, value: float):
        idx = self._value_to_index(value)
        if idx >= 0:
            self.combo.blockSignals(True)
            self.combo.setCurrentIndex(idx)
            self.combo.blockSignals(False)


class IntegerControl(ControlWidget):
    """Slider for integer controls (non-enum)."""

    def __init__(self, control: PortControl, parent=None):
        super().__init__(control, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Label
        self.label = QLabel(control.name)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)

        # Slider with integer steps
        self.dial = QDial()
        self.dial.setRange(int(control.minimum), int(control.maximum))
        self.dial.setValue(int(control.value))
        self.dial.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self.dial)

        # Value display
        self.value_label = QLabel(control.format_value())
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.value_label)

    def _on_slider_changed(self, value: int):
        self.value_label.setText(self.control.format_value(value))
        self._emit_change(float(value))

    def _set_widget_value(self, value: float):
        self.dial.blockSignals(True)
        self.dial.setValue(int(value))
        self.dial.blockSignals(False)
        self.value_label.setText(self.control.format_value(value))


class MeterControl(ControlWidget):
    """Read-only label for output controls (meters, indicators)."""

    def __init__(self, control: PortControl, parent=None):
        super().__init__(control, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Name label
        self.label = QLabel(control.name)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)

        # Value display (normalized 0.0-1.0)
        normalized = control.normalize(control.value)
        self.value_label = QLabel(f"{normalized:.2f}")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(self.value_label)

    def _set_widget_value(self, value: float):
        normalized = self.control.normalize(value)
        self.value_label.setText(f"{normalized:.2f}")


def create_control_widget(control: PortControl, parent=None) -> ControlWidget:
    """Factory function to create appropriate widget for control type."""
    # Output controls are read-only meters
    if control.direction == PortDirection.OUTPUT:
        return MeterControl(control, parent)
    if control.is_toggled:
        return ToggleControl(control, parent)
    if control.is_enumeration:
        return EnumControl(control, parent)
    if control.is_integer and not control.is_enumeration:
        return IntegerControl(control, parent)
    return KnobControl(control, parent)


class PluginSelectorDialog(QDialog):
    """Dialog to select a plugin from available effects."""

    def __init__(self, rack: Rack, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Plugin")
        self.setMinimumSize(400, 500)

        self.selected_uri = None

        layout = QVBoxLayout(self)

        # Filter input
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter by name, label, or category (supports regex)")
        self.filter_input.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self.filter_input)

        # Plugin list - show only whitelisted plugins
        self.list_widget = QListWidget()

        # Store plugin data for filtering
        self._plugins = []
        for p_config in rack.config.plugins:
            name = p_config.name
            uri = p_config.uri
            category = p_config.category or ["General"]
            label = getattr(p_config, "label", "") or ""
            self._plugins.append(
                {
                    "name": name,
                    "uri": uri,
                    "category": category,
                    "label": label,
                }
            )

        self._populate_list(self._plugins)

        self.list_widget.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.list_widget)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate_list(self, plugins: list[dict]):
        """Populate the list widget with given plugins."""
        self.list_widget.clear()
        for p in plugins:
            item = QListWidgetItem(f"{p['name']}\n  [{', '.join(p['category'])}]")
            item.setData(Qt.ItemDataRole.UserRole, p["uri"])
            self.list_widget.addItem(item)

    def _on_filter_changed(self, text: str):
        """Filter plugins by name, label, or category using regex or partial match."""
        if not text:
            self._populate_list(self._plugins)
            return

        # Try to compile as regex, fall back to case-insensitive substring match
        try:
            pattern = re.compile(text, re.IGNORECASE)
            use_regex = True
        except re.error:
            use_regex = False
            text_lower = text.lower()

        filtered = []
        for p in self._plugins:
            searchable = [
                p["name"] or "",
                p["label"] or "",
                *p["category"],
            ]
            match = False
            for field in searchable:
                if use_regex:
                    if pattern.search(field):
                        match = True
                        break
                else:
                    if text_lower in field.lower():
                        match = True
                        break
            if match:
                filtered.append(p)

        self._populate_list(filtered)

    def _on_double_click(self, item):
        self.selected_uri = item.data(Qt.UserRole)
        self.accept()

    def _on_accept(self):
        current = self.list_widget.currentItem()
        if current:
            self.selected_uri = current.data(Qt.UserRole)
        self.accept()


class ControlsPanel(QScrollArea):
    """Panel showing controls for selected plugin."""

    bypass_changed = Signal(str, bool)  # label, bypassed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.container = QWidget()
        self._layout = QVBoxLayout(self.container)
        self._layout.setAlignment(Qt.AlignTop)
        self.setWidget(self.container)

        self.plugin: Plugin | None = None
        self.current_label: str | None = None
        self.control_widgets: dict[str, ControlWidget] = {}
        self.bypass_checkbox: QCheckBox | None = None

        # Placeholder
        self.placeholder = QLabel("Select a plugin to see controls")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self._layout.addWidget(self.placeholder)

    def set_plugin(self, plugin: Plugin | None, label: str | None = None):
        """Set the plugin to display controls for."""
        # Clear existing
        self._clear_controls()
        self.plugin = plugin
        self.current_label = label

        if plugin is None:
            self.placeholder.setText("Select a plugin to see controls")
            self.placeholder.show()
            return

        self.placeholder.hide()

        # Plugin name and bypass
        header = QHBoxLayout()
        name_label = QLabel(f"<b>{plugin.name}</b>")
        header.addWidget(name_label)

        self.bypass_checkbox = QCheckBox("Bypass")
        # Set initial state from plugin
        bypassed = getattr(plugin, "_bypassed", False)
        self.bypass_checkbox.setChecked(bypassed)
        self.bypass_checkbox.toggled.connect(self._on_bypass_changed)
        header.addWidget(self.bypass_checkbox)

        header.addStretch()

        self._layout.addLayout(header)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        self._layout.addWidget(line)

        # Controls grid
        # ================================
        # OUTPUTS (top)
        # ================================
        outputs_group = QGroupBox("Outputs")
        outputs_grid = QGridLayout(outputs_group)

        out_row = out_col = 0
        max_cols = 10

        # ================================
        # INPUTS (bottom)
        # ================================
        inputs_group = QGroupBox("Controls")
        inputs_grid = QGridLayout(inputs_group)

        in_row = in_col = 0

        controls = plugin.controls.values()

        for control in controls:
            widget = create_control_widget(control)
            widget.value_changed.connect(self._on_control_changed)
            self.control_widgets[control.symbol] = widget

            if control.direction == PortDirection.OUTPUT:
                outputs_grid.addWidget(widget, out_row, out_col)
                out_col += 1
                if out_col >= max_cols:
                    out_col = 0
                    out_row += 1
            else:
                inputs_grid.addWidget(widget, in_row, in_col)
                in_col += 1
                if in_col >= max_cols:
                    in_col = 0
                    in_row += 1

        # Add frames in correct order
        if out_row or out_col:
            self._layout.addWidget(outputs_group)

        if in_row or in_col:
            self._layout.addWidget(inputs_group)

        self._layout.addStretch()

    def _clear_controls(self):
        """Remove all control widgets."""
        for widget in self.control_widgets.values():
            widget.deleteLater()
        self.control_widgets.clear()
        self.bypass_checkbox = None

        # Clear layout
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget() and item.widget() != self.placeholder:
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

        self._layout.addWidget(self.placeholder)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _on_control_changed(self, symbol: str, value: float):
        """Handle control value change."""
        if self.plugin:
            self.plugin.param_set(symbol, value)

    def set_bypass_silent(self, bypassed: bool):
        """Set bypass checkbox without emitting signal."""
        if self.bypass_checkbox:
            self.blockSignals(True)
            self.bypass_checkbox.setChecked(bypassed)
            self.blockSignals(False)

    def _on_bypass_changed(self, state):
        """Handle bypass checkbox change."""
        if self.plugin:
            self.plugin.bypass(state)
            if self.current_label:
                self.bypass_changed.emit(self.current_label, state)


class MainWindow(QMainWindow):
    """Main application window."""

    order_changed_signal = Signal(list)
    _param_changed_signal = Signal(str, str, float)  # label, symbol, value
    _bypass_changed_signal = Signal(str, bool)  # label, bypassed

    def __init__(self, rack: Rack):
        super().__init__()
        self.rack = rack
        self.selected_label: str | None = None

        # Connect rack callbacks to emit signals (WS thread → main thread)
        self.order_changed_signal.connect(self._rebuild_slot_widgets)
        self._param_changed_signal.connect(self._on_ws_param_changed)
        self._bypass_changed_signal.connect(self._on_ws_bypass_changed)
        self.rack.on_rack_order_changed(self._handle_rack_cb)
        self.rack.client.ws.on(GraphParamSetEvent, self._forward_control_event)
        self.rack.client.ws.on(GraphOutputSetEvent, self._forward_control_event)
        self.rack.client.ws.on(GraphParamSetBypassEvent, self._forward_bypass_event)

        self.setWindowTitle("MOD Rack Controller")
        self.setMinimumSize(800, 600)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # Cable visualization at top (with horizontal scroll)
        self.cable_scroll = QScrollArea()
        self.cable_scroll.setWidgetResizable(True)
        self.cable_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cable_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cable_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scrollbar_height = self.cable_scroll.horizontalScrollBar().sizeHint().height()
        self.cable_scroll.setMinimumHeight(CableView.BOX_HEIGHT + CableView.MARGIN * 2)
        self.cable_scroll.setMaximumHeight(CableView.BOX_HEIGHT + CableView.MARGIN * 2 + scrollbar_height)

        self.cable_view = CableView()
        self.cable_view.slot_clicked.connect(self._on_slot_clicked)
        self.cable_view.add_clicked.connect(self._on_add_plugin)
        self.cable_view.bypass_toggled.connect(self._on_cable_bypass_toggled)
        self.cable_view.remove_clicked.connect(self._on_remove_plugin)
        self.cable_view.slot_dropped.connect(self._on_slot_dropped)
        self.cable_scroll.setWidget(self.cable_view)
        main_layout.addWidget(self.cable_scroll)

        # Controls panel below
        self.controls_panel = ControlsPanel()
        self.controls_panel.bypass_changed.connect(self._on_local_bypass_changed)
        main_layout.addWidget(self.controls_panel, stretch=1)

        # Clear all button at bottom
        self.clear_all_btn = QPushButton("Clear All")
        self.clear_all_btn.clicked.connect(self._on_clear_all)
        main_layout.addWidget(self.clear_all_btn)

        self.rack.client.ws.connect()

    def _handle_rack_cb(self, slots: list):
        """This method executes in background Orchestrator thread."""
        # Just pass data to main thread via signal
        self.order_changed_signal.emit(slots)

    def _rebuild_slot_widgets(self):
        """Rebuild cable view from rack state."""
        # Build cable view data
        cable_slots = []
        for slot in self.rack.slots:
            cable_slots.append(
                {
                    "label": slot.label,
                    "name": slot.plugin.name,
                    "categories": slot.plugin._effect.category,
                    "selected": False,
                    "bypassed": slot.plugin._bypassed,
                }
            )

        # Update cable view
        self.cable_view.set_slots(cable_slots)

        # Update selection
        if self.selected_label and self.rack.get_slot_by_label(self.selected_label):
            self._select_slot(self.selected_label)
        elif self.rack.slots:
            self._select_slot(self.rack.slots[0].label)
        else:
            self.selected_label = None
            self.controls_panel.set_plugin(None)
            self.cable_view.set_selected(None)

    def _select_slot(self, label: str):
        """Select a slot and show its controls."""
        self.selected_label = label
        self.cable_view.set_selected(label)

        slot = self.rack.get_slot_by_label(label)
        if slot:
            self.controls_panel.set_plugin(slot.plugin, label)
        else:
            self.controls_panel.set_plugin(None)

    def _on_slot_clicked(self, label: str):
        """Handle slot click - select it."""
        self._select_slot(label)

    def _on_add_plugin(self):
        """Add a new plugin (request via REST, wait for WS feedback)."""
        dialog = PluginSelectorDialog(self.rack, self)
        if dialog.exec() == QDialog.Accepted and dialog.selected_uri:
            label = self.rack.request_add_plugin_at(dialog.selected_uri, len(self.rack.slots))
            if label:
                _log.debug("Requested add plugin, label=%s", label)
            else:
                _log.debug("Failed to request add plugin")

    def _on_remove_plugin(self, label: str):
        """Remove plugin (request via REST, wait for WS feedback)."""
        success = self.rack.request_remove_plugin(label)
        if success:
            _log.debug("Requested remove plugin %s", label)
        else:
            _log.debug("Failed to request remove plugin %s", label)

    def _on_replace_plugin(self, label: str):
        """Replace plugin - remove old, add new."""
        dialog = PluginSelectorDialog(self.rack, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_uri:
            # Preserve slot index: remove old, then request add at same index
            slot = self.rack.get_slot_by_label(label)
            insert_idx = self.rack.slots.index(slot) if slot else None
            # Request remove first
            self.rack.request_remove_plugin(label)
            # Request add at the same index (will be moved when WS feedback arrives)
            if insert_idx is not None:
                self.rack.request_add_plugin_at(dialog.selected_uri, insert_idx)
            else:
                self.rack.request_add_plugin(dialog.selected_uri)

            return

    def _on_clear_all(self):
        """Clear all plugins."""
        self.rack.clear()
        # update UI to reflect cleared state
        # self._rebuild_slot_widgets()
        QTimer.singleShot(100, self._rebuild_slot_widgets)

    def _on_slot_dropped(self, src_label: str, dest_index: int):
        """Handle drag-and-drop reorder: move src slot to dest index."""
        _log.debug("ON_SLOT_DROPPED: src_label=%s dest_index=%s", src_label, dest_index)
        src_slot = self.rack.get_slot_by_label(src_label)
        if not src_slot:
            return
        from_idx = self.rack.slots.index(src_slot)
        to_idx = dest_index
        _log.debug("ON_SLOT_DROPPED: from_idx=%s to_idx=%s", from_idx, to_idx)
        if from_idx == to_idx:
            return
        # Use rack.move_slot which handles reconnect
        self.rack.request_move_slot(from_idx, to_idx)
        # Rebuild UI to reflect new order and keep selection on moved slot
        self._rebuild_slot_widgets()
        self._select_slot(src_label)

    # =========================================================================
    # WebSocket event handlers (thread-safe via Qt signals)
    # =========================================================================

    def _forward_control_event(self, event: GraphParamSetEvent | GraphOutputSetEvent):
        """Forward WS event to main thread via signal."""
        self._param_changed_signal.emit(event.label, event.symbol, event.value)

    def _forward_bypass_event(self, event: GraphParamSetBypassEvent):
        """Forward WS event to main thread via signal."""
        self._bypass_changed_signal.emit(event.label, event.bypassed)

    def _on_ws_param_changed(self, label: str, symbol: str, value: float):
        """Handle parameter change in main thread."""
        if label == self.selected_label and symbol in self.controls_panel.control_widgets:
            widget = self.controls_panel.control_widgets[symbol]
            widget.set_value_silent(value)

    def _on_ws_bypass_changed(self, label: str, bypassed: bool):
        """Handle bypass change from WebSocket."""
        # Update cable view bypass indicator
        self.cable_view.set_bypassed(label, bypassed)

        if label == self.selected_label:
            self.controls_panel.set_bypass_silent(bypassed)

    def _on_local_bypass_changed(self, label: str, bypassed: bool):
        """Handle bypass change from local UI (checkbox)."""
        self.cable_view.set_bypassed(label, bypassed)

    def _on_cable_bypass_toggled(self, label: str, bypassed: bool):
        """Handle bypass toggle from cable view."""
        slot = self.rack.get_slot_by_label(label)
        if slot:
            slot.plugin.bypass(bypassed)
            self.cable_view.set_bypassed(label, bypassed)
            # Update controls panel checkbox if this is the selected slot
            if label == self.selected_label:
                self.controls_panel.set_bypass_silent(bypassed)

    def _on_rack_order_changed(self, order: list):
        """Handle order change from WebSocket - rebuild UI."""
        _log.debug("UI: Order changed: %s", order)
        self._rebuild_slot_widgets()

    def closeEvent(self, event):
        """Called when user closes window."""
        _log.debug("Closing rack connection...")
        event.accept()


def main():
    parser = get_argparser()
    ns = parser.parse_args()

    if ns.verbose:
        logger.setLevel(logging.DEBUG)

    config = Config.load(ns.config)

    # IMPORTANT: Make sure RackWSServer is imported
    # from your ws_server.py file
    # from mod_rack.ws_server import RackWSServer

    logger.info(f"Connecting to MOD server at {ns.server}...")

    # You used the name Orchestrator in previous files
    # If your class is named Rack, the logic remains the same
    mode = OrchestratorMode.OBSERVER if ns.slave else OrchestratorMode.MANAGER
    rack = Rack(ns.server, config, mode)

    # Start WebSocket server if flag is set
    if ns.rack_ws_port is not None:
        logger.info("Starting Rack WebSocket server on port %s...", ns.rack_ws_port)
        ws_server = RackWSServer(rack, port=ns.rack_ws_port)
        ws_server.start()  # Starts in background thread

    # Create and run app
    app = QApplication(sys.argv)

    # Handle Ctrl+C
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    window = MainWindow(rack)
    title = window.windowTitle()
    window.setWindowTitle(f"{title} ({'SLAVE' if ns.slave else 'MASTER'})")

    window.show()

    # Timer for signal handling (Ctrl+C)
    timer = QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    # Start GUI event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
