from .base import Item, SOURCE_REGISTRY, Source, detect_source, get_source, register
from .media import MediaFileSource
from .pdf import PDFSource
from .youtube import YouTubeSource

register(YouTubeSource())
register(MediaFileSource())
register(PDFSource())

__all__ = [
    "Item",
    "Source",
    "SOURCE_REGISTRY",
    "detect_source",
    "get_source",
    "register",
    "YouTubeSource",
    "MediaFileSource",
    "PDFSource",
]
