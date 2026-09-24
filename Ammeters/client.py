from socket import socket, AF_INET, SOCK_STREAM


def request_current_from_ammeter(port: int, command: bytes) -> float:
    with socket(AF_INET, SOCK_STREAM) as s:
        s.connect(('localhost', port))
        s.sendall(command)
        data = s.recv(1024)
        if not data:
            raise RuntimeError(f"No data received from port {port}")
        current = float(data.decode("utf-8"))
        print(f"Received current measurement from port {port}: {current} A")
        return current

