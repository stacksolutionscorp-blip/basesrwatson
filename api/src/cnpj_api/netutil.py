import ipaddress


def valid_ip(value: str | None) -> str | None:
    """IP normalizado, ou None se o valor não for um IP (ex.: "testclient", X-Forwarded-For malformado)."""
    try:
        return str(ipaddress.ip_address(value)) if value else None
    except ValueError:
        return None
