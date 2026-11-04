"""
eCamp Database Configuration
Connects to AWS RDS PostgreSQL via SSH tunnel through EC2

Edited by vaughn huey 9/24/26

To query the database locally, tunnel through the EC2 bastion using the
values in your .env file:
        ssh -i "$SSH_KEY_PATH" -L 5434:"$RDS_HOST":5432 -N -f ec2-user@"$SSH_HOST"
        psql -h 127.0.0.1 -p 5434 -U "$DB_USER" -d "$DB_NAME"

To exit the psql session cleanly, type: exit
"""

import os
from sshtunnel import SSHTunnelForwarder
import psycopg
 
# Database & Tunnel Configuration
SSH_HOST = os.environ.get("SSH_HOST")
SSH_USER = os.environ.get("SSH_USER")
SSH_KEY_PATH = os.environ.get("SSH_KEY_PATH")
# RDS Configuration
RDS_HOST = os.environ.get("RDS_HOST")
RDS_PORT = 5432
DB_HOST = os.environ.get("DB_HOST")
DB_NAME = os.environ.get("DB_NAME")
DB_USER =os.environ.get("DB_USER")
DB_PASSWORD = os.environ.get("DB_PASSWORD")


# Global tunnel reference
_tunnel = None


def get_tunnel():
    """Get or create SSH tunnel to EC2."""
    global _tunnel
    if _tunnel is None or not _tunnel.is_active:
        _tunnel = SSHTunnelForwarder(
            (SSH_HOST, 22),
            ssh_username=SSH_USER,
            ssh_pkey=SSH_KEY_PATH,
            remote_bind_address=(RDS_HOST, RDS_PORT),
            local_bind_address=("127.0.0.1", 0)  # 0 = auto-assign available port
        )
        _tunnel.start()
        print(f"SSH tunnel established on local port {_tunnel.local_bind_port}")
    return _tunnel


def get_connection():
    """Get database connection through SSH tunnel."""
    tunnel = get_tunnel()
    return psycopg.connect(
        host="127.0.0.1",
        port=tunnel.local_bind_port,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        sslmode="require" 
    )


def test_connection():
    """Test database connectivity."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()[0]
        print(f"Connected to PostgreSQL: {version}")
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Connection failed: {e}")
        return False


if __name__ == "__main__":
    print("Testing database connection...")
    test_connection()
