"""Shared fixtures.

Each test gets its own `BookingStore` through FastAPI's dependency override, so
tests never see each other's data. That isolation is deliberate: shared mutable
state is the most common source of order-dependent (flaky) API tests.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_store
from app.store import BookingStore


@pytest.fixture()
def store() -> BookingStore:
    return BookingStore()


@pytest.fixture()
def client(store: BookingStore) -> TestClient:
    app.dependency_overrides[get_store] = lambda: store
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def future_date() -> date:
    """A date the API will accept. Kept relative so the suite never expires."""
    return date.today() + timedelta(days=14)


@pytest.fixture()
def make_payload(future_date: date) -> Callable[..., dict]:
    """Build a valid create-booking payload, with per-test overrides."""

    def _make(**overrides: object) -> dict:
        payload: dict[str, object] = {
            "customer_name": "Ada Lovelace",
            "email": "ada@example.com",
            "booking_date": future_date.isoformat(),
            "party_size": 2,
            "notes": "window seat please",
        }
        payload.update(overrides)
        return payload

    return _make


@pytest.fixture()
def created_booking(client: TestClient, make_payload: Callable[..., dict]) -> dict:
    """A booking that already exists, for tests about read/update/delete."""
    response = client.post("/bookings", json=make_payload())
    assert response.status_code == 201, response.text
    return response.json()
