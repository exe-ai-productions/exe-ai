"""Whether a host name leads only to public places.

One answer for every place the program fetches something a model or a
server named (a picture for a job, the logo of an MCP server): a name that
does not resolve, one that leads to a private, loopback or link-local
address (the cloud metadata address among them), or to the shared range of a
mesh network, is not public.
"""

from __future__ import annotations

import ipaddress
import socket

_NAT64 = ipaddress.IPv6Network("64:ff9b::/96")


def is_public(host: str) -> bool:
    """Whether every address ``host`` leads to is a public one. Blocking —
    it resolves the name — so a caller on the event loop runs it in a
    thread."""
    try:
        found = {item[4][0] for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    except (OSError, UnicodeError):
        return False
    if not found:
        return False
    for text in found:
        address = ipaddress.ip_address(text.split("%")[0])
        if isinstance(address, ipaddress.IPv6Address):
            # The IPv4 address inside a mapped or a NAT64 one is the place
            # that is reached; it is the one that is looked at.
            if address.ipv4_mapped is not None:
                address = address.ipv4_mapped
            elif address in _NAT64:
                address = ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
        if not address.is_global:
            return False
    return True
