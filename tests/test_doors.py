"""
Tests for drops:
- a malformed body answered 422 /errors/validation
- an unknown flat answered 400 /errors/no-such-flat
- a drop that fails part-way (500), for the one-transaction rule
"""

from sqlalchemy import func, select, text

from lockerline.models import Door, Parcel
from tests.conftest import drop, fill


def test_drop_takes_lowest_free_door_of_exact_size(client, db):
    body = drop(client, "M", "302")
    assert body["door"] == "D21" and body["size_class"] == "M" and body["flat"] == "302"


def test_id_and_time_roundtrip(client):
    body = drop(client, "M", "302")
    assert body["parcel_id"].startswith("P") and body["dropped_at"] == "2026-09-25T13:10:00Z"
    assert client.get(f"/parcels/{body['parcel_id']}").json()["dropped_at"] == "2026-09-25T13:10:00Z"


def test_door_is_taken_and_next_uses_next_door(client, db):
    body = drop(client, "M", "302")
    with db() as s:
        door = s.scalar(select(Door).where(Door.no == "D21"))
        assert door.current_parcel_id is not None

    assert drop(client, "M", "302")["door"] == "D22"


def test_location_header_points_at_the_parcel(client):
    r = client.post("/drops", json={"size_class": "S", "flat": "101"})
    assert r.headers["location"] == f"/parcels/{r.json()['parcel_id']}"
    assert client.get(r.headers["location"]).status_code == 200


def test_unknown_flat(client, db):
    """an unknown flat answered 400 /errors/no-such-flat"""
    r = client.post("/drops", json={"size_class": "M", "flat": "999"})
    assert r.status_code == 400 and r.json()["type"] == "/errors/no-such-flat"

    with db() as s:
        assert s.scalar(select(func.count()).select_from(Parcel)) == 0


def test_malformed_body(client):
    """a malformed body answered 422 /errors/validation"""
    r = client.post("/drops", json={"size_class": "XL", "flat": "302"})
    assert r.status_code == 422 and r.json()["type"] == "/errors/validation"
    assert [e["field"] for e in r.json()["errors"]] == ["size_class"]


def test_no_door_free_lists_free_sizes(client):
    fill(client, "L")
    r = client.post("/drops", json={"size_class": "L", "flat": "302"})
    assert r.status_code == 409 and r.json()["type"] == "/errors/no-door-free"
    assert r.json()["free_sizes"] == ["S", "M"]


def test_transaction_rollback_on_failure(client, db):
    """a drop that fails part-way (500), for the one-transaction rule"""
    with db() as s:
        s.execute(
            text(
                "CREATE TRIGGER fail_hold BEFORE UPDATE ON doors WHEN NEW.current_parcel_id IS NOT NULL "
                "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
            )
        )
        s.commit()

    r = client.post("/drops", json={"size_class": "M", "flat": "302"})
    assert r.status_code == 500

    with db() as s:
        assert s.scalar(select(func.count()).select_from(Parcel)) == 0
        door = s.scalar(select(Door).where(Door.no == "D21"))
        assert door.current_parcel_id is None