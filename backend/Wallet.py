'''
Name: Erick Constant
Purpose: To create a wallet feature.
'''


def get_balance(cur, user_Id):
    '''
    Purpose: Return the balance of the user, or None if the user does not exist.
    '''
    cur.execute("SELECT pirate_dollars FROM users WHERE id = %s", (user_Id,))
    row = cur.fetchone()
    if row is None:
        return None
    return float(row[0] or 0)

def check_for_sufficent_funds(cur, user_Id, value):
    '''
    Purpose: Check if the user has sufficient funds to make a purchase. Returns True for sufficient and False for insufficient funds.
    '''
    current_balance = get_balance(cur, user_Id)
    return current_balance is not None and current_balance >= value

def _set_balance(cur, user_Id, value):
    '''
    Purpose: Set the balance of the user without committing.
    '''
    cur.execute("UPDATE users SET pirate_dollars = %s WHERE id = %s", (value, user_Id))

def update_money(conn, cur, user_Id, value):
    '''
    Purpose: Update the money of the user in the database and commit.
    '''
    _set_balance(cur, user_Id, value)
    conn.commit()

def transfer_money(conn, buyer_Id, seller_Id, cost):
    '''
    Purpose: Transfers the money from one user to another in one transaction. Returns 0 for complete, returns 1 for incomplete.
    '''
    cur = conn.cursor()
    try:
        if not check_for_sufficent_funds(cur, buyer_Id, cost) or get_balance(cur, seller_Id) is None:
            conn.rollback()
            return 1
        buyer_updated_money = get_balance(cur, buyer_Id) - cost
        seller_updated_money = get_balance(cur, seller_Id) + cost
        _set_balance(cur, buyer_Id, buyer_updated_money)
        _set_balance(cur, seller_Id, seller_updated_money)
        conn.commit()
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
