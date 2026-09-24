import threading
import time

import pytest

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from src.utils.config import load_config

STARTERS = {
    "greenlee": GreenleeAmmeter,
    "entes": EntesAmmeter,
    "circutor": CircutorAmmeter,
}


@pytest.fixture(scope="session", autouse=True)
def running_ammeters():
    config = load_config("config/config.yaml")
    for name, ammeter_cls in STARTERS.items():
        port = config["ammeters"][name]["port"]
        threading.Thread(target=ammeter_cls(port).start_server, daemon=True).start()
    time.sleep(1)
