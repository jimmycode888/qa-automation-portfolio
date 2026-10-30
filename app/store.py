"""Domain model and in-memory store for the booking API.

The store is deliberately simple (a dict guarded by a lock) so that the
project stays about *testing*, not about persistence. A real service would
swap `BookingStore` for a database repository with the same interface.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum

# Business rules — the numbers a test plan should pin down.
MAX_PARTY_SIZE = 10
MAX_SEATS_PER_DATE = 20


class BookingStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


# Allowed transitions. Anything not listed is rejected with 409.
ALLOWED_TRANSITIONS: dict[BookingStatus, set[BookingStatus]] = {
    BookingStatus.PENDING: {BookingStatus.CONFIRMED, BookingStatus.CANCELLED},
    BookingStatus.CONFIRMED: {BookingStatus.CANCELLED},
    BookingStatus.CANCELLED: set(),
}


@dataclass
class Booking:
    customer_name: str
    email: str
    booking_date: date
    party_size: int
    notes: str | None = None
    status: BookingStatus = BookingStatus.PENDING
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BookingStore:
    """Thread-safe in-memory store. `reset()` exists purely for tests."""

    def __init__(self) -> None:
        self._items: dict[str, Booking] = {}
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._items.clear()

    def all(self) -> list[Booking]:
        with self._lock:
            return list(self._items.values())

    def get(self, booking_id: str) -> Booking | None:
        with self._lock:
            return self._items.get(booking_id)

    def seats_taken(self, booking_date: date) -> int:
        """Seats already committed for a date. Cancelled bookings free their seats."""
        with self._lock:
            return sum(
                b.party_size
                for b in self._items.values()
                if b.booking_date == booking_date and b.status is not BookingStatus.CANCELLED
            )

    def has_duplicate(self, email: str, booking_date: date) -> bool:
        """One active booking per customer per date."""
        with self._lock:
            return any(
                b.email.lower() == email.lower()
                and b.booking_date == booking_date
                and b.status is not BookingStatus.CANCELLED
                for b in self._items.values()
            )

    def add(self, booking: Booking) -> Booking:
        with self._lock:
            self._items[booking.id] = booking
            return booking

    def update(self, booking_id: str, **changes: object) -> Booking | None:
        with self._lock:
            booking = self._items.get(booking_id)
            if booking is None:
                return None
            for key, value in changes.items():
                setattr(booking, key, value)
            return booking

    def delete(self, booking_id: str) -> bool:
        with self._lock:
            return self._items.pop(booking_id, None) is not None
