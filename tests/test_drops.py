def test_a_malformed_body_answered_422_errors_validation(client):
    """a malformed body answered 422 /errors/validation"""
    r = client.post("/drops", json={"size_class": "XL", "flat": "302"})
    assert r.status_code == 422
    assert r.json()["type"] == "/errors/validation"
    assert [e["field"] for e in r.json()["errors"]] == ["size_class"]


def test_an_unknown_flat_answered_400_errors_no_such_flat(client, db):
    """an unknown flat answered 400 /errors/no-such-flat"""
    r = client.post("/drops", json={"size_class": "M", "flat": "999"})
    assert r.status_code == 400
    assert r.json()["type"] == "/errors/no-such-flat"

    with db() as s:
        assert s.scalar(select(func.count()).select_from(Parcel)) == 0


def test_a_drop_that_fails_part_way_500_for_the_one_transaction_rule(client, db):
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