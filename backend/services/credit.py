"""Credit balance. The only module in this repo that changes it.

Pay-per-generation spends real money from the first MVP run (Product.md 6), so the whole
billing story is deliberately squeezed into one function. `UPDATE account` appears nowhere
else in the tree and tests/test_billing_integrity.py greps to keep it that way — auditing
AC-4 should mean reading one file, not tracing a pipeline.

Unit: 1 successful generation = 1 credit. Not money. Pricing is still open in Product.md 6,
and when it lands it changes what a credit costs, not what a credit is.
"""

from backend.models import request_log


def balance(conn):
    return conn.execute("SELECT credits FROM account WHERE id = 1").fetchone()[0]


def has_credit(conn, amount=1):
    return balance(conn) >= amount


def charge_for(conn, request_id):
    """Deduct exactly 1 credit for a request that actually produced an image.

    Both preconditions — the request reached api_success, and it has never been charged —
    are in the WHERE clause, so calling this twice, early, or on a failed request cannot
    take money. Returns True only if this call is the one that charged.
    """
    with conn:
        cur = conn.execute(
            "UPDATE requests SET charged = 1"
            " WHERE request_id = ? AND status = ? AND charged = 0",
            (request_id, request_log.API_SUCCESS),
        )
        if cur.rowcount != 1:
            return False
        conn.execute("UPDATE account SET credits = credits - 1 WHERE id = 1")
    return True


def topup(conn, amount):
    """Manual top-up. Single-account MVP, so this is a command, not a payment flow."""
    if amount <= 0:
        raise ValueError("top-up amount must be positive")
    with conn:
        conn.execute("UPDATE account SET credits = credits + ? WHERE id = 1", (amount,))
    return balance(conn)


if __name__ == "__main__":
    import sys

    conn = request_log.connect()
    if len(sys.argv) == 3 and sys.argv[1] == "topup":
        print(f"credits: {topup(conn, int(sys.argv[2]))}")
    elif len(sys.argv) == 1:
        print(f"credits: {balance(conn)}")
    else:
        print("usage: python -m backend.services.credit [topup <n>]")
        raise SystemExit(2)
