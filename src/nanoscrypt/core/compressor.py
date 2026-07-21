import structlog
from typing import Any
from nanoscrypt.config.settings import settings

logger = structlog.get_logger()

try:
    import headroom
    HEADROOM_AVAILABLE = True
except Exception as e:
    HEADROOM_AVAILABLE = False
    logger.warning("headroom_import_warning", error=str(e))


class ContextCompressor:
    """Context compression engine wrapping headroom-ai for code and tool output shrinking."""

    def __init__(self) -> None:
        self.enabled = settings.headroom.enabled and HEADROOM_AVAILABLE
        self.total_saved_tokens = 0

    def _extract_compressed_text(self, res: Any, default_text: str) -> str:
        try:
            if isinstance(res, list) and len(res) > 0:
                item = res[0]
                if isinstance(item, dict):
                    return item.get("content", default_text)
                return getattr(item, "content", str(item))
            if hasattr(res, "messages") and res.messages:
                item = res.messages[0]
                if isinstance(item, dict):
                    return item.get("content", default_text)
                return getattr(item, "content", str(item))
            if hasattr(res, "text") and res.text:
                return res.text
        except Exception:
            pass
        return str(res) if res else default_text

    def compress_text(self, text: str) -> str:
        """Compresses arbitrary text using headroom if enabled."""
        if not self.enabled or not text or len(text) < 200:
            return text

        try:
            msgs = [{"role": "user", "content": text}]
            res = headroom.compress(msgs)
            compressed_text = self._extract_compressed_text(res, text)
            if compressed_text and len(compressed_text) < len(text):
                saved = (len(text) - len(compressed_text)) // 4
                self.total_saved_tokens += max(0, saved)
                return compressed_text
        except Exception as e:
            logger.debug("headroom_text_compression_fallback", error=str(e))
        return text

    def compress_code(self, code: str, file_name: str = "") -> str:
        """Compresses code file contents using headroom AST/structural compression."""
        if not self.enabled or not code or len(code) < 300:
            return code

        try:
            msgs = [{"role": "user", "content": f"File: {file_name}\n{code}"}]
            res = headroom.compress(msgs)
            compressed_text = self._extract_compressed_text(res, code)
            if compressed_text and len(compressed_text) < len(code):
                saved = (len(code) - len(compressed_text)) // 4
                self.total_saved_tokens += max(0, saved)
                return compressed_text
        except Exception as e:
            logger.debug("headroom_code_compression_fallback", error=str(e))

        return code

    def compress_tool_output(self, output: str) -> str:
        """Shrinks tool execution outputs, web search results, or stack traces."""
        if not self.enabled or not output or len(output) < 300:
            return output

        try:
            msgs = [{"role": "user", "content": output}]
            res = headroom.compress(msgs)
            compressed_text = self._extract_compressed_text(res, output)
            if compressed_text and len(compressed_text) < len(output):
                saved = (len(output) - len(compressed_text)) // 4
                self.total_saved_tokens += max(0, saved)
                return compressed_text
        except Exception as e:
            logger.debug("headroom_tool_output_compression_fallback", error=str(e))

        return output
