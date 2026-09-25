import pytest

from src.utils.config import load_config
from src.utils.emulators import start_emulators


@pytest.fixture(scope="session", autouse=True)
def running_ammeters():
    start_emulators(load_config("config/config.yaml"))
