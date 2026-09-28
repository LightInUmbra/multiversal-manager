import time

import pytest

import database as db
import sync


class FakeRemote:
    # What the server does: keep the newest record per row, hand out a log after a cursor
    def __init__(self):
        self.newest, self.log = {}, []

    def push(self, records):
        for r in records:
            key = (r["tbl"], r["uid"])
            if key not in self.newest or r["updated_at"] > self.newest[key]["updated_at"]:
                self.newest[key] = r
                self.log.append(r)

    def pull(self, cursor):
        start = int(cursor or 0)
        return self.log[start:], str(len(self.log))


@pytest.fixture
def devices(tmp_path, monkeypatch):
    # on("pc") / on("phone") switches which device's collection.db the db functions use
    def on(name):
        monkeypatch.setattr(db, "DB_NAME", str(tmp_path / f"{name}.db"))
        db.create_table()
        return db
    return on, FakeRemote()


def _cards():
    return {(r["name"], r["quantity"]) for r in db.get_all_cards()}


def _tick():
    time.sleep(0.01)  # stamps are to the millisecond


def test_new_device_gets_everything(devices):
    on, remote = devices
    on("pc").add_card("Sol Ring", "C21", 1.0, 2, scryfall_id="a")
    deck = db.create_list("Atraxa", "deck", "commander")
    db.add_list_entries(deck, [{"name": "Sol Ring", "set_name": "C21", "price": 1.0, "quantity": 1}])
    db.add_sealed(name="Bloomburrow Bundle")
    assert sync.sync(remote)[0] == 4

    on("phone")
    sync.sync(remote)
    assert _cards() == {("Sol Ring", 2)}
    (phone_deck,) = db.get_lists()
    assert phone_deck["name"] == "Atraxa"
    assert [e["name"] for e in db.get_list_entries(phone_deck["id"])] == ["Sol Ring"]
    assert [s["name"] for s in db.get_sealed()] == ["Bloomburrow Bundle"]

    # Nothing changed, so nothing moves
    assert sync.sync(remote) == (0, 0)
    on("pc")
    assert sync.sync(remote) == (0, 0)


def test_edits_and_deletes_travel_both_ways(devices):
    on, remote = devices
    card = on("pc").add_card("Sol Ring", "C21", 1.0, 1, scryfall_id="a")
    deck = db.create_list("Atraxa", "deck", "commander")
    db.add_list_entries(deck, [{"name": "Sol Ring", "set_name": "C21", "price": 1.0, "quantity": 1}])
    sync.sync(remote)
    on("phone")
    sync.sync(remote)

    _tick()
    (phone_card,) = db.get_all_cards()
    db.update_quantity(phone_card["id"], 4)
    db.delete_list(db.get_lists()[0]["id"])
    sync.sync(remote)

    on("pc")
    sync.sync(remote)
    assert _cards() == {("Sol Ring", 4)}
    assert db.get_lists() == [] and db.get_list_entries(deck) == []

    _tick()
    db.remove_card(card)
    sync.sync(remote)
    on("phone")
    sync.sync(remote)
    assert _cards() == set()


def test_same_field_goes_to_newest_edit_whichever_syncs_last(devices):
    on, remote = devices
    card = on("pc").add_card("Sol Ring", "C21", 1.0, 1, scryfall_id="a")
    sync.sync(remote)
    on("phone")
    sync.sync(remote)

    def set_notes(card_id, notes):
        with db._connect() as conn:
            conn.execute("UPDATE collection SET notes = ? WHERE id = ?", (notes, card_id))

    _tick()
    on("pc")
    set_notes(card, "older")
    _tick()
    on("phone")
    set_notes(db.get_all_cards()[0]["id"], "newer")
    sync.sync(remote)  # the newer edit syncs first...
    on("pc")
    sync.sync(remote)  # ...and the older one doesn't overwrite it
    assert db.get_all_cards()[0]["notes"] == "newer"
    on("phone")
    sync.sync(remote)
    assert db.get_all_cards()[0]["notes"] == "newer"


def _both_have_one_sol_ring(on, remote):
    card = on("pc").add_card("Sol Ring", "C21", 1.0, 2, scryfall_id="a")
    sync.sync(remote)
    on("phone")
    sync.sync(remote)
    return card, db.get_all_cards()[0]["id"]


def test_copies_added_on_both_devices_add_up(devices):
    on, remote = devices
    pc_card, phone_card = _both_have_one_sol_ring(on, remote)
    _tick()
    on("pc").update_quantity(pc_card, 4)       # +2 at home
    on("phone").update_quantity(phone_card, 3)  # +1 at the table
    sync.sync(remote)
    on("pc")
    sync.sync(remote)
    assert _cards() == {("Sol Ring", 5)}
    on("phone")
    sync.sync(remote)
    assert _cards() == {("Sol Ring", 5)}
    # Settled: more syncs change nothing
    assert sync.sync(remote) == (0, 0)
    on("pc")
    assert sync.sync(remote) == (0, 0)


def test_different_fields_both_survive(devices):
    on, remote = devices
    pc_card, phone_card = _both_have_one_sol_ring(on, remote)
    _tick()
    with db._connect() as conn:
        conn.execute("UPDATE collection SET notes = 'signed' WHERE id = ?", (phone_card,))
    on("pc")
    with db._connect() as conn:
        conn.execute("UPDATE collection SET condition = 'LP' WHERE id = ?", (pc_card,))
    sync.sync(remote)
    on("phone")
    sync.sync(remote)
    on("pc")
    sync.sync(remote)
    for device in ("pc", "phone"):
        on(device)
        (row,) = db.get_all_cards()
        assert (row["notes"], row["condition"], row["quantity"]) == ("signed", "LP", 2)


def test_same_card_added_on_both_becomes_one_entry(devices):
    on, remote = devices
    on("pc").add_card("Sol Ring", "C21", 1.0, 2, scryfall_id="a", notes="from the precon")
    deck = db.create_list("Atraxa", "deck", "commander")
    sync.sync(remote)
    on("phone")
    sync.sync(remote)
    phone_deck = db.get_lists()[0]["id"]
    db.add_card("Sol Ring", "C21", 1.0, 1, scryfall_id="a", notes="traded")  # merges with the synced one
    db.add_card("Arcane Signet", "C21", 1.0, 1, scryfall_id="b")
    db.add_list_entries(phone_deck, [{"name": "Arcane Signet", "set_name": "C21", "price": 1.0,
                                      "quantity": 1, "scryfall_id": "b"}])
    on("pc").add_card("Arcane Signet", "C21", 1.0, 2, scryfall_id="b")
    db.add_list_entries(deck, [{"name": "Arcane Signet", "set_name": "C21", "price": 1.0,
                                "quantity": 1, "scryfall_id": "b"}])
    sync.sync(remote)
    on("phone")
    sync.sync(remote)
    on("pc")
    sync.sync(remote)
    for device in ("pc", "phone"):
        on(device)
        assert _cards() == {("Sol Ring", 3), ("Arcane Signet", 3)}
        (entry,) = db.get_list_entries(db.get_lists()[0]["id"])
        assert entry["quantity"] == 2
    assert {r["notes"] for r in db.get_all_cards()} == {"from the precon\ntraded", ""}


def test_restored_backup_wins_on_every_device(devices, tmp_path):
    import shutil

    import backup
    on, remote = devices
    pc_card, _ = _both_have_one_sol_ring(on, remote)
    on("pc")
    shutil.copy(db.DB_NAME, tmp_path / "backup.db")

    _tick()
    on("phone")
    db.update_quantity(db.get_all_cards()[0]["id"], 9)
    db.add_card("Arcane Signet", "C21", 1.0, 1, scryfall_id="b")
    sync.sync(remote)
    on("pc")
    sync.sync(remote)
    assert _cards() == {("Sol Ring", 9), ("Arcane Signet", 1)}

    _tick()
    backup.restore(tmp_path / "backup.db")
    sync.sync(remote)
    assert _cards() == {("Sol Ring", 2)}
    on("phone")
    sync.sync(remote)
    assert _cards() == {("Sol Ring", 2)}

    # Afterwards, edits sync as usual again
    _tick()
    db.add_card("Arcane Signet", "C21", 1.0, 1, scryfall_id="b")
    sync.sync(remote)
    on("pc")
    sync.sync(remote)
    assert _cards() == {("Sol Ring", 2), ("Arcane Signet", 1)}


def test_knows_when_something_is_waiting_to_sync(devices):
    on, remote = devices

    def waiting():
        with db._connect() as conn:
            return sync.has_local_changes(conn)

    card = on("pc").add_card("Sol Ring", "C21", 1.0, 1, scryfall_id="a")
    assert waiting()
    sync.sync(remote)
    assert not waiting()
    db.update_prices([(card, 2.0)])  # a price refresh isn't an edit
    assert not waiting()
    _tick()
    db.update_quantity(card, 3)
    assert waiting()
    sync.sync(remote)
    db.remove_card(card)
    assert waiting()
    sync.sync(remote)
    assert not waiting()


def test_supabase_signs_in_once_per_session(monkeypatch):
    sign_ins = []

    def fake_auth(grant, payload):
        sign_ins.append(payload["refresh_token"])
        return {"refresh_token": f"token{len(sign_ins)}", "access_token": "access", "expires_in": 3600}

    class Empty:
        ok, content = True, b"[]"

        def json(self):
            return []

    monkeypatch.setattr(sync, "_auth", fake_auth)
    monkeypatch.setattr(sync.requests, "get", lambda *a, **k: Empty())
    remote = sync.SupabaseRemote("token0")
    for _ in range(5):
        remote.pull(None)
    assert sign_ins == ["token0"] and remote.refresh_token == "token1"

    remote._expires = time.time() + 30  # about to run out
    remote.pull(None)
    assert sign_ins == ["token0", "token1"] and remote.refresh_token == "token2"


def test_merge_rules():
    base = {"quantity": 2, "notes": "", "condition": "NM"}
    assert sync.merge(base, {**base, "quantity": 4}, {**base, "quantity": 3}, True)["quantity"] == 5
    assert sync.merge(base, {**base, "quantity": 0}, {**base, "quantity": 1}, True)["quantity"] == 0
    both = sync.merge(base, {**base, "notes": "mine"}, {**base, "notes": "theirs"}, mine_newer=False)
    assert both["notes"] == "theirs"


def test_unknown_tables_and_columns_are_ignored(temp_db):
    with db._connect() as conn:
        applied = sync.apply(conn, [
            {"tbl": "sqlite_master", "uid": "x", "updated_at": "2030", "deleted": True, "data": None},
            {"tbl": "sealed", "uid": "s", "updated_at": "2030", "deleted": False,
             "data": {"name": "Box", "quantity": 1, "notes": "", "from_a_newer_version": 1}},
        ])
    assert applied == 1
    assert [s["name"] for s in db.get_sealed()] == ["Box"]
