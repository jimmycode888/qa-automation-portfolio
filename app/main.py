"""Booking API — the system under test for this QA portfolio.

Five endpoints over a single resource, with rules that are worth testing:
input validation, a per-date capacity limit, one-active-booking-per-customer,
and a status state machine. Those rules are where real defects live, so the
test suite targets them rather than just happy paths.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.store import (
    ALLOWED_TRANSITIONS,
    MAX_PARTY_SIZE,
    MAX_SEATS_PER_DATE,
    Booking,
    BookingStatus,
    BookingStore,
)

app = FastAPI(
    title="Workshop Booking API",
    version="1.0.0",
    description="Small service used as the system under test for an automated test suite.",
)

store = BookingStore()


def get_store() -> BookingStore:
    """Dependency hook so tests can swap in a fresh store."""
    return store


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------


class BookingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_name: str = Field(min_length=1, max_length=60)
    email: EmailStr
    booking_date: date
    party_size: int = Field(ge=1, le=MAX_PARTY_SIZE)
    notes: str | None = Field(default=None, max_length=200)

    @field_validator("booking_date")
    @classmethod
    def not_in_the_past(cls, value: date) -> date:
        if value < date.today():
            raise ValueError("booking_date must not be in the past")
        return value

    @field_validator("customer_name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("customer_name must not be blank")
        return value.strip()


class BookingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: BookingStatus | None = None
    party_size: int | None = Field(default=None, ge=1, le=MAX_PARTY_SIZE)


class BookingOut(BaseModel):
    id: str
    customer_name: str
    email: str
    booking_date: date
    party_size: int
    notes: str | None
    status: BookingStatus


def to_out(booking: Booking) -> BookingOut:
    return BookingOut(
        id=booking.id,
        customer_name=booking.customer_name,
        email=booking.email,
        booking_date=booking.booking_date,
        party_size=booking.party_size,
        notes=booking.notes,
        status=booking.status,
    )


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/bookings", status_code=status.HTTP_201_CREATED, response_model=BookingOut, tags=["bookings"])
def create_booking(payload: BookingCreate, db: Annotated[BookingStore, Depends(get_store)]) -> BookingOut:
    if db.has_duplicate(payload.email, payload.booking_date):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="customer already has an active booking on that date",
        )

    seats_left = MAX_SEATS_PER_DATE - db.seats_taken(payload.booking_date)
    if payload.party_size > seats_left:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"only {seats_left} seat(s) left on that date",
        )

    booking = Booking(
        customer_name=payload.customer_name,
        email=str(payload.email),
        booking_date=payload.booking_date,
        party_size=payload.party_size,
        notes=payload.notes,
    )
    db.add(booking)
    return to_out(booking)


@app.get("/bookings/{booking_id}", response_model=BookingOut, tags=["bookings"])
def read_booking(booking_id: str, db: Annotated[BookingStore, Depends(get_store)]) -> BookingOut:
    booking = db.get(booking_id)
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="booking not found")
    return to_out(booking)


@app.get("/bookings", response_model=list[BookingOut], tags=["bookings"])
def list_bookings(
    db: Annotated[BookingStore, Depends(get_store)],
    on: Annotated[date | None, Query(alias="date", description="filter by booking date")] = None,
) -> list[BookingOut]:
    items = db.all()
    if on is not None:
        items = [b for b in items if b.booking_date == on]
    return [to_out(b) for b in sorted(items, key=lambda b: (b.booking_date, b.created_at))]


@app.patch("/bookings/{booking_id}", response_model=BookingOut, tags=["bookings"])
def update_booking(
    booking_id: str,
    payload: BookingPatch,
    db: Annotated[BookingStore, Depends(get_store)],
) -> BookingOut:
    booking = db.get(booking_id)
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="booking not found")

    if payload.status is not None and payload.status is not booking.status:
        if payload.status not in ALLOWED_TRANSITIONS[booking.status]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"cannot move from {booking.status.value} to {payload.status.value}",
            )
        booking = db.update(booking_id, status=payload.status)  # type: ignore[assignment]

    if payload.party_size is not None and payload.party_size != booking.party_size:
        if booking.status is BookingStatus.CANCELLED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="cannot change party_size on a cancelled booking",
            )
        delta = payload.party_size - booking.party_size
        seats_left = MAX_SEATS_PER_DATE - db.seats_taken(booking.booking_date)
        if delta > seats_left:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"only {seats_left} extra seat(s) available on that date",
            )
        booking = db.update(booking_id, party_size=payload.party_size)  # type: ignore[assignment]

    return to_out(booking)


@app.delete("/bookings/{booking_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["bookings"])
def delete_booking(booking_id: str, db: Annotated[BookingStore, Depends(get_store)]) -> Response:
    if not db.delete(booking_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="booking not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
