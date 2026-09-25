import threading
import time

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter

STARTERS = {
    "greenlee": GreenleeAmmeter,
    "entes": EntesAmmeter,
    "circutor": CircutorAmmeter,
}


def start_emulators(config: dict, wait_seconds: float = 1) -> None:
    for name, ammeter_cls in STARTERS.items():
        port = config["ammeters"][name]["port"]
        threading.Thread(target=ammeter_cls(port).start_server, daemon=True).start()
    time.sleep(wait_seconds)