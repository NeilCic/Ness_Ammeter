import pytest

from src.utils.config import load_config
from src.utils.emulators import start_emulators
from src.utils.logger import SESSION_LOG

_test_number = 0
_test_total = 0
_started = set()


def pytest_collection_finish(session):
    global _test_total
    _test_total = len(session.items)


def pytest_runtest_logreport(report):
    global _test_number
    title = report.nodeid.split("::")[-1]
    if report.when == "setup":
        _test_number += 1
        label = f"{_test_number}/{_test_total} {title}"
        if report.passed:
            _started.add(report.nodeid)
            SESSION_LOG.info(f"========== start {label} ==========")
        else:
            SESSION_LOG.error(f"========== finish {label} setup {report.outcome} ==========")
    elif report.when == "call" and report.nodeid in _started:
        label = f"{_test_number}/{_test_total} {title}"
        SESSION_LOG.info(f"========== finish {label} {report.outcome} ==========")


def pytest_sessionfinish(session, exitstatus):
    SESSION_LOG.info(f"session finished exit {exitstatus}")
    SESSION_LOG.close()


@pytest.fixture(scope="session", autouse=True)
def running_ammeters():
    config = load_config("config/config.yaml")
    start_emulators(config)
    started = ", ".join(
        f"{name} on port {meter['port']}" for name, meter in config["ammeters"].items()
    )
    SESSION_LOG.info(f"emulators started: {started}")
