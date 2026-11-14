from application import get_db_connection



def check_if_user_exists(user_id):
    '''
    
    Purpose: Checks if the user exists in the database.
    Return True if the user exists, False otherwise.
    Made by Erick Constant

    '''
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM users WHERE id = %s", (user_id,))
        return cur.fetchone() is not None
    finally:
        cur.close()
        conn.close()



def get_balance(user_id):
    '''
    Purpose: Return the balance of the user, or None if the user does not exist.
    Edited by Vaughn Huey
    '''
    conn = get_db_connection()
    cur = conn.cursor()

    if not check_if_user_exists(user_id):
        return 0.0

    
    try:
        cur.execute("SELECT pirate_dollars FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        return float(row[0]) if row else 0.0
    finally:
        cur.close()
        conn.close()


def check_for_sufficient_funds(user_id, value):
    '''
    Purpose: Check if the user has sufficient funds to make a purchase.
    Returns True for sufficient, False for insufficient funds.
    Edited by Vaughn Huey
    '''
    current_balance = get_balance(user_id)
    return current_balance >= value

def update_money(user_id, new_balance):
    '''
    Purpose: Update the money of the user in the database and commit.
    Edited by Vaughn Huey
    '''
    conn = get_db_connection()
    cur = conn.cursor()

    if not check_if_user_exists(user_id):
        return 0.0


    try:
        cur.execute(
            "UPDATE users SET pirate_dollars = %s WHERE id = %s",
            (new_balance, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()


def transfer_money(buyer_id, seller_id, cost):
    '''
    Purpose: Transfers the money from one user to another and updates it.
    Returns 0 for complete, returns 1 for incomplete (insufficient funds).
    Edited by Vaughn Huey
    '''
    
    
    if not check_for_sufficient_funds(buyer_id, cost):
        return 1

    buyer_balance = get_balance(buyer_id)
    seller_balance = get_balance(seller_id)

    buyer_updated = buyer_balance - cost
    seller_updated = seller_balance + cost
    
    update_money(buyer_id, buyer_updated)
    update_money(seller_id, seller_updated)
    return 0


def get_transaction_history(user_id, limit=50, offset=0):
    '''
    Purpose: Get transaction history for a user.
    Created by Vaughn Huey
    '''
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT t.id, t.from_user_id, t.to_user_id, t.amount, t.type, t.created_at,
                   u1.username as from_username, u2.username as to_username
            FROM transactions t
            LEFT JOIN users u1 ON t.from_user_id = u1.id
            LEFT JOIN users u2 ON t.to_user_id = u2.id
            WHERE t.from_user_id = %s OR t.to_user_id = %s
            ORDER BY t.created_at DESC
            LIMIT %s OFFSET %s
        """, (user_id, user_id, limit, offset))
        rows = cur.fetchall()
        return [{
            "id": r[0], "from_user_id": r[1], "to_user_id": r[2],
            "amount": float(r[3]), "type": r[4], "created_at": str(r[5]),
            "from_username": r[6], "to_username": r[7]
        } for r in rows]
    finally:
        cur.close()
        conn.close()