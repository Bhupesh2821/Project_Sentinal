"""Measured statistics only; no estimated processor utilization."""
from PySide6.QtWidgets import QFrame, QLabel, QHBoxLayout, QVBoxLayout
from sentinal.vision.types import count_objects


class StatisticsPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.values = {}
        for key, title, tooltip in (
            ("people", "PEOPLE", "Visible person detections in the latest frame"),
            ("bags", "BAGS", "Backpacks, handbags and suitcases in the latest frame"),
            ("tracked", "TRACKED", "Visible detections with assigned tracking IDs"),
            ("fps", "PIPELINE FPS", "Measured capture, inference and tracking throughput; excludes playback waits"),
            ("latency", "VISION · MS", "Rolling average detection and tracking latency, excluding capture and rendering"),
            ("device", "PROCESSOR", "Actual model inference device"),
        ):
            card = QFrame()
            card.setObjectName("statCard")
            card.setToolTip(tooltip)
            inner = QVBoxLayout(card)
            inner.setContentsMargins(14, 13, 14, 13)
            inner.setSpacing(4)
            label = QLabel(title)
            label.setObjectName("metricTitle")
            value = QLabel("—")
            value.setObjectName("metricValue")
            inner.addWidget(label)
            inner.addWidget(value)
            layout.addWidget(card, 1)
            self.values[key] = value

    def update_packet(self, packet):
        for key, value in count_objects(packet.detections).items():
            if key in self.values:
                self.values[key].setText(str(value))
        self.values["fps"].setText(f"{packet.fps:.1f}")
        self.values["latency"].setText(f"{packet.average_inference_ms:.0f}")
        self.values["device"].setText(packet.device.upper())

    def reset_live(self):
        for key in ("people", "bags", "tracked", "fps", "latency"):
            self.values[key].setText("—")
