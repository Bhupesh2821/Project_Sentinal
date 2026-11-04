"""Draw original frames and source-coordinate annotations without distortion."""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QFont
from PySide6.QtWidgets import QWidget

from sentinal.vision.types import BAG_CLASSES


class VideoPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 320)
        self.setObjectName("videoPanel")
        self._image = None
        self._packet = None
        self._sampled_view = False
        self.show_boxes = True
        self.show_labels = True
        self.show_ids = True
        self.message = "READY TO MONITOR"

    def present_packet(self, packet, hazards_enabled=False):
        """Keep each hazard overlay on the exact frame that was analyzed.

        When hazards are sampled less often than objects, display the latest
        complete AI sample instead of briefly flashing boxes or moving old boxes
        onto newer pixels. Processing statistics still use the newest packet.
        """
        active = hazards_enabled and any(
            info.get('status') == 'active' for info in packet.detector_health.values()
        )
        previous = self._packet
        self._sampled_view = active
        if (active and not packet.hazard_sampled and previous is not None
                and previous.session_id == packet.session_id and previous.hazard_sampled):
            self.update()
            return False
        self.set_packet(packet)
        return True

    def set_packet(self, packet):
        frame = packet.frame
        h, w = frame.shape[:2]
        # copy() disconnects the display image from the worker-owned ndarray.
        self._image = QImage(frame.data, w, h, frame.strides[0], QImage.Format.Format_BGR888).copy()
        self._packet = packet
        self.update()

    def clear_frame(self, message="SOURCE INACTIVE"):
        self._image = None
        self._packet = None
        self._sampled_view = False
        self.message = message
        self.update()

    def set_annotations(self, boxes, labels, ids):
        self.show_boxes, self.show_labels, self.show_ids = boxes, labels, ids
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#080e16"))
        painter.setPen(QPen(QColor("#233348"), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 10, 10)
        if self._image is None:
            self._draw_empty(painter)
            return
        width, height = self._image.width(), self._image.height()
        scale = min((self.width() - 4) / width, (self.height() - 4) / height)
        x, y = (self.width() - width * scale) / 2, (self.height() - height * scale) / 2
        target = QRectF(x, y, width * scale, height * scale)
        painter.drawImage(target, self._image)
        painter.setClipRect(target)
        painter.setFont(QFont("Helvetica Neue", 11, QFont.Weight.DemiBold))
        for detection in self._packet.detections:
            color = QColor("#53d9c4" if detection.label in BAG_CLASSES else "#59aaff")
            x1, y1, x2, y2 = detection.bbox
            box = QRectF(x + x1 * scale, y + y1 * scale, (x2 - x1) * scale, (y2 - y1) * scale)
            if self.show_boxes:
                painter.setPen(QPen(color, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(box)
            parts = []
            if self.show_labels:
                parts.append(f"{detection.label}  {detection.confidence:.0%}")
            if self.show_ids and detection.track_id is not None:
                parts.append(f"#{detection.track_id}")
            if parts:
                text = "  ·  ".join(parts)
                text_width = painter.fontMetrics().horizontalAdvance(text) + 14
                label_x = min(max(x, box.left()), max(x, target.right() - text_width))
                label_y = max(y, box.top() - 24)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(7, 19, 33, 225))
                painter.drawRoundedRect(QRectF(label_x, label_y, text_width, 23), 3, 3)
                painter.setPen(color)
                painter.drawText(QRectF(label_x + 7, label_y, text_width - 7, 23), Qt.AlignmentFlag.AlignVCenter, text)

        for observation in getattr(self._packet,'hazards',()):
            color=QColor('#e7b760')
            x1,y1,x2,y2=observation.bbox
            box=QRectF(x+x1*scale,y+y1*scale,(x2-x1)*scale,(y2-y1)*scale)
            if self.show_boxes:
                painter.setPen(QPen(color,2));painter.setBrush(Qt.BrushStyle.NoBrush);painter.drawRect(box)
            parts=[]
            if self.show_labels:parts.append('Possible '+observation.category.replace('weapon_','').replace('ghs_','GHS ').replace('_',' ')+f' {observation.confidence:.0%}')
            if self.show_ids and observation.track_id is not None:parts.append(f'{observation.detector} #{observation.track_id}')
            if parts:
                text=' · '.join(parts);tw=painter.fontMetrics().horizontalAdvance(text)+14
                lx=min(max(x,box.left()),max(x,target.right()-tw));ly=max(y,box.top()-24)
                painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor(42,31,14,230));painter.drawRoundedRect(QRectF(lx,ly,tw,23),3,3)
                painter.setPen(color);painter.drawText(QRectF(lx+7,ly,tw-7,23),Qt.AlignmentFlag.AlignVCenter,text)

        if self._sampled_view:
            painter.setClipping(False)
            text = 'AI sampled view · ' + self._packet.timestamp
            painter.setFont(QFont('Helvetica Neue', 10))
            painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor(7, 19, 33, 235))
            painter.drawRect(QRectF(4, self.height()-25, self.width()-8, 22))
            painter.setPen(QColor('#d6e6f5'))
            painter.drawText(QRectF(12, self.height()-25, self.width()-24, 22), Qt.AlignmentFlag.AlignVCenter, text)

    def _draw_empty(self, painter):
        center = self.rect().center()
        painter.setPen(QPen(QColor("#1e3652"), 1))
        painter.drawEllipse(center, 48, 48)
        painter.drawEllipse(center, 33, 33)
        painter.setPen(QPen(QColor("#458ac9"), 2))
        painter.drawLine(center.x() - 12, center.y(), center.x() + 12, center.y())
        painter.drawLine(center.x(), center.y() - 12, center.x(), center.y() + 12)
        painter.setPen(QColor("#a0bbd9"))
        painter.setFont(QFont("Helvetica Neue", 13, QFont.Weight.DemiBold))
        painter.drawText(QRectF(0, center.y() + 68, self.width(), 30), Qt.AlignmentFlag.AlignCenter, self.message)
        painter.setPen(QColor("#6c839f"))
        painter.setFont(QFont("Helvetica Neue", 11))
        painter.drawText(QRectF(20, center.y() + 100, self.width() - 40, 50), Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, "Select a camera or local video, then start monitoring.\nVideo processing stays on this Mac.")
