# Imports
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy

import background
import scryfall

# Scryfall's "normal" images are 488x680
CARD_ASPECT = 680 / 488

# Recently shown images stay decoded in memory, so flipping between cards is instant
_MEMORY_CACHE_SIZE = 64
_pixmap_cache = {}


def _fetch(url):
    # Returns (url, bytes-or-None) so the result can be matched to the request
    # that asked for it, and a failed download just shows a placeholder
    try:
        return url, scryfall.fetch_image(url)
    except Exception:
        return url, None


class CardImage(QLabel):
    """Shows a full card image, scaled to fit but never cropped, so the artist
    credit and copyright line printed on the card always stay visible."""

    def __init__(self, width=244, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(QSize(width, round(width * CARD_ASPECT)))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("color: gray;")
        self.setWordWrap(True)
        self._pixmap = None
        self._url = None
        self.clear_image()

    def clear_image(self, message="No card selected"):
        self._url = None
        self._pixmap = None
        self.setPixmap(QPixmap())
        self.setText(message)

    def set_image_url(self, url):
        if not url:
            self.clear_image("No image available")
            return
        if url == self._url:
            return
        self._url = url
        if url in _pixmap_cache:
            self._show(_pixmap_cache[url])
            return
        self._pixmap = None
        self.setPixmap(QPixmap())
        self.setText("Loading image…")
        background.run(_fetch, url, on_success=self._on_loaded)

    def _on_loaded(self, result):
        url, data = result
        # A slow response for a card the user already clicked away from is ignored
        if url != self._url:
            return
        pixmap = QPixmap()
        if data is not None and pixmap.loadFromData(data):
            _pixmap_cache[url] = pixmap
            if len(_pixmap_cache) > _MEMORY_CACHE_SIZE:
                del _pixmap_cache[next(iter(_pixmap_cache))]
            self._show(pixmap)
        else:
            self.setText("Image unavailable (offline?)")

    def _show(self, pixmap):
        self._pixmap = pixmap
        self.setText("")
        self._rescale()

    def _rescale(self):
        if self._pixmap is not None:
            self.setPixmap(self._pixmap.scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()
