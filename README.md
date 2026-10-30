# QA Automation Portfolio — Booking API

A small FastAPI service and the automated test suite that guards it.
The service exists to be tested: it is deliberately built around rules that
break in interesting ways — input validation, a per-date capacity limit,
one-active-booking-per-customer, and a status state machine.

**Result: 54 tests, 100% statement coverage, ~0.7s wall time.**

---

## Why this repository exists

Most "I know pytest" claims are unverifiable. This repository is meant to be
the opposite: you can read the rules in `app/store.py`, read the tests that
pin them down, run one command, and see the same result I do.

The suite is written the way I would write it on a team — grouped by the rule
under test rather than by endpoint, so a red test points at the broken rule
instead of at a URL.

## What is covered

| Area | Tests | What they pin down |
|---|---|---|
| Create — happy path | 4 | 201 shape, initial status, unique ids, whitespace trimming |
| Create — validation | 14 | Party-size range and its boundaries, malformed emails, blank names, past dates, today as boundary, unknown and missing fields |
| Create — business rules | 5 | Duplicate booking (case-insensitive), same customer on a different date, capacity exhaustion, capacity released on cancellation |
| Read | 5 | Single fetch, 404 on unknown id, list, date filter, empty result |
| Update — state machine | 8 | `pending → confirmed`, `pending → cancelled`, `confirmed → cancelled`, cancelled is terminal, no backwards transition, idempotent same-status, invalid enum |
| Update — party size | 6 | Grow, shrink, out-of-range, blocked after cancellation, capacity interaction |
| Delete | 3 | 204 with empty body, resource actually gone, second delete is 404 |
| Ops and store units | 9 | Health check, dependency singleton, store defensive branches |

Two decisions worth calling out:

**TestClient instead of a live server.** Tests run in-process against the ASGI
app. This keeps the suite fast and removes port binding from CI, at the cost of
not exercising the real network stack. If the service ever sits behind a
gateway with its own timeout or retry behaviour, that layer needs a separate
contract test against a deployed instance — this suite would not catch it.

**Every test gets its own store.** Isolation comes from a dependency override
in `tests/conftest.py`, not from cleanup code. Shared mutable state is the most
common cause of order-dependent failures, and this removes the class entirely.

## Layout

```
app/
  main.py         FastAPI app: 5 endpoints, request/response schemas
  store.py        Business rules, state machine, in-memory store
tests/
  conftest.py     Fixtures: isolated client, future date, payload factory
  test_create_booking.py
  test_booking_lifecycle.py
  test_ops_and_store.py
pytest.ini        Markers: smoke / regression
```

## Run it

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

pytest                            # full suite
pytest -m smoke                   # fast gate
pytest --cov=app --cov-report=term-missing
uvicorn app.main:app --reload     # serve it, docs at /docs
```

## CI

`.github/workflows/ci.yml` runs on every push and pull request across Python
3.11, 3.12 and 3.13. It runs the smoke gate first, then the full regression
suite with coverage, and uploads the coverage report.

## Known limitations

- **In-memory storage.** State disappears on restart, and there is no
  concurrency test beyond the lock in `BookingStore`. A real deployment would
  need database-level tests for transaction isolation.
- **No contract testing yet.** Responses are checked field by field, but there
  is no JSON Schema validation, so a silently renamed field would only fail
  where a test happens to read it.
- **No load testing.** The service has no performance budget; k6 scenarios are
  the next addition.
- **Time-dependent rule.** "Not in the past" is tested against `date.today()`,
  which is fine today but would need a frozen clock if the suite ever runs
  across midnight in a timezone different from the service.
