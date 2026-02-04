import sys
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QVBoxLayout,
    QWidget,
    QSlider,
    QLabel,
    QCheckBox,
)
from PySide6.QtCore import Qt
from mod_rack.examples.rack_client_qt import RackWSClient


class MainWindow(QMainWindow):
    def __init__(self, client):
        super().__init__()
        self.client = client
        self.setWindowTitle("MOD Rack - Thin Client")
        self.slots = []

        # UI Layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        # Connect client signals to GUI
        self.client.order_changed.connect(self.rebuild_ui)
        self.client.param_changed.connect(self.on_remote_param_change)
        self.client.bypass_changed.connect(self.on_remote_bypass_change)

    def rebuild_ui(self, slots):
        self.slots = slots
        # Clear layout
        for i in reversed(range(self.layout.count())):
            self.layout.itemAt(i).widget().setParent(None)

        for slot in slots:
            label = QLabel(f"<b>{slot['label']}</b>")
            self.layout.addWidget(label)

            # Bypass button
            cb = QCheckBox("Bypass")
            cb.setChecked(slot.get("bypassed", False))
            cb.stateChanged.connect(
                lambda state, lbl=slot["label"]: self.client.send_cmd(
                    {"cmd": "bypass", "label": lbl, "bypassed": bool(state)}
                )
            )
            self.layout.addWidget(cb)

            # Sliders for parameters
            for ctrl in slot.get("controls", []):
                if ctrl["direction"] == "INPUT":
                    self.layout.addWidget(QLabel(f"{ctrl['name']}:"))
                    slider = QSlider(Qt.Horizontal)
                    slider.setRange(0, 1000)
                    # Convert value to slider position
                    val = int(
                        (ctrl["value"] - ctrl["minimum"])
                        / (ctrl["maximum"] - ctrl["minimum"])
                        * 1000
                    )
                    slider.setValue(val)

                    # On change - send command to server
                    slider.valueChanged.connect(
                        lambda v,
                        lbl=slot["label"],
                        s=ctrl["symbol"],
                        min_v=ctrl["minimum"],
                        max_v=ctrl["maximum"]: self.client.send_cmd(
                            {
                                "cmd": "param",
                                "label": lbl,
                                "symbol": s,
                                "value": min_v + (v / 1000) * (max_v - min_v),
                            }
                        )
                    )
                    self.layout.addWidget(slider)

    def on_remote_param_change(self, label, symbol, value):
        # Here you can find needed slider and update it,
        # so GUI reflects changes from MicroPython or another GUI
        print(f"Remote change: {label} {symbol} = {value}")

    def on_remote_bypass_change(self, label, bypassed):
        print(f"Remote bypass: {label} = {bypassed}")


def main():
    app = QApplication(sys.argv)

    # Create and start client
    client = RackWSClient("localhost", 9000)
    if not client.connect_server():
        print("Could not connect to service.py! Make sure it is running.")
        sys.exit(1)

    window = MainWindow(client)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
