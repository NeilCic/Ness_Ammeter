from socket import socket, AF_INET, SOCK_STREAM

# Returned current is in amperes.
CURRENT_UNIT = "A"


def request_current_from_ammeter(port: int, command: bytes, timeout: float) -> float:
    with socket(AF_INET, SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            s.connect(('localhost', port))
            s.sendall(command)
            data = s.recv(1024)
        except TimeoutError:
            raise RuntimeError(f"No response from port {port} within {timeout} seconds") from None
        if not data:
            raise RuntimeError(f"No data received from port {port}")
        current = float(data.decode("utf-8"))
        print(f"Received current measurement from port {port}: {current} {CURRENT_UNIT}")
        return current

