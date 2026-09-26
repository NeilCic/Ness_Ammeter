import logging
import math
from socket import socket, AF_INET, SOCK_STREAM

# Returned current is in amperes.
CURRENT_UNIT = "A"

log = logging.getLogger("ammeters.client")


class AmmeterError(RuntimeError):
    """A meter could not be reached, did not answer, or answered with something that is not a current."""


def request_current_from_ammeter(port: int, command: bytes, timeout: float) -> float:
    with socket(AF_INET, SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            s.connect(('localhost', port))
        except OSError:  # refused outright on Linux/macOS, keeps retrying until the timeout on Windows
            raise AmmeterError(f"No meter is reachable on port {port}") from None
        try:
            s.sendall(command)
            data = s.recv(1024)
        except TimeoutError:
            raise AmmeterError(f"No response from port {port} within {timeout} seconds") from None
    if not data:
        raise AmmeterError(f"No data received from port {port}")
    text = data.decode("utf-8", errors="replace").strip()
    try:
        current = float(text)
    except ValueError:
        raise AmmeterError(f"Port {port} replied with {text!r}, which is not a number") from None
    if not math.isfinite(current):
        raise AmmeterError(f"Port {port} replied with {text!r}, which is not a finite current")
    log.debug(f"Received current measurement from port {port}: {current} {CURRENT_UNIT}")
    return current
