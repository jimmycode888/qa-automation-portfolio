"""Read, update and delete behaviour.

The state machine is the interesting part: pending -> confirmed -> cancelled,
with everything else rejected. Those transitions are tested exhaustively here
because a silent illegal transition is the kind of defect that reaches
production.
"""

from __future__ import annotations

from typing import Callable

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.regression


class TestRead:
    def test_get_existing_booking(self, client: TestClient, created_booking: dict) -> None:
        response = client.get(f"/bookings/{created_booking['id']}")

        assert response.status_code == 200
        assert response.json() == created_booking

    def test_get_unknown_id_returns_404(self, client: TestClient) -> None:
        response = client.get("/bookings/does-not-exist")

        assert response.status_code == 404
        assert response.json()["detail"] == "booking not found"

    def test_list_returns_every_booking(
        self, client: TestClient, make_payload: Callable[..., dict]
    ) -> None:
        client.post("/bookings", json=make_payload())
        client.post("/bookings", json=make_payload(email="grace@example.com"))

        response = client.get("/bookings")

        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_list_filters_by_date(
        self, client: TestClient, make_payload: Callable[..., dict], future_date
    ) -> None:
        client.post("/bookings", json=make_payload())

        response = client.get("/bookings", params={"date": future_date.isoformat()})

        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["booking_date"] == future_date.isoformat()

    def test_list_returns_empty_array_when_nothing_matches(
        self, client: TestClient, future_date
    ) -> None:
        response = client.get("/bookings", params={"date": future_date.isoformat()})

        assert response.status_code == 200
        assert response.json() == []


class TestUpdateStateMachine:
    def test_pending_to_confirmed(self, client: TestClient, created_booking: dict) -> None:
        response = client.patch(f"/bookings/{created_booking['id']}", json={"status": "confirmed"})

        assert response.status_code == 200
        assert response.json()["status"] == "confirmed"

    def test_pending_to_cancelled(self, client: TestClient, created_booking: dict) -> None:
        response = client.patch(f"/bookings/{created_booking['id']}", json={"status": "cancelled"})

        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"

    def test_confirmed_to_cancelled(self, client: TestClient, created_booking: dict) -> None:
        client.patch(f"/bookings/{created_booking['id']}", json={"status": "confirmed"})

        response = client.patch(f"/bookings/{created_booking['id']}", json={"status": "cancelled"})

        assert response.status_code == 200

    def test_cancelled_is_terminal(self, client: TestClient, created_booking: dict) -> None:
        client.patch(f"/bookings/{created_booking['id']}", json={"status": "cancelled"})

        response = client.patch(f"/bookings/{created_booking['id']}", json={"status": "confirmed"})

        assert response.status_code == 409
        assert "cannot move from cancelled" in response.json()["detail"]

    def test_confirmed_cannot_go_back_to_pending(self, client: TestClient, created_booking: dict) -> None:
        client.patch(f"/bookings/{created_booking['id']}", json={"status": "confirmed"})

        response = client.patch(f"/bookings/{created_booking['id']}", json={"status": "pending"})

        assert response.status_code == 409

    def test_same_status_is_idempotent(self, client: TestClient, created_booking: dict) -> None:
        response = client.patch(f"/bookings/{created_booking['id']}", json={"status": "pending"})

        assert response.status_code == 200
        assert response.json()["status"] == "pending"

    def test_unknown_status_value_is_rejected(self, client: TestClient, created_booking: dict) -> None:
        response = client.patch(f"/bookings/{created_booking['id']}", json={"status": "archived"})

        assert response.status_code == 422

    def test_patch_unknown_booking_returns_404(self, client: TestClient) -> None:
        response = client.patch("/bookings/nope", json={"status": "confirmed"})

        assert response.status_code == 404


class TestUpdatePartySize:
    def test_increase_party_size_within_capacity(
        self, client: TestClient, created_booking: dict
    ) -> None:
        response = client.patch(f"/bookings/{created_booking['id']}", json={"party_size": 6})

        assert response.status_code == 200
        assert response.json()["party_size"] == 6

    def test_decrease_party_size(self, client: TestClient, created_booking: dict) -> None:
        response = client.patch(f"/bookings/{created_booking['id']}", json={"party_size": 1})

        assert response.status_code == 200
        assert response.json()["party_size"] == 1

    @pytest.mark.parametrize("party_size", [0, 11])
    def test_party_size_outside_range_is_rejected(
        self, client: TestClient, created_booking: dict, party_size: int
    ) -> None:
        response = client.patch(f"/bookings/{created_booking['id']}", json={"party_size": party_size})

        assert response.status_code == 422

    def test_cannot_change_party_size_after_cancellation(
        self, client: TestClient, created_booking: dict
    ) -> None:
        client.patch(f"/bookings/{created_booking['id']}", json={"status": "cancelled"})

        response = client.patch(f"/bookings/{created_booking['id']}", json={"party_size": 5})

        assert response.status_code == 409


class TestDelete:
    def test_delete_returns_204_and_removes_resource(
        self, client: TestClient, created_booking: dict
    ) -> None:
        delete = client.delete(f"/bookings/{created_booking['id']}")

        assert delete.status_code == 204
        assert delete.content == b""
        assert client.get(f"/bookings/{created_booking['id']}").status_code == 404

    def test_delete_unknown_id_returns_404(self, client: TestClient) -> None:
        response = client.delete("/bookings/nope")

        assert response.status_code == 404

    def test_second_delete_returns_404(self, client: TestClient, created_booking: dict) -> None:
        client.delete(f"/bookings/{created_booking['id']}")

        response = client.delete(f"/bookings/{created_booking['id']}")

        assert response.status_code == 404
