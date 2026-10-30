from collections.abc import Iterator

import pytest

from services.registry.tests.fixtures import isolated  # noqa: F401


@pytest.fixture(autouse=True)
def _fresh_rate_limit() -> Iterator[None]:
    """Each test starts with an empty write window: the limiter is per process, and the suite's POSTs add up."""
    from services.api import main

    main.limiter.reset()
    yield
