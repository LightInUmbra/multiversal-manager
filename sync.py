# Two-way sync of what the user made themselves (cards, decks and their entries, sealed
# product) between this device and a remote store shared by all their devices.
#
# A record is {"tbl", "uid", "updated_at", "deleted", "data"}: one row, or a deletion
# (data None). The remote keeps the newest record per (tbl, uid) and hands back records
# written after a cursor.
#
# Each device keeps every row as it was when last synced (sync_shadow), which tells it
# what changed here since. When a row changed both here and elsewhere, the changes are
# merged field by field against that version: quantities add up, and a field changed on
# both sides goes to the newer edit. Afterwards, copies that turn out to be the same card
# (added on two devices) become one entry, the way adding a card twice does.
import json

import requests

import database as db

# The Supabase project holding every device's records (schema: supabase/schema.sql).
# The publishable key is meant to ship in apps; row-level security keeps each account to its own rows.
SUPABASE_URL = "https://aepdyzawmgpwcmxytocu.supabase.co"
SUPABASE_KEY = "sb_publishable_yL1ZQ5fwf9dBOkEv79rv0w_fVXELPyb"
TIMEOUT = 30
_PAGE = 1000  # Supabase's most rows per request

# Parents before children, so a deck exists before its entries arrive
TABLES = ("lists", "list_entries", "collection", "sealed")
# Local ids differ per device; entries refer to their deck by uid (list_uid) instead
_LOCAL_ONLY = ("id", "uid", "updated_at", "list_id")
# Entries that mean the same cards, as when adding them in the app. Collection entries
# without a printing (typed in by hand) never merge.
_SAME = {"collection": ("scryfall_id", "foil", "condition", "language"),
         "list_entries": ("list_id", "section", "scryfall_id", "foil", "name")}


def _get(conn, key):
    row = conn.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def _set(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO sync_state (key, value) VALUES (?, ?)", (key, value))


def _select(table):
    if table == "list_entries":
        return "SELECT t.*, l.uid AS list_uid FROM list_entries t LEFT JOIN lists l ON l.id = t.list_id"
    return f"SELECT t.* FROM {table} t"


def _data(row):
    return {k: row[k] for k in row.keys() if k not in _LOCAL_ONLY}


def _remember(conn, records):
    # These versions are on the remote now
    conn.executemany("INSERT OR REPLACE INTO sync_shadow (tbl, uid, updated_at, data) VALUES (?, ?, ?, ?)",
                     [(r["tbl"], r["uid"], r["updated_at"], None if r["deleted"] else json.dumps(r["data"]))
                      for r in records])


def local_changes(conn):
    """Records for every row edited or deleted here since it was last synced"""
    records = []
    for table in TABLES:
        for row in conn.execute(f"{_select(table)} LEFT JOIN sync_shadow s ON s.tbl = ? AND s.uid = t.uid "
                                "WHERE s.updated_at IS NOT t.updated_at", (table,)):
            records.append({"tbl": table, "uid": row["uid"], "updated_at": row["updated_at"], "deleted": False,
                            "data": _data(row)})
    for row in conn.execute("SELECT t.* FROM sync_tombstones t LEFT JOIN sync_shadow s "
                            "ON s.tbl = t.tbl AND s.uid = t.uid WHERE s.updated_at IS NOT t.deleted_at"):
        records.append({"tbl": row["tbl"], "uid": row["uid"], "updated_at": row["deleted_at"], "deleted": True,
                        "data": None})
    return records


def merge(base, mine, theirs, mine_newer):
    """Combines two edits of the same row, given the version both started from"""
    merged = {}
    for k in base.keys() | mine.keys() | theirs.keys():
        b = base.get(k)
        m, t = mine.get(k, b), theirs.get(k, b)
        if m == b or t == m:
            merged[k] = t
        elif t == b:
            merged[k] = m
        elif k == "quantity" and None not in (b, m, t):
            merged[k] = max(0, m + t - b)  # both added (or removed) copies
        else:
            merged[k] = m if mine_newer else t
    return merged


def _write(conn, table, uid, row_id, data, stamp):
    # Returns the row's id, or None when it can't be written (its deck is gone)
    data = dict(data)
    if table == "list_entries":
        parent = conn.execute("SELECT id FROM lists WHERE uid = ?", (data.pop("list_uid", None),)).fetchone()
        if not parent:
            return None
        data["list_id"] = parent["id"]
    # Names come from the remote, so only this table's own columns are written
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    data = {k: v for k, v in data.items() if k in columns and k not in ("id", "uid")}
    data["updated_at"] = stamp
    if row_id:
        conn.execute(f"UPDATE {table} SET {', '.join(f'{k} = ?' for k in data)} WHERE id = ?",
                     [*data.values(), row_id])
        return row_id
    data["uid"] = uid
    row_id = conn.execute(f"INSERT INTO {table} ({', '.join(data)}) VALUES ({', '.join('?' * len(data))})",
                          list(data.values())).lastrowid
    conn.execute("DELETE FROM sync_tombstones WHERE tbl = ? AND uid = ?", (table, uid))
    return row_id


def _delete(conn, table, uid, row_id, stamp):
    if row_id:
        conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
    # Keep the other device's time rather than the trigger's
    conn.execute("INSERT OR REPLACE INTO sync_tombstones (tbl, uid, deleted_at) VALUES (?, ?, ?)",
                 (table, uid, stamp))


def _merge_duplicates(conn, table, row_id):
    # Folds entries meaning the same cards into the one with the lowest uid, so every
    # device keeps the same one; the others are deleted, which syncs like any delete
    key = _SAME[table]
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    if not row or row["scryfall_id"] is None and table == "collection":
        return
    rows = conn.execute(f"SELECT * FROM {table} WHERE {' AND '.join(f'{k} IS ?' for k in key)} ORDER BY uid",
                        [row[k] for k in key]).fetchall()
    if len(rows) < 2:
        return
    keep, *rest = rows
    fields = {"quantity": sum(r["quantity"] for r in rows)}
    if table == "collection":
        fields["notes"] = keep["notes"]
        for r in rest:
            fields["notes"] = db.merge_notes(fields["notes"], r["notes"])
    conn.execute(f"UPDATE {table} SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                 [*fields.values(), keep["id"]])
    conn.executemany(f"DELETE FROM {table} WHERE id = ?", [(r["id"],) for r in rest])


def after_restore(conn):
    """A restored backup replaces the collection on every device: everything in it is
    stamped now, so it wins, and the next sync pulls everything again to delete what the
    backup doesn't have (see apply)."""
    now = conn.execute(f"SELECT {db.SYNC_NOW}").fetchone()[0]
    for table in TABLES:
        conn.execute(f"UPDATE {table} SET updated_at = ?", (now,))
    conn.execute("UPDATE sync_tombstones SET deleted_at = ?", (now,))
    conn.execute("DELETE FROM sync_shadow")
    _set(conn, "pulled_until", None)
    _set(conn, "restored_at", now)


def apply(conn, records):
    """Brings in records from other devices, merging with what changed here since the
    last sync. Table and column names come from the remote, so only known ones are used.
    Returns how many records changed something here."""
    order = {table: i for i, table in enumerate(TABLES)}
    restored = _get(conn, "restored_at")
    applied, written = 0, []
    for r in sorted((r for r in records if r["tbl"] in order), key=lambda r: order[r["tbl"]]):
        table, uid, stamp = r["tbl"], r["uid"], r["updated_at"]
        shadow = conn.execute("SELECT updated_at, data FROM sync_shadow WHERE tbl = ? AND uid = ?",
                              (table, uid)).fetchone()
        if shadow and stamp <= shadow["updated_at"]:
            continue  # seen it already (or sent it)
        row = conn.execute(f"{_select(table)} WHERE t.uid = ?", (uid,)).fetchone()
        tomb = conn.execute("SELECT deleted_at FROM sync_tombstones WHERE tbl = ? AND uid = ?",
                            (table, uid)).fetchone()
        mine = row["updated_at"] if row else tomb["deleted_at"] if tomb else None
        _remember(conn, [r])
        row_id = row["id"] if row else None
        if restored and stamp < restored:
            # From before a backup was restored here: the backup wins, and what it doesn't have goes
            if not row and not tomb:
                _delete(conn, table, uid, None, restored)
            continue
        changed_here = mine is not None and mine != (shadow["updated_at"] if shadow else None)

        if not changed_here or (stamp > mine and (r["deleted"] or not row or not (shadow and shadow["data"]))):
            # Only the other side changed, or one side deleted it and the other's newer
            if r["deleted"]:
                _delete(conn, table, uid, row_id, stamp)
            else:
                written.append((table, _write(conn, table, uid, row_id, r["data"], stamp)))
        elif row and not r["deleted"] and shadow and shadow["data"]:
            # Both edited it: merge, stamped now so it goes out as the newest version
            merged = merge(json.loads(shadow["data"]), _data(row), r["data"], mine > stamp)
            now = conn.execute(f"SELECT {db.SYNC_NOW}").fetchone()[0]
            written.append((table, _write(conn, table, uid, row_id, merged, max(now, stamp, mine))))
        else:
            continue  # the change here is newer and goes out next
        applied += 1

    for table, row_id in written:
        if table in _SAME and row_id:
            _merge_duplicates(conn, table, row_id)
    return applied


def sync(remote):
    """Pulls everyone else's changes, merges them with this device's, then pushes this
    device's. remote has push(records) and pull(cursor) -> (records, new cursor). A
    failure part way is safe: whatever wasn't pushed differs from its shadow and goes next time.
    Returns (records pushed, records applied)."""
    with db._connect() as conn:
        cursor = _get(conn, "pulled_until")
    records, cursor = remote.pull(cursor)
    with db._connect() as conn:
        applied = apply(conn, records)
        _set(conn, "pulled_until", cursor)
        _set(conn, "restored_at", None)  # everything from before it has been pulled and dealt with
        changes = local_changes(conn)
    if changes:
        remote.push(changes)
        with db._connect() as conn:
            _remember(conn, changes)
    return len(changes), applied


# Supabase

class SyncError(Exception):
    pass


def _check(response):
    if response.ok:
        return response.json() if response.content else None
    try:
        body = response.json()
    except ValueError:
        body = {}
    message = body.get("error_description") or body.get("msg") or body.get("message") or response.reason
    raise SyncError(message)


def _auth(grant, payload):
    # A session: access_token (good for an hour) and refresh_token (keeps the device signed in)
    return _check(requests.post(f"{SUPABASE_URL}/auth/v1/token", params={"grant_type": grant}, json=payload,
                                headers={"apikey": SUPABASE_KEY}, timeout=TIMEOUT))


def sign_in(email, password):
    """Returns the refresh token that keeps this device signed in"""
    return _auth("password", {"email": email, "password": password})["refresh_token"]


def sign_up(email, password):
    """Creates an account. Returns its refresh token, or None when Supabase first wants
    the email address confirmed (via the link it sends)."""
    body = _check(requests.post(f"{SUPABASE_URL}/auth/v1/signup", json={"email": email, "password": password},
                                headers={"apikey": SUPABASE_KEY}, timeout=TIMEOUT))
    return body.get("refresh_token")


class SupabaseRemote:
    """The remote for sync(). Signing in again uses up refresh_token, so save
    self.refresh_token (its replacement) afterwards."""

    def __init__(self, refresh_token):
        session = _auth("refresh_token", {"refresh_token": refresh_token})
        self.refresh_token = session["refresh_token"]
        self.email = session["user"]["email"]
        self._headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {session['access_token']}"}

    def push(self, records, batch=500):
        for start in range(0, len(records), batch):
            _check(requests.post(f"{SUPABASE_URL}/rest/v1/rpc/push_records", headers=self._headers,
                                 json={"records": records[start:start + batch]}, timeout=TIMEOUT))

    def pull(self, cursor):
        records, cursor = [], int(cursor or 0)
        while True:
            page = _check(requests.get(f"{SUPABASE_URL}/rest/v1/records", headers=self._headers, timeout=TIMEOUT,
                                       params={"select": "tbl,uid,updated_at,deleted,data,seq",
                                               "seq": f"gt.{cursor}", "order": "seq", "limit": _PAGE}))
            records += page
            if page:
                cursor = page[-1]["seq"]
            if len(page) < _PAGE:
                return records, str(cursor)
