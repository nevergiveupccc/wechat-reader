"""Discovery-provider contracts and built-in implementations."""

from wechat_reader_mcp.discovery.base import DiscoveryProvider, ProviderPage
from wechat_reader_mcp.discovery.public import (
    SogouDiscoveryProvider,
    SogouUrlResolver,
)

__all__ = [
    "DiscoveryProvider",
    "ProviderPage",
    "SogouDiscoveryProvider",
    "SogouUrlResolver",
]
