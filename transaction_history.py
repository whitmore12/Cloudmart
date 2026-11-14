"""Read-only transaction history for the CloudMart wallet.

The connection factory is passed in by app.py, avoiding database connections or
circular Flask imports at module import time.
"""


def get_transaction_history(get_db_connection, user_id, limit=20, offset=0):
    """Return transactions visible to one user, most recent first.

    A purchase creates two legacy rows with the same sender and receiver:
      purchase -> show only to buyer (debit)
      sale     -> show only to seller (credit)
    A transfer is shown to both sides. Other transaction types are shown to
    participants; the frontend signs the amount based on direction.

    WARNING: This data access function is not an authentication mechanism.
    The HTTP route must enforce identity/authorization separately.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.id, t.from_user_id, t.to_user_id,
                       sender.username, receiver.username,
                       t.amount, t.type, t.created_at
                FROM transactions AS t
                LEFT JOIN users AS sender ON sender.id = t.from_user_id
                LEFT JOIN users AS receiver ON receiver.id = t.to_user_id
                WHERE (t.type = 'purchase' AND t.from_user_id = %s)
                   OR (t.type = 'sale' AND t.to_user_id = %s)
                   OR ((t.type IS NULL OR t.type NOT IN ('purchase', 'sale'))
                       AND (t.from_user_id = %s OR t.to_user_id = %s))
                ORDER BY t.created_at DESC, t.id DESC
                LIMIT %s OFFSET %s
                """,
                (user_id, user_id, user_id, user_id, limit, offset),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        {
            "id": row[0],
            "from_user_id": row[1],
            "to_user_id": row[2],
            "from_username": row[3] or "Unknown user",
            "to_username": row[4] or "Unknown user",
            "amount": float(row[5]),
            "type": row[6] or "transfer",
            "created_at": row[7].isoformat() if row[7] else None,
        }
        for row in rows
    ]
