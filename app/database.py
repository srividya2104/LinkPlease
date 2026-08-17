from contextlib import contextmanager
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple


class Database:

    def __init__(self, db_path: str = "linkplease.db"):
        self.db_path = db_path
        self.init_db()

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=10000;")
            yield conn
        finally:
            conn.close()

    def init_db(self):
        with self.get_connection() as conn:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS rules (
                        id TEXT PRIMARY KEY,
                        keyword TEXT NOT NULL,
                        dm_message TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """
                )

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS events (
                        event_id TEXT PRIMARY KEY,
                        received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """
                )

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS deliveries (
                        id TEXT PRIMARY KEY,
                        rule_id TEXT NOT NULL,
                        recipient_user_id TEXT NOT NULL,
                        comment_id TEXT NOT NULL,
                        idempotency_key TEXT UNIQUE NOT NULL,
                        message TEXT NOT NULL,
                        status TEXT NOT NULL,
                        dm_id TEXT,
                        attempt_count INTEGER DEFAULT 0,
                        next_attempt_at REAL,
                        last_error TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """
                )

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS counters (
                        name TEXT PRIMARY KEY,
                        val INTEGER DEFAULT 0
                    );
                """
                )

                conn.execute(
                    """
                    INSERT INTO counters (name, val) VALUES ('duplicates_blocked', 0)
                    ON CONFLICT(name) DO NOTHING;
                """
                )

                conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_deliveries_idempotency"
                    " ON deliveries(idempotency_key);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_deliveries_status ON"
                    " deliveries(status, next_attempt_at);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_deliveries_comment_id ON"
                    " deliveries(comment_id);"
                )

    def insert_rule(
        self, rule_id: str, keyword: str, dm_message: str
    ) -> Dict[str, Any]:
        with self.get_connection() as conn:
            with conn:
                conn.execute(
                    "INSERT INTO rules (id, keyword, dm_message) VALUES (?, ?,"
                    " ?)",
                    (rule_id, keyword, dm_message),
                )
        return {"rule_id": rule_id, "keyword": keyword, "dm_message": dm_message}

    def get_all_rules(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT id, keyword, dm_message FROM rules")
            return [
                {
                    "rule_id": row["id"],
                    "keyword": row["keyword"],
                    "dm_message": row["dm_message"],
                }
                for row in cursor.fetchall()
            ]

    def record_event_if_new(self, event_id: str) -> bool:
        """Returns True if the event was newly inserted, False if it already existed."""
        with self.get_connection() as conn:
            with conn:
                cursor = conn.execute(
                    "INSERT INTO events (event_id) VALUES (?) ON"
                    " CONFLICT(event_id) DO NOTHING",
                    (event_id,),
                )
                return cursor.rowcount > 0

    def increment_duplicates_blocked(self, count: int = 1):
        with self.get_connection() as conn:
            with conn:
                conn.execute(
                    "UPDATE counters SET val = val + ? WHERE name ="
                    " 'duplicates_blocked'",
                    (count,),
                )

    def get_delivery_by_idempotency_key(
        self, idempotency_key: str
    ) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM deliveries WHERE idempotency_key = ?",
                (idempotency_key,),
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def create_delivery(
        self,
        delivery_id: str,
        rule_id: str,
        recipient_user_id: str,
        comment_id: str,
        idempotency_key: str,
        message: str,
    ) -> bool:
        """Attempts to create a delivery record.

        If idempotency_key already exists, returns False and increments
        duplicates_blocked. Otherwise returns True.
        """
        now = time.time()
        with self.get_connection() as conn:
            with conn:
                try:
                    conn.execute(
                        """
                        INSERT INTO deliveries (
                            id, rule_id, recipient_user_id, comment_id, idempotency_key, message, status, attempt_count, next_attempt_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?);
                    """,
                        (
                            delivery_id,
                            rule_id,
                            recipient_user_id,
                            comment_id,
                            idempotency_key,
                            message,
                            now,
                            now,
                        ),
                    )
                    return True
                except sqlite3.IntegrityError:
                    conn.execute(
                        "UPDATE counters SET val = val + 1 WHERE name ="
                        " 'duplicates_blocked'"
                    )
                    return False

    def claim_pending_deliveries(self, limit: int = 1) -> List[Dict[str, Any]]:
        """Atomically claims up to `limit` pending deliveries where next_attempt_at <= now."""
        now = time.time()
        claimed = []
        with self.get_connection() as conn:
            with conn:
                # Find matching pending IDs
                cursor = conn.execute(
                    """
                    SELECT id FROM deliveries
                    WHERE status = 'pending' AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                    ORDER BY created_at ASC
                    LIMIT ?
                """,
                    (now, limit),
                )
                ids = [row["id"] for row in cursor.fetchall()]
                if not ids:
                    return []

                placeholders = ",".join("?" for _ in ids)
                conn.execute(
                    f"""
                    UPDATE deliveries
                    SET status = 'sending', updated_at = ?
                    WHERE id IN ({placeholders}) AND status = 'pending'
                """,
                    [now] + ids,
                )

                cursor = conn.execute(
                    f"SELECT * FROM deliveries WHERE id IN ({placeholders})", ids
                )
                claimed = [dict(row) for row in cursor.fetchall()]
        return claimed

    def update_delivery(
        self,
        delivery_id: str,
        status: str,
        dm_id: Optional[str] = None,
        next_attempt_at: Optional[float] = None,
        last_error: Optional[str] = None,
        increment_attempt: bool = False,
    ):
        now = time.time()
        with self.get_connection() as conn:
            with conn:
                query = "UPDATE deliveries SET status = ?, updated_at = ?"
                params: List[Any] = [status, now]

                if dm_id is not None:
                    query += ", dm_id = ?"
                    params.append(dm_id)

                if next_attempt_at is not None:
                    query += ", next_attempt_at = ?"
                    params.append(next_attempt_at)

                if last_error is not None:
                    query += ", last_error = ?"
                    params.append(last_error)

                if increment_attempt:
                    query += ", attempt_count = attempt_count + 1"

                query += " WHERE id = ?"
                params.append(delivery_id)

                conn.execute(query, params)

    def get_accepted_deliveries_for_reconciliation(
        self, limit: int = 10
    ) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM deliveries
                WHERE status = 'dm_accepted' AND dm_id IS NOT NULL
                ORDER BY updated_at ASC
                LIMIT ?
            """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def cancel_pending_by_comment_id(self, comment_id: str) -> bool:
        """Cancels a pending or sending delivery if the comment was deleted before acceptance."""
        now = time.time()
        with self.get_connection() as conn:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE deliveries
                    SET status = 'cancelled', updated_at = ?, last_error = 'comment_deleted'
                    WHERE comment_id = ? AND status IN ('pending', 'sending')
                """,
                    (now, comment_id),
                )
                return cursor.rowcount > 0

    def reset_stuck_deliveries(self, timeout_seconds: float = 30.0):
        """Resets deliveries stuck in 'sending' state back to 'pending' if worker crashed."""
        threshold = time.time() - timeout_seconds
        now = time.time()
        with self.get_connection() as conn:
            with conn:
                conn.execute(
                    """
                    UPDATE deliveries
                    SET status = 'pending', next_attempt_at = ?, updated_at = ?
                    WHERE status = 'sending' AND updated_at < ?
                """,
                    (now, now, threshold),
                )

    def get_stats(self) -> Dict[str, int]:
        with self.get_connection() as conn:
            # Query counts grouped by status
            cursor = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM deliveries GROUP BY status"
            )
            counts = {row["status"]: row["cnt"] for row in cursor.fetchall()}

            # duplicates_blocked
            cursor2 = conn.execute(
                "SELECT val FROM counters WHERE name = 'duplicates_blocked'"
            )
            dup_row = cursor2.fetchone()
            duplicates_blocked = dup_row["val"] if dup_row else 0

            # 'queued' includes: pending, sending, dm_accepted
            sent = counts.get("sent", 0)
            failed = counts.get("failed", 0)
            queued = (
                counts.get("pending", 0)
                + counts.get("sending", 0)
                + counts.get("dm_accepted", 0)
            )

            return {
                "sent": sent,
                "failed": failed,
                "queued": queued,
                "duplicates_blocked": duplicates_blocked,
            }
