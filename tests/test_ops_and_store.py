"""Ops endpoint and store-level unit tests.

Two reasons this file exists:

1. The health check is what a deployment pipeline polls; if it silently breaks,
   every downstream alert is wrong. It deserves a test.
2. A few store methods have defensive branches the HTTP layer cannot reach
   (e.g. updating a record that vanished between read and write). Testing them
   at the unit level keeps coverage honest instead of leaving dead branches.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

import pytest
from fastapi.testclient import TestClient

from app.main import get_store
from app.store import MAX_PARTY_SIZE, MAX_SEATS_PER_DATE, Booking, BookingStatus, BookingStore

pytestmark = pytest.mark.smoke


def test_health_reports_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_default_store_is_a_singleton_dependency() -> None:
    """The production dependency must return the module-level store."""
    assert isinstance(get_store(), BookingStore)
    assert get_store() is get_store()


class TestStoreUnit:
    def test_reset_clears_everything(self) -> None:
        db = BookingStore()
        db.add(
            Booking(
                customer_name="Ada",
                email="ada@example.com",
                booking_date=date.today() + timedelta(days=1),
                party_size=2,
            )
        )
        assert db.all()

        db.reset()

        assert db.all() == []

    def test_update_missing_record_returns_none(self) -> None:
        db = BookingStore()

        assert db.update("missing", status=BookingStatus.CONFIRMED) is None

    def test_delete_missing_record_returns_false(self) -> None:
        db = BookingStore()

        assert db.delete("missing") is False

    def test_cancelled_bookings_are_excluded_from_seat_count(self) -> None:
        db = BookingStore()
        day = date.today() + timedelta(days=3)
        db.add(
            Booking(
                customer_name="Ada",
                email="ada@example.com",
                booking_date=day,
                party_size=4,
                status=BookingStatus.CANCELLED,
            )
        )

        assert db.seats_taken(day) == 0


class TestCapacityOnUpdate:
    def test_growing_party_size_beyond_remaining_capacity_conflicts(
        self, client: TestClient, make_payload: Callable[..., dict]
    ) -> None:
        # Occupy the date exactly: 1 + 10 + 9 = MAX_SEATS_PER_DATE, leaving zero.
        target = client.post("/bookings", json=make_payload(party_size=1)).json()
        client.post("/bookings", json=make_payload(email="first@example.com", party_size=10))
        client.post("/bookings", json=make_payload(email="second@example.com", party_size=9))

        response = client.patch(f"/bookings/{target['id']}", json={"party_size": 3})

        assert response.status_code == 409
        assert "extra seat(s)" in response.json()["detail"]

    def test_shrinking_party_size_always_frees_seats(
        self, client: TestClient, make_payload: Callable[..., dict]
    ) -> None:
        target = client.post("/bookings", json=make_payload(party_size=10)).json()
        client.post("/bookings", json=make_payload(email="first@example.com", party_size=10))

        response = client.patch(f"/bookings/{target['id']}", json={"party_size": 2})

        assert response.status_code == 200
        assert response.json()["party_size"] == 2
