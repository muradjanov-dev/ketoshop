"""
Auto-translate product text from Uzbek to Russian using Google Translate
"""
import asyncio
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


def _translate_sync(text: str, source: str = "uz", target: str = "ru") -> str:
    """Synchronous translation using Google Translate."""
    if not text or not text.strip():
        return text
    try:
        from deep_translator import GoogleTranslator
        result = GoogleTranslator(source=source, target=target).translate(text)
        return result or text
    except Exception as e:
        logger.warning(f"Translation failed ({source}->{target}): {e}")
        return text


async def translate(text: str, source: str = "uz", target: str = "ru") -> str:
    """Async wrapper for translation."""
    if not text or not text.strip():
        return text
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _translate_sync, text, source, target)


async def translate_product_fields(name: str, description: str) -> tuple[str, str]:
    """Translate product name and description from Uzbek to Russian.
    Returns (name_ru, description_ru).
    """
    name_ru = await translate(name, "uz", "ru") if name else ""
    desc_ru = await translate(description, "uz", "ru") if description else ""
    return name_ru, desc_ru
