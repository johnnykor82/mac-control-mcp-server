"""Legacy owned-tab schema retained for local status; no browser actions."""
def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS watcher_tab_leases (
       tag TEXT PRIMARY KEY, delivery_id TEXT NOT NULL, chat_url TEXT NOT NULL,
       opened_at REAL NOT NULL, closed_at REAL, close_reason TEXT, close_error TEXT)""")
    # Migrate databases created by the initial lease implementation in-place.
    columns={row["name"] for row in db.execute("PRAGMA table_info(watcher_tab_leases)")}
    if "close_attempts" not in columns:
        db.execute("ALTER TABLE watcher_tab_leases ADD COLUMN close_attempts INTEGER NOT NULL DEFAULT 0")
    if "last_close_attempt_at" not in columns:
        db.execute("ALTER TABLE watcher_tab_leases ADD COLUMN last_close_attempt_at REAL")
    db.execute("""CREATE INDEX IF NOT EXISTS watcher_tab_leases_open
                  ON watcher_tab_leases(closed_at,opened_at)""")

def summary(db):
    row=db.execute("""SELECT
         SUM(CASE WHEN closed_at IS NULL THEN 1 ELSE 0 END) AS open,
         SUM(CASE WHEN closed_at IS NOT NULL THEN 1 ELSE 0 END) AS closed,
         SUM(CASE WHEN closed_at IS NULL AND close_error IS NOT NULL THEN 1 ELSE 0 END) AS close_failures
         FROM watcher_tab_leases""").fetchone()
    counts={k:int(row[k] or 0) for k in ("open","closed","close_failures")}
    # Expose only failure categories and counts, never draft contents.
    reasons=db.execute("""SELECT close_error,COUNT(*) AS total
         FROM watcher_tab_leases
         WHERE closed_at IS NULL AND close_error IS NOT NULL
         GROUP BY close_error""").fetchall()
    counts["close_failure_reasons"]={r["close_error"]:int(r["total"]) for r in reasons}
    return counts
