import logging
from datetime import datetime
from pathlib import Path


class TestLogger:
    __test__ = False

    def __init__(self, test_name: str, log_dir: Path):
        self._test_name = test_name
        self.logger = logging.getLogger(f"test_{test_name}_{id(self)}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = log_dir / f"{timestamp}_{test_name}.log"
        handler = logging.FileHandler(self.path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        self.logger.addHandler(handler)

    def info(self, message: str):
        self.logger.info(message)

    def error(self, message: str):
        self.logger.error(message)

    def debug(self, message: str):
        self.logger.debug(message)

    def warning(self, message: str):
        self.logger.warning(message)

    def close(self):
        for handler in list(self.logger.handlers):
            handler.close()
            self.logger.removeHandler(handler)


SESSION_LOG = TestLogger("session", Path("results") / "logs")
