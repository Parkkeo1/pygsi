from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from pygsi import GSIServer

FIXTURES_PATH = Path(__file__).parent / "fixtures.json"
PLAYER_ID = "76561198000000000"


@pytest.fixture
def fixtures() -> dict[str, Any]:
    result: dict[str, Any] = json.loads(FIXTURES_PATH.read_text())
    return result


@pytest.fixture
def gsi() -> GSIServer:
    return GSIServer(player_id=PLAYER_ID, port=0)


@pytest.fixture
def client(gsi: GSIServer) -> AsyncClient:
    transport = ASGITransport(app=gsi._app)
    return AsyncClient(transport=transport, base_url="http://test")
