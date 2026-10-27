from __future__ import annotations

from collections.abc import Iterator

import pytest

from services.geom_worker.sandbox import WarmPool
from services.geom_worker.tests.conftest import PLATE


@pytest.fixture(scope="session")
def vpool() -> Iterator[WarmPool]:
    p = WarmPool(size=2)
    p.warm()
    yield p
    p.close()


@pytest.fixture(scope="session")
def plate_code() -> str:
    return PLATE
