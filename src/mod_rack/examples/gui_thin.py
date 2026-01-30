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

        # Підключення сигналів клієнта до GUI
        self.client.order_changed.connect(self.rebuild_ui)
        self.client.param_changed.connect(self.on_remote_param_change)
        self.client.bypass_changed.connect(self.on_remote_bypass_change)

    def rebuild_ui(self, slots):
        self.slots = slots
        # Очистка лейауту
        for i in reversed(range(self.layout.count())):
            self.layout.itemAt(i).widget().setParent(None)

        for slot in slots:
            label = QLabel(f"<b>{slot['label']}</b>")
            self.layout.addWidget(label)

            # Кнопка Bypass
            cb = QCheckBox("Bypass")
            cb.setChecked(slot.get("bypassed", False))
            cb.stateChanged.connect(
                lambda state, lbl=slot["label"]: self.client.send_cmd(
                    {"cmd": "set_bypass", "label": lbl, "bypassed": bool(state)}
                )
            )
            self.layout.addWidget(cb)

            # Слайдери для параметрів
            for ctrl in slot.get("controls", []):
                if ctrl["direction"] == "INPUT":
                    self.layout.addWidget(QLabel(f"{ctrl['name']}:"))
                    slider = QSlider(Qt.Horizontal)
                    slider.setRange(0, 1000)
                    # Конвертація значення в позицію слайдера
                    val = int(
                        (ctrl["value"] - ctrl["minimum"])
                        / (ctrl["maximum"] - ctrl["minimum"])
                        * 1000
                    )
                    slider.setValue(val)

                    # При зміні - надсилаємо команду на сервер
                    slider.valueChanged.connect(
                        lambda v,
                        lbl=slot["label"],
                        s=ctrl["symbol"],
                        min_v=ctrl["minimum"],
                        max_v=ctrl["maximum"]: self.client.send_cmd(
                            {
                                "cmd": "set_param",
                                "label": lbl,
                                "symbol": s,
                                "value": min_v + (v / 1000) * (max_v - min_v),
                            }
                        )
                    )
                    self.layout.addWidget(slider)

    def on_remote_param_change(self, label, symbol, value):
        # Тут можна знайти потрібний слайдер і оновити його,
        # щоб GUI відображав зміни від MicroPython або іншого GUI
        print(f"Remote change: {label} {symbol} = {value}")

    def on_remote_bypass_change(self, label, bypassed):
        print(f"Remote bypass: {label} = {bypassed}")


def main():
    app = QApplication(sys.argv)

    # Створюємо і запускаємо клієнт
    client = RackWSClient("localhost", 9000)
    if not client.connect_server():
        print("Could not connect to service.py! Make sure it is running.")
        sys.exit(1)

    window = MainWindow(client)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
