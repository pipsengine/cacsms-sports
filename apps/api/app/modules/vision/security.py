"""Pure URL permission checks; reject internal and credentialed browser destinations."""
from urllib.parse import urlsplit
import ipaddress,socket

def validate_destination(url, allowed_hosts, resolver=socket.getaddrinfo):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError('Only credential-free HTTPS destinations on port 443 are permitted')
    host=parsed.hostname.lower().rstrip('.')
    from app.modules.acquisition.source_policy import assert_permitted
    assert_permitted(url)  # terms-of-service prohibitions win over any allowlist entry
    if host not in {x.lower().rstrip('.') for x in allowed_hosts}:
        raise PermissionError('Destination not in approved source host allowlist')
    if not allowed_hosts:raise PermissionError('No approved sources configured')
    for item in resolver(host,443,type=socket.SOCK_STREAM):
        addr=ipaddress.ip_address(item[4][0])
        if not addr.is_global:raise PermissionError('Non-public IP destination rejected')
    return url
