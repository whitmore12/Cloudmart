'''
Name: Erick Constant
Purpose: To create a wallet feature.
'''

from app import get_db_connection

conn = get_db_connection()
cur = conn.cursor()

def get_balance(user_Id):
    '''
    Purpose: Return the balance of the user using SQL.
    '''
    current_balance = cur.execute("SELECT pirate_dollars FROM users where id = %i", (user_Id))
    return current_balance

def transfer_money(buyer_Id, seller_Id, cost):
    '''
    Purpose: Transfers the money from one user to another and updates it. Returns 0 for complete, returns 1 for incomplete
    '''
    if check_for_sufficent_funds(buyer_Id, cost) == True:
        buyer_current_money = get_balance(buyer_Id)
        seller_current_money = get_balance(seller_Id)
        buyer_updated_money = buyer_current_money - cost
        seller_updated_money = seller_current_money + cost
        update_money(buyer_Id, buyer_updated_money)
        update_money(seller_Id, seller_updated_money)
        return 0
    else:
        return 1



def check_for_sufficent_funds(user_Id, value):
    '''
    Purpose: Check if the user has sufficient funds to make a purchase. Returns True for sufficient and False for insufficient funds.
    '''
    current_balance = get_balance(user_Id)
    if current_balance < value:
        return True 
    else:
        return False

def update_money(user1, value):
    '''
    Purpose: Update the money of the user in the database.
    '''
    cur.execute("UPDATE pirate_dollars SET %i FROM users WHERE id = %i", (value, user1))