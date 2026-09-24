from Ammeters.client import request_current_from_ammeter
from ..utils.config import load_config


class AmmeterTestFramework:
    def __init__(self, config_path: str = "config/config.yaml"):
        self.config = load_config(config_path)
        
    def run_test(self, ammeter_type: str) -> float:
        try:
            ammeter = self.config["ammeters"][ammeter_type]
        except KeyError:
            known = ", ".join(self.config.get("ammeters", {}))
            raise ValueError(f"Unknown ammeter '{ammeter_type}'. Known: {known}") from None
        return request_current_from_ammeter(ammeter["port"], ammeter["command"].encode("utf-8"))