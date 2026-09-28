"""Draws the Multiversal Manager icon (a spellbook) with QPainter and writes a
multi-size .ico (PNG entries) plus a preview sheet.
Usage: make_icon.py <out.ico> <preview.png>"""
import math
import struct
import sys

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
GOLD, GOLD_DARK, GOLD_LIGHT = QColor("#e8b64a"), QColor("#9a6a1c"), QColor("#fff0b8")


def sparkle(center, radius, waist=0.22):
    # A four-pointed star
    path = QPainterPath()
    for i in range(8):
        angle = math.pi / 4 * i - math.pi / 2
        r = radius if i % 2 == 0 else radius * waist
        point = QPointF(center.x() + r * math.cos(angle), center.y() + r * math.sin(angle))
        path.moveTo(point) if i == 0 else path.lineTo(point)
    path.closeSubpath()
    return path


def draw(size):
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 256, size / 256)
    small = size <= 24      # fewer, bolder details where there are only a few pixels
    medium = size <= 48

    # The page block, peeking out right and bottom
    pages = QRectF(58, 34, 168, 196) if not small else QRectF(56, 30, 172, 204)
    p.setPen(QPen(QColor("#8a6a3a"), 4))
    p.setBrush(QColor("#f4e7c6"))
    p.drawRoundedRect(pages, 14, 14)
    if not medium:
        p.setPen(QPen(QColor("#cdb88a"), 2.5))
        for offset in (10, 18):
            p.drawLine(QPointF(pages.right() - offset, pages.top() + 16),
                       QPointF(pages.right() - offset, pages.bottom() - 10))
            p.drawLine(QPointF(pages.left() + 24, pages.bottom() - offset),
                       QPointF(pages.right() - 14, pages.bottom() - offset))

    # The cover: deep purple leather
    cover = QRectF(30, 18, 176, 200)
    grad = QLinearGradient(cover.topLeft(), cover.bottomRight())
    grad.setColorAt(0, QColor("#6b3fb0"))
    grad.setColorAt(0.55, QColor("#46237f"))
    grad.setColorAt(1, QColor("#2a1352"))
    p.setPen(QPen(QColor("#1c0b3a"), 5 if not small else 8))
    p.setBrush(grad)
    p.drawRoundedRect(cover, 16, 16)

    # Spine with gold bands
    spine = QRectF(30, 18, 34, 200)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(20, 6, 45, 110))
    p.drawRoundedRect(spine, 14, 14)
    if not small:
        p.setBrush(GOLD)
        for y in (46, 186):
            p.drawRoundedRect(QRectF(32, y, 30, 9 if not medium else 12), 3, 3)

    # Gold corner guards on the cover's outer corners
    p.setBrush(GOLD)
    p.setPen(QPen(GOLD_DARK, 3) if not small else Qt.PenStyle.NoPen)
    corner = 34 if not small else 40
    for (x, y, dx, dy) in ((206, 18, -1, 1), (206, 218, -1, -1)):
        path = QPainterPath(QPointF(x, y))
        path.lineTo(QPointF(x + dx * corner, y))
        path.lineTo(QPointF(x, y + dy * corner))
        path.closeSubpath()
        p.drawPath(path)

    # The emblem: a glowing ring and a star
    center = QPointF(136, 118)
    glow = QRadialGradient(center, 70)
    glow.setColorAt(0, QColor(150, 230, 255, 200))
    glow.setColorAt(0.45, QColor(120, 140, 255, 90))
    glow.setColorAt(1, QColor(120, 90, 255, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(glow)
    p.drawEllipse(center, 70, 70)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(GOLD, 7 if not small else 11))
    p.drawEllipse(center, 46, 46)
    if not medium:
        p.setPen(QPen(GOLD_LIGHT, 2))
        p.drawEllipse(center, 37, 37)
        # Rune ticks around the ring
        p.setPen(QPen(GOLD, 4))
        for i in range(12):
            a = math.pi / 6 * i
            p.drawLine(QPointF(center.x() + 50 * math.cos(a), center.y() + 50 * math.sin(a)),
                       QPointF(center.x() + 58 * math.cos(a), center.y() + 58 * math.sin(a)))
    star = QLinearGradient(QPointF(136, 80), QPointF(136, 156))
    star.setColorAt(0, QColor("#ffffff"))
    star.setColorAt(0.5, GOLD_LIGHT)
    star.setColorAt(1, GOLD)
    p.setPen(QPen(GOLD_DARK, 2.5) if not small else Qt.PenStyle.NoPen)
    p.setBrush(star)
    p.drawPath(sparkle(center, 40 if not small else 44, 0.26 if not small else 0.32))

    # Sparkles of magic around the book
    if not small:
        p.setPen(QPen(GOLD_DARK, 2.5 if not medium else 5))
        p.setBrush(GOLD_LIGHT)
        for x, y, r in ((226, 28, 20), (240, 68, 11)):
            p.drawPath(sparkle(QPointF(x, y), r if not medium else r * 1.3, 0.25))
    p.end()
    return image


def png_bytes(image):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def write_ico(path, images):
    # ICO header, a directory entry per size, then each size as PNG data
    blobs = [png_bytes(image) for image in images]
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries = b""
    for image, blob in zip(images, blobs):
        side = image.width() if image.width() < 256 else 0   # 0 means 256
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    with open(path, "wb") as f:
        f.write(header + entries + b"".join(blobs))


def preview(path, images):
    # Every size side by side at 1x, on light and dark backgrounds
    width = sum(i.width() + 12 for i in images) + 12
    sheet = QImage(width, 2 * 280, QImage.Format.Format_ARGB32)
    p = QPainter(sheet)
    for row, bg in enumerate(("#f3f3f3", "#1e1e1e")):
        p.fillRect(0, row * 280, width, 280, QColor(bg))
        x = 12
        for image in images:
            p.drawImage(x, row * 280 + 12 + (256 - image.height()), image)
            x += image.width() + 12
    p.end()
    sheet.save(path)


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    images = [draw(size) for size in SIZES]
    write_ico(sys.argv[1], images)
    preview(sys.argv[2], images)
    print("wrote", sys.argv[1])
