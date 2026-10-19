"""Internal exception wrapper for safe, structured reader errors."""

from wechat_reader_mcp.models import ReaderError


class ReaderException(Exception):
    """Raise a public-safe :class:`ReaderError` through internal layers."""

    def __init__(self, error: ReaderError) -> None:
        self.error = error
        super().__init__(error.message)
