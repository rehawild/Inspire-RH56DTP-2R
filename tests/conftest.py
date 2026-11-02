import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from inspire_rh56dtp_2r.hand import RH56Hand  # noqa: E402
from inspire_rh56dtp_2r.sim import SimServer  # noqa: E402


@pytest.fixture
def sim():
    with SimServer() as server:
        yield server


@pytest.fixture
def hand(sim):
    host, port = sim.address
    with RH56Hand(host, port) as h:
        yield h
