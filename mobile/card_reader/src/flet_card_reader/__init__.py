import flet as ft

__all__ = ["CardReader"]


@ft.control("CardReader")
class CardReader(ft.Service):
    """Reads the text on a photo, on the phone (Google ML Kit, offline)"""

    async def read_text(self, image: bytes) -> list:
        """The lines of text on a photo (JPEG or PNG bytes), each a dict with "text" and
        where it is: "top", "left", "width" and "height" in pixels"""
        return await self._invoke_method("read_text", {"image": image}, timeout=30)
