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
        ammeter = ammeter_cls(config["ammeters"][name]["port"])
        server = ammeter.bind_server()
        threading.Thread(target=ammeter.start_server, args=(server,), daemon=True).start()
    time.sleep(wait_seconds)
