"""
CloudMart Authentication Utilities
Standalone script for testing user creation via SSH tunnel to RDS
"""

import bcrypt
from DataBase.postgres import get_connection

#adds admin role 
def setup_database():
    """Creates the users table with role support."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role VARCHAR(20) DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("Table 'users' is ready with role support.")
    except Exception as e:
        print(f"Error setting up table: {e}")


def create_account(email, username, plain_password, role='user'):
    """Hashes the password and saves the user to the database with a specific role."""
    password_hash = bcrypt.hashpw(
        plain_password.encode('utf-8'), 
        bcrypt.gensalt()
    ).decode('utf-8')

    try:
        conn = get_connection()
        cur = conn.cursor()
        
        cur.execute(
            "INSERT INTO users(email, username, password_hash, role) VALUES(%s, %s, %s, %s)",
            (email.lower(), username, password_hash, role)
        )
        
        conn.commit()
        cur.close()
        conn.close()
        print(f"User '{username}' ({role}) created successfully!")
        
    except Exception as e:
        print(f"Error creating account: {e}")


def verify_password(username, plain_password):
    """Verify a user's password."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        cur.execute(
            "SELECT password_hash FROM users WHERE LOWER(username) = LOWER(%s)",
            (username,)
        )
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        if not result:
            return False
            
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            result[0].encode('utf-8')
        )
        
    except Exception as e:
        print(f"Error verifying password: {e}")
        return False


if __name__ == "__main__":
    setup_database()
    
    print("\n--- Test Account Creation ---")
    email = input("Enter email (@my.hamptonu.edu): ")
    username = input("Enter username: ")
    password = input("Enter password: ")
    role_input = input("Enter role (user/admin) [default: user]: ") or "user"
    
    create_account(email, username, password, role_input)