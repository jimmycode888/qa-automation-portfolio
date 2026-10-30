"""Contract and validation tests for POST /bookings.

Grouped by the rule under test, not by endpoint, so a failure points straight
at the business rule that broke.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

import pytest
from fastapi.testclient import TestClient

from app.store import MAX_PARTY_SIZE, MAX_SEATS_PER_DATE

pytestmark = pytest.mark.regression


class TestCreateHappyPath:
    def test_returns_201_and_echoes_payload(self, client: TestClient, make_payload: Callable[..., dict]) -> None:
        payload = make_payload()

        response = client.post("/bookings", json=payload)

        assert response.status_code == 201
        body = response.json()
        assert body["customer_name"] == payload["customer_name"]
        assert body["email"] == payload["email"]
        assert body["booking_date"] == payload["booking_date"]
        assert body["party_size"] == payload["party_size"]
        assert body["notes"] == payload["notes"]

    def test_new_booking_starts_pending(self, client: TestClient, make_payload: Callable[..., dict]) -> None:
        response = client.post("/bookings", json=make_payload())

        assert response.json()["status"] == "pending"

    def test_generated_id_is_unique_across_bookings(
        self, client: TestClient, make_payload: Callable[..., dict]
    ) -> None:
        first = client.post("/bookings", json=make_payload()).json()
        second = client.post("/bookings", json=make_payload(email="grace@example.com")).json()

        assert first["id"] != second["id"]

    def test_surrounding_whitespace_is_trimmed_from_name(
        self, client: TestClient, make_payload: Callable[..., dict]
    ) -> None:
        response = client.post("/bookings", json=make_payload(customer_name="  Ada Lovelace  "))

        assert response.status_code == 201
        assert response.json()["customer_name"] == "Ada Lovelace"


class TestCreateValidation:
    @pytest.mark.parametrize("party_size", [0, -1, MAX_PARTY_SIZE + 1, 99])
    def test_rejects_party_size_outside_allowed_range(
        self, client: TestClient, make_payload: Callable[..., dict], party_size: int
    ) -> None:
        response = client.post("/bookings", json=make_payload(party_size=party_size))

        assert response.status_code == 422

    @pytest.mark.parametrize("party_size", [1, MAX_PARTY_SIZE])
    def test_accepts_boundary_party_sizes(
        self, client: TestClient, make_payload: Callable[..., dict], party_size: int
    ) -> None:
        response = client.post("/bookings", json=make_payload(party_size=party_size))

        assert response.status_code == 201

    @pytest.mark.parametrize("bad_email", ["not-an-email", "missing@tld", "@example.com", ""])
    def test_rejects_malformed_email(
        self, client: TestClient, make_payload: Callable[..., dict], bad_email: str
    ) -> None:
        response = client.post("/bookings", json=make_payload(email=bad_email))

        assert response.status_code == 422

    @pytest.mark.parametrize("blank_name", ["", "   "])
    def test_rejects_blank_customer_name(
        self, client: TestClient, make_payload: Callable[..., dict], blank_name: str
    ) -> None:
        response = client.post("/bookings", json=make_payload(customer_name=blank_name))

        assert response.status_code == 422

    def test_rejects_past_date(self, client: TestClient, make_payload: Callable[..., dict]) -> None:
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        response = client.post("/bookings", json=make_payload(booking_date=yesterday))

        assert response.status_code == 422

    def test_accepts_today(self, client: TestClient, make_payload: Callable[..., dict]) -> None:
        """Boundary: today is the earliest acceptable date."""
        response = client.post("/bookings", json=make_payload(booking_date=date.today().isoformat()))

        assert response.status_code == 201

    def test_rejects_unknown_field(
        self, client: TestClient, make_payload: Callable[..., dict]
    ) -> None:
        """extra='forbid' — a typo'd field must fail loudly, not be silently dropped."""
        response = client.post("/bookings", json=make_payload(party_sizes=2))

        assert response.status_code == 422

    def test_rejects_missing_required_field(
        self, client: TestClient, make_payload: Callable[..., dict]
    ) -> None:
        payload = make_payload()
        del payload["booking_date"]

        response = client.post("/bookings", json=payload)

        assert response.status_code == 422


class TestCreateBusinessRules:
    def test_duplicate_booking_for_same_customer_and_date_conflicts(
        self, client: TestClient, make_payload: Callable[..., dict]
    ) -> None:
        client.post("/bookings", json=make_payload())

        response = client.post("/bookings", json=make_payload(party_size=4))

        assert response.status_code == 409
        assert "already has an active booking" in response.json()["detail"]

    def test_duplicate_detection_ignores_email_case(
        self, client: TestClient, make_payload: Callable[..., dict]
    ) -> None:
        client.post("/bookings", json=make_payload(email="ada@example.com"))

        response = client.post("/bookings", json=make_payload(email="ADA@example.com"))

        assert response.status_code == 409

    def test_same_customer_can_book_a_different_date(
        self, client: TestClient, make_payload: Callable[..., dict], future_date: date
    ) -> None:
        client.post("/bookings", json=make_payload())
        other_day = (future_date + timedelta(days=1)).isoformat()

        response = client.post("/bookings", json=make_payload(booking_date=other_day))

        assert response.status_code == 201

    def test_booking_beyond_remaining_capacity_conflicts(
        self, client: TestClient, make_payload: Callable[..., dict]
    ) -> None:
        # Fill the date to MAX_SEATS_PER_DATE using distinct customers.
        for index in range(MAX_SEATS_PER_DATE // MAX_PARTY_SIZE):
            response = client.post(
                "/bookings",
                json=make_payload(email=f"filler{index}@example.com", party_size=MAX_PARTY_SIZE),
            )
            assert response.status_code == 201

        response = client.post("/bookings", json=make_payload(email="late@example.com", party_size=1))

        assert response.status_code == 409
        assert "seat(s) left" in response.json()["detail"]

    def test_cancelled_booking_frees_capacity(
        self, client: TestClient, make_payload: Callable[..., dict]
    ) -> None:
        for index in range(MAX_SEATS_PER_DATE // MAX_PARTY_SIZE):
            client.post(
                "/bookings",
                json=make_payload(email=f"filler{index}@example.com", party_size=MAX_PARTY_SIZE),
            )
        full = client.post("/bookings", json=make_payload(email="late@example.com", party_size=1))
        assert full.status_code == 409

        first = client.get("/bookings").json()[0]
        client.patch(f"/bookings/{first['id']}", json={"status": "cancelled"})

        retry = client.post("/bookings", json=make_payload(email="late@example.com", party_size=1))

        assert retry.status_code == 201
