import errno
import logging
import socket
import time
import random
from abc import ABC, abstractmethod

NotImplementedErrorMsg = "Subclasses must implement this property."

log = logging.getLogger("ammeters")


class AmmeterEmulatorBase(ABC):
    def __init__(self, port: int):
        self.port = port
        random.seed(time.time())  # Seed the random number generator for each instance

    def bind_server(self) -> socket.socket:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.bind(("localhost", self.port))
            server.listen()
        except OSError as error:
            server.close()
            if error.errno == errno.EADDRINUSE or getattr(error, "winerror", None) == 10048:
                raise OSError(f"Port {self.port} is already taken") from None
            raise
        return server

    def start_server(self, server: socket.socket | None = None):
        """
        Starts the server to listen for client requests.
        The server will run indefinitely, handling one client request at a time.
        """
        if server is None:
            server = self.bind_server()
        with server:
            log.info(f"{self.__class__.__name__} is running on port {self.port}")
            while True:
                conn, addr = server.accept()
                with conn:
                    log.debug(f"Connected by {addr}")
                    data = conn.recv(1024)
                    if data == self.get_current_command:
                        # Call the specific measure_current() method defined in subclasses
                        current = self.measure_current()
                        conn.sendall(str(current).encode('utf-8'))

    @property
    @abstractmethod
    def get_current_command(self) -> bytes:
        """
        This property must be implemented by each subclass to provide the specific
        command to get the current measurement.
        """
        raise NotImplementedError(NotImplementedErrorMsg)

    @abstractmethod
    def measure_current(self) -> float:
        """
        This method must be implemented by each subclass to provide the specific
        logic for current measurement.
        """
        raise NotImplementedError(NotImplementedErrorMsg)

