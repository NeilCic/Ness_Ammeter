import math

import pytest

from src.testing.test_framework import AmmeterTestFramework
from src.utils.config import load_config

AMMETERS = list(load_config("config/config.yaml")["ammeters"])


@pytest.mark.parametrize("ammeter_type", AMMETERS)
def test_returns_a_finite_current(ammeter_type):
    current = AmmeterTestFramework().run_test(ammeter_type)
    assert isinstance(current, float)
    assert math.isfinite(current)
