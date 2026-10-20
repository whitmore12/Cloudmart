# Collaboration from Howard Ames, Nickodemus, and Gemini
from flask import Flask, request, jsonify
from flask_cors import CORS
from sshtunnel import SSHTunnelForwarder
import psycopg
import bcrypt
import os
import uuid
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# S3 config
from s3_config import s3, BUCKET_NAME, AWS_REGION

app = Flask(__name__)
CORS(app)

# Database & Tunnel Configuration
SSH_HOST = "18.190.235.250"
SSH_USER = "ec2-user"
SSH_KEY_PATH = os.path.join(os.path.dirname(__file__), "Resources", "ec2Test.pem")

RDS_HOST = "cloudmart3-4.cjy4c6csc3wv.us-east-2.rds.amazonaws.com"
RDS_PORT = 5432
DB_NAME = "cloudmartdb"
DB_USER = "postgres"
DB_PASSWORD = "password"

tunnel = None


def start_ssh_tunnel():
    global tunnel
    if tunnel is None or not getattr(tunnel, "is_active", False):
        tunnel = SSHTunnelForwarder(
            (SSH_HOST, 22),
            ssh_username=SSH_USER,
            ssh_pkey=SSH_KEY_PATH,
            remote_bind_address=(RDS_HOST, RDS_PORT),
            local_bind_address=("127.0.0.1", 0)
        )
        tunnel.start()
    return tunnel


def get_db_connection():
    tun = start_ssh_tunnel()
    return psycopg.connect(
        host="127.0.0.1",
        port=tun.local_bind_port,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        email VARCHAR(255) UNIQUE,
        username VARCHAR(50) UNIQUE,
        password_hash TEXT,
        role VARCHAR(20) DEFAULT 'user',
        profile_image TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS profile_image TEXT
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS listings (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES users(id),
        title VARCHAR(255),
        price NUMERIC,
        category VARCHAR(100),
        condition VARCHAR(100),
        image TEXT,
        seller VARCHAR(100),
        buyer_email VARCHAR(255),
        status VARCHAR(20) DEFAULT 'active'
    )
    """)

    cur.execute("""
    ALTER TABLE listings
    ADD COLUMN IF NOT EXISTS seller VARCHAR(100)
    """)
    cur.execute("""
    ALTER TABLE listings
    ADD COLUMN IF NOT EXISTS buyer_email VARCHAR(255)
    """)
    cur.execute("""
    ALTER TABLE listings
    ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active'
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS wishlist (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES users(id),
        listing_id INTEGER REFERENCES listings(id),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, listing_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS return_requests (
        id SERIAL PRIMARY KEY,
        listing_id INTEGER REFERENCES listings(id) ON DELETE CASCADE,
        seller_id INTEGER REFERENCES users(id),
        buyer_id INTEGER REFERENCES users(id),
        buyer_email VARCHAR(255) NOT NULL,
        reason TEXT NOT NULL,
        status VARCHAR(20) DEFAULT 'pending',
        seller_note TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        reviewed_at TIMESTAMP
    )
    """)

    cur.execute("""
    ALTER TABLE return_requests
    ADD COLUMN IF NOT EXISTS seller_note TEXT
    """)
    cur.execute("""
    ALTER TABLE return_requests
    ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP
    """)

    conn.commit()
    cur.close()
    conn.close()


# ========================
# AUTH
# ========================
@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json()
    password_hash = bcrypt.hashpw(data["password"].encode(), bcrypt.gensalt()).decode()
    role = data.get("role", "user")

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            "INSERT INTO users (email, username, password_hash, role) VALUES (%s, %s, %s, %s) RETURNING id",
            (data["email"], data["username"], password_hash, role)
        )
        user_id = cur.fetchone()[0]
        conn.commit()
        return jsonify({"user_id": user_id, "role": role}), 201
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        conn.close()


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json()

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, username, password_hash, email, role, profile_image FROM users WHERE username = %s",
        (data["username"],)
    )
    user = cur.fetchone()

    cur.close()
    conn.close()

    if not user or not bcrypt.checkpw(data["password"].encode(), user[2].encode()):
        return jsonify({"error": "Invalid credentials"}), 401

    return jsonify({
        "user": {
            "id": user[0],
            "username": user[1],
            "email": user[3],
            "role": user[4],
            "profile_image": user[5]
        }
    }), 200


# ========================
# S3 UPLOADS
# ========================
@app.route("/api/uploads/presign", methods=["POST", "OPTIONS"])
def generate_presigned_upload_url():
    if request.method == "OPTIONS":
        return jsonify({"ok": True}), 200

    data = request.get_json() or {}
    file_name = data.get("fileName")
    file_type = data.get("fileType")

    if not file_name or not file_type:
        return jsonify({"error": "fileName and fileType are required"}), 400

    try:
        ext = os.path.splitext(file_name)[1] or ""
        unique_name = f"listings/{uuid.uuid4()}{ext}"

        upload_url = s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": BUCKET_NAME,
                "Key": unique_name,
                "ContentType": file_type
            },
            ExpiresIn=300
        )

        image_url = f"https://{BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{unique_name}"

        return jsonify({
            "uploadUrl": upload_url,
            "imageUrl": image_url
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/uploads/profile-presign", methods=["POST", "OPTIONS"])
def generate_profile_presigned_upload_url():
    if request.method == "OPTIONS":
        return jsonify({"ok": True}), 200

    data = request.get_json() or {}
    file_name = data.get("fileName")
    file_type = data.get("fileType")

    if not file_name or not file_type:
        return jsonify({"error": "fileName and fileType are required"}), 400

    try:
        ext = os.path.splitext(file_name)[1] or ""
        unique_name = f"profiles/{uuid.uuid4()}{ext}"

        upload_url = s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": BUCKET_NAME,
                "Key": unique_name,
                "ContentType": file_type
            },
            ExpiresIn=300
        )

        image_url = f"https://{BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{unique_name}"

        return jsonify({
            "uploadUrl": upload_url,
            "imageUrl": image_url
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========================
# LISTINGS
# ========================
@app.route("/api/listings", methods=["POST"])
def create_listing():
    data = request.get_json()
    image = data.get("image") or "https://picsum.photos/300"

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("SELECT username FROM users WHERE id = %s", (data["user_id"],))
        seller_row = cur.fetchone()
        seller_name = seller_row[0] if seller_row else "Unknown"

        cur.execute("""
            INSERT INTO listings (user_id, title, price, category, condition, image, seller, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            data["user_id"],
            data["title"],
            data["price"],
            data["category"],
            data["condition"],
            image,
            seller_name,
            "active"
        ))

        new_listing_id = cur.fetchone()[0]
        conn.commit()

        return jsonify({"message": "Listing created", "id": new_listing_id}), 201
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        conn.close()


# Homepage only shows ACTIVE listings
@app.route("/api/listings", methods=["GET"])
def get_listings():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            l.id,
            l.user_id,
            l.title,
            l.price,
            l.category,
            l.condition,
            l.image,
            COALESCE(NULLIF(l.seller, ''), u.username) AS seller,
            COALESCE(l.status, 'active') AS status,
            l.buyer_email
        FROM listings l
        LEFT JOIN users u ON l.user_id = u.id
        WHERE COALESCE(l.status, 'active') = 'active'
        ORDER BY l.id DESC
    """)

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify([{
        "id": r[0],
        "user_id": r[1],
        "title": r[2],
        "price": float(r[3]) if r[3] is not None else 0,
        "category": r[4],
        "condition": r[5],
        "image": r[6],
        "seller": r[7],
        "status": r[8],
        "buyer_email": r[9]
    } for r in rows]), 200


@app.route("/api/listings/<int:listing_id>", methods=["GET"])
def get_listing_by_id(listing_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            l.id,
            l.user_id,
            l.title,
            l.price,
            l.category,
            l.condition,
            l.image,
            COALESCE(NULLIF(l.seller, ''), u.username) AS seller,
            COALESCE(l.status, 'active') AS status,
            l.buyer_email
        FROM listings l
        LEFT JOIN users u ON l.user_id = u.id
        WHERE l.id = %s
    """, (listing_id,))

    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return jsonify({"error": "Listing not found"}), 404

    return jsonify({
        "id": row[0],
        "user_id": row[1],
        "title": row[2],
        "price": float(row[3]) if row[3] is not None else 0,
        "category": row[4],
        "condition": row[5],
        "image": row[6],
        "seller": row[7],
        "status": row[8],
        "buyer_email": row[9]
    }), 200


@app.route("/api/listings/<int:listing_id>", methods=["PUT"])
def update_listing(listing_id):
    data = request.get_json()
    user_id = data.get("user_id")
    user_role = data.get("role")

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("SELECT user_id, COALESCE(status, 'active') FROM listings WHERE id = %s", (listing_id,))
        row = cur.fetchone()

        if not row:
            return jsonify({"error": "Listing not found"}), 404

        if user_role != "admin" and int(row[0]) != int(user_id):
            return jsonify({"error": "Forbidden"}), 403

        cur.execute("""
            UPDATE listings
            SET title = %s,
                price = %s,
                category = %s,
                condition = %s,
                image = %s
            WHERE id = %s
        """, (
            data["title"],
            data["price"],
            data["category"],
            data["condition"],
            data["image"],
            listing_id
        ))

        conn.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


# Mark listing as sold + store buyer email
@app.route("/api/listings/<int:listing_id>/mark-sold", methods=["PUT"])
def mark_listing_sold(listing_id):
    data = request.get_json()
    user_id = data.get("user_id")
    user_role = data.get("role")
    buyer_email = (data.get("buyer_email") or "").strip().lower()

    if not buyer_email:
        return jsonify({"error": "Buyer email is required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("SELECT user_id, COALESCE(status, 'active') FROM listings WHERE id = %s", (listing_id,))
        row = cur.fetchone()

        if not row:
            return jsonify({"error": "Listing not found"}), 404

        if user_role != "admin" and int(row[0]) != int(user_id):
            return jsonify({"error": "Forbidden"}), 403

        current_status = (row[1] or "active").lower()

        if current_status == "sold":
            return jsonify({"error": "Listing is already sold"}), 400

        if current_status == "deleted":
            return jsonify({"error": "Deleted listings cannot be marked as sold"}), 400

        cur.execute("SELECT id, email FROM users WHERE LOWER(email) = LOWER(%s)", (buyer_email,))
        buyer_row = cur.fetchone()

        if not buyer_row:
            return jsonify({"error": "Buyer email does not belong to a registered user"}), 400

        if int(buyer_row[0]) == int(user_id):
            return jsonify({"error": "You cannot mark your own listing as bought by yourself"}), 400

        cur.execute("""
            UPDATE listings
            SET status = 'sold',
                buyer_email = %s
            WHERE id = %s
        """, (buyer_row[1], listing_id))

        conn.commit()
        return jsonify({"success": True, "message": "Listing marked as sold"}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cur.close()
        conn.close()


# Move sold listing back to active, but not deleted listings
@app.route("/api/listings/<int:listing_id>/mark-active", methods=["PUT"])
def mark_listing_active(listing_id):
    data = request.get_json()
    user_id = data.get("user_id")
    user_role = data.get("role")

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("SELECT user_id, COALESCE(status, 'active') FROM listings WHERE id = %s", (listing_id,))
        row = cur.fetchone()

        if not row:
            return jsonify({"error": "Listing not found"}), 404

        if user_role != "admin" and int(row[0]) != int(user_id):
            return jsonify({"error": "Forbidden"}), 403

        current_status = (row[1] or "active").lower()

        if current_status == "deleted":
            return jsonify({"error": "Deleted listings cannot be moved directly back to active"}), 400

        cur.execute("""
            UPDATE listings
            SET status = 'active',
                buyer_email = NULL
            WHERE id = %s
        """, (listing_id,))

        conn.commit()
        return jsonify({"success": True, "message": "Listing moved back to active"}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cur.close()
        conn.close()


# SOFT DELETE
@app.route("/api/listings/<int:listing_id>", methods=["DELETE"])
def delete_listing(listing_id):
    data = request.get_json() or {}
    user_id = data.get("user_id")
    user_role = data.get("role")

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("SELECT user_id, COALESCE(status, 'active') FROM listings WHERE id = %s", (listing_id,))
        row = cur.fetchone()

        if not row:
            return jsonify({"error": "Listing not found"}), 404

        if user_role != "admin" and int(row[0]) != int(user_id):
            return jsonify({"error": "Forbidden"}), 403

        current_status = (row[1] or "active").lower()

        if current_status == "deleted":
            return jsonify({"success": True, "message": "Listing is already deleted"}), 200

        cur.execute("""
            UPDATE listings
            SET status = 'deleted',
                buyer_email = NULL
            WHERE id = %s
        """, (listing_id,))

        conn.commit()
        return jsonify({"success": True, "message": "Listing soft deleted"}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cur.close()
        conn.close()


# ========================
# USERS / PROFILE SUPPORT
# ========================
@app.route("/api/users/by-username/<username>", methods=["GET"])
def get_user_by_username(username):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, email, username, role, profile_image, created_at
        FROM users
        WHERE LOWER(username) = LOWER(%s)
    """, (username,))
    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:
        return jsonify({"error": "User not found"}), 404

    return jsonify({
        "id": row[0],
        "email": row[1],
        "username": row[2],
        "role": row[3],
        "profile_image": row[4],
        "created_at": str(row[5])
    }), 200


@app.route("/api/users/<int:user_id>/profile", methods=["PUT"])
def update_user_profile(user_id):
    data = request.get_json() or {}
    requester_id = data.get("user_id")
    requester_role = data.get("role")
    new_username = (data.get("username") or "").strip()
    profile_image = (data.get("profile_image") or "").strip()

    if requester_role != "admin" and int(requester_id) != int(user_id):
        return jsonify({"error": "Forbidden"}), 403

    if not new_username:
        return jsonify({"error": "Username is required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("SELECT id, username FROM users WHERE id = %s", (user_id,))
        existing_user = cur.fetchone()

        if not existing_user:
            return jsonify({"error": "User not found"}), 404

        cur.execute("""
            SELECT id
            FROM users
            WHERE LOWER(username) = LOWER(%s)
              AND id <> %s
        """, (new_username, user_id))
        username_taken = cur.fetchone()

        if username_taken:
            return jsonify({"error": "Username is already taken"}), 400

        cur.execute("""
            UPDATE users
            SET username = %s,
                profile_image = %s
            WHERE id = %s
        """, (new_username, profile_image or None, user_id))

        cur.execute("""
            UPDATE listings
            SET seller = %s
            WHERE user_id = %s
        """, (new_username, user_id))

        conn.commit()

        return jsonify({
            "success": True,
            "user": {
                "id": user_id,
                "username": new_username,
                "profile_image": profile_image or None
            }
        }), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cur.close()
        conn.close()


# Seller page shows active, sold, and deleted
@app.route("/api/listings/by-seller/<username>", methods=["GET"])
def get_listings_by_seller(username):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            l.id,
            l.user_id,
            l.title,
            l.price,
            l.category,
            l.condition,
            l.image,
            COALESCE(NULLIF(l.seller, ''), u.username) AS seller,
            COALESCE(l.status, 'active') AS status,
            l.buyer_email
        FROM listings l
        LEFT JOIN users u ON l.user_id = u.id
        WHERE LOWER(COALESCE(NULLIF(l.seller, ''), u.username)) = LOWER(%s)
        ORDER BY l.id DESC
    """, (username,))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify([{
        "id": r[0],
        "user_id": r[1],
        "title": r[2],
        "price": float(r[3]) if r[3] is not None else 0,
        "category": r[4],
        "condition": r[5],
        "image": r[6],
        "seller": r[7],
        "status": r[8],
        "buyer_email": r[9]
    } for r in rows]), 200


# Bought items for the logged-in buyer
@app.route("/api/listings/bought/<path:buyer_email>", methods=["GET"])
def get_bought_items(buyer_email):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            l.id,
            l.user_id,
            l.title,
            l.price,
            l.category,
            l.condition,
            l.image,
            COALESCE(NULLIF(l.seller, ''), u.username) AS seller,
            COALESCE(l.status, 'active') AS status,
            l.buyer_email,
            rr.id AS return_request_id,
            rr.reason AS return_reason,
            rr.status AS return_status,
            rr.seller_note,
            rr.created_at AS return_created_at,
            rr.reviewed_at AS return_reviewed_at
        FROM listings l
        LEFT JOIN users u ON l.user_id = u.id
        LEFT JOIN LATERAL (
            SELECT
                id,
                reason,
                status,
                seller_note,
                created_at,
                reviewed_at
            FROM return_requests
            WHERE listing_id = l.id
              AND LOWER(buyer_email) = LOWER(%s)
            ORDER BY created_at DESC
            LIMIT 1
        ) rr ON TRUE
        WHERE LOWER(COALESCE(l.buyer_email, '')) = LOWER(%s)
          AND COALESCE(l.status, 'active') = 'sold'
        ORDER BY l.id DESC
    """, (buyer_email, buyer_email))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify([{
        "id": r[0],
        "user_id": r[1],
        "title": r[2],
        "price": float(r[3]) if r[3] is not None else 0,
        "category": r[4],
        "condition": r[5],
        "image": r[6],
        "seller": r[7],
        "status": r[8],
        "buyer_email": r[9],
        "return_request_id": r[10],
        "return_reason": r[11],
        "return_status": r[12],
        "seller_note": r[13],
        "return_created_at": str(r[14]) if r[14] else None,
        "return_reviewed_at": str(r[15]) if r[15] else None
    } for r in rows]), 200


# ========================
# RETURNS
# ========================
@app.route("/api/returns/request", methods=["POST"])
def create_return_request():
    data = request.get_json() or {}
    listing_id = data.get("listing_id")
    buyer_id = data.get("buyer_id")
    buyer_email = (data.get("buyer_email") or "").strip().lower()
    reason = (data.get("reason") or "").strip()

    if not listing_id or not buyer_id or not buyer_email or not reason:
        return jsonify({"error": "listing_id, buyer_id, buyer_email, and reason are required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT id, email
            FROM users
            WHERE id = %s
        """, (buyer_id,))
        buyer_row = cur.fetchone()

        if not buyer_row:
            return jsonify({"error": "Buyer not found"}), 404

        if (buyer_row[1] or "").strip().lower() != buyer_email:
            return jsonify({"error": "Buyer email does not match the logged-in user"}), 403

        cur.execute("""
            SELECT id, user_id, buyer_email, COALESCE(status, 'active')
            FROM listings
            WHERE id = %s
        """, (listing_id,))
        listing_row = cur.fetchone()

        if not listing_row:
            return jsonify({"error": "Listing not found"}), 404

        listing_owner_id = listing_row[1]
        listing_buyer_email = (listing_row[2] or "").strip().lower()
        listing_status = (listing_row[3] or "active").strip().lower()

        if listing_status != "sold":
            return jsonify({"error": "Only sold items can be returned"}), 400

        if listing_buyer_email != buyer_email:
            return jsonify({"error": "Only the buyer of this item can request a return"}), 403

        cur.execute("""
            SELECT id
            FROM return_requests
            WHERE listing_id = %s
              AND buyer_id = %s
              AND status = 'pending'
        """, (listing_id, buyer_id))
        existing_pending = cur.fetchone()

        if existing_pending:
            return jsonify({"error": "A return request for this item is already pending"}), 400

        cur.execute("""
            INSERT INTO return_requests (listing_id, seller_id, buyer_id, buyer_email, reason, status)
            VALUES (%s, %s, %s, %s, %s, 'pending')
            RETURNING id
        """, (listing_id, listing_owner_id, buyer_id, buyer_row[1], reason))

        new_return_id = cur.fetchone()[0]
        conn.commit()

        return jsonify({
            "success": True,
            "message": "Return request submitted",
            "return_request_id": new_return_id
        }), 201

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cur.close()
        conn.close()


@app.route("/api/returns/seller/<int:seller_id>", methods=["GET"])
def get_return_requests_for_seller(seller_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            rr.id,
            rr.listing_id,
            l.title,
            l.price,
            l.category,
            l.condition,
            l.image,
            COALESCE(NULLIF(l.seller, ''), u.username) AS seller,
            rr.buyer_email,
            rr.reason,
            rr.status,
            rr.seller_note,
            rr.created_at,
            rr.reviewed_at
        FROM return_requests rr
        JOIN listings l ON rr.listing_id = l.id
        LEFT JOIN users u ON l.user_id = u.id
        WHERE rr.seller_id = %s
        ORDER BY
            CASE WHEN rr.status = 'pending' THEN 0 ELSE 1 END,
            rr.created_at DESC
    """, (seller_id,))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify([{
        "id": r[0],
        "listing_id": r[1],
        "title": r[2],
        "price": float(r[3]) if r[3] is not None else 0,
        "category": r[4],
        "condition": r[5],
        "image": r[6],
        "seller": r[7],
        "buyer_email": r[8],
        "reason": r[9],
        "status": r[10],
        "seller_note": r[11],
        "created_at": str(r[12]) if r[12] else None,
        "reviewed_at": str(r[13]) if r[13] else None
    } for r in rows]), 200


@app.route("/api/returns/<int:return_id>/review", methods=["PUT"])
def review_return_request(return_id):
    data = request.get_json() or {}
    seller_id = data.get("seller_id")
    user_role = data.get("role")
    action = (data.get("action") or "").strip().lower()
    seller_note = (data.get("seller_note") or "").strip()

    if action not in ["approve", "deny"]:
        return jsonify({"error": "Action must be approve or deny"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT id, listing_id, seller_id, status
            FROM return_requests
            WHERE id = %s
        """, (return_id,))
        return_row = cur.fetchone()

        if not return_row:
            return jsonify({"error": "Return request not found"}), 404

        listing_id = return_row[1]
        request_seller_id = return_row[2]
        request_status = (return_row[3] or "").lower()

        if request_status != "pending":
            return jsonify({"error": "This return request has already been reviewed"}), 400

        if user_role != "admin" and int(request_seller_id) != int(seller_id):
            return jsonify({"error": "Forbidden"}), 403

        new_status = "approved" if action == "approve" else "denied"

        cur.execute("""
            UPDATE return_requests
            SET status = %s,
                seller_note = %s,
                reviewed_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (new_status, seller_note if seller_note else None, return_id))

        if action == "approve":
            cur.execute("""
                UPDATE listings
                SET status = 'active',
                    buyer_email = NULL
                WHERE id = %s
            """, (listing_id,))

        conn.commit()

        return jsonify({
            "success": True,
            "message": f"Return request {new_status}"
        }), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cur.close()
        conn.close()


# ========================
# WISHLIST
# ========================
@app.route("/api/wishlist", methods=["GET"])
def get_wishlist():
    user_id = request.args.get("user_id")

    if not user_id:
        return jsonify([]), 200

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT l.id, l.user_id, l.title, l.price, l.category, l.condition, l.image,
               COALESCE(NULLIF(l.seller, ''), u.username) AS seller,
               COALESCE(l.status, 'active') AS status,
               l.buyer_email
        FROM wishlist w
        JOIN listings l ON w.listing_id = l.id
        LEFT JOIN users u ON l.user_id = u.id
        WHERE w.user_id = %s
          AND COALESCE(l.status, 'active') = 'active'
        ORDER BY w.id DESC
    """, (user_id,))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify([{
        "id": r[0],
        "user_id": r[1],
        "title": r[2],
        "price": float(r[3]) if r[3] is not None else 0,
        "category": r[4],
        "condition": r[5],
        "image": r[6],
        "seller": r[7],
        "status": r[8],
        "buyer_email": r[9]
    } for r in rows]), 200


@app.route("/api/wishlist", methods=["POST"])
def add_to_wishlist():
    data = request.get_json()
    user_id = data.get("user_id")
    listing_id = data.get("listing_id")

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO wishlist (user_id, listing_id)
            SELECT %s, %s
            WHERE EXISTS (
                SELECT 1
                FROM listings
                WHERE id = %s
                  AND COALESCE(status, 'active') = 'active'
            )
        """, (user_id, listing_id, listing_id))

        if cur.rowcount == 0:
            conn.rollback()
            return jsonify({"error": "Only active listings can be added to wishlist"}), 400

        conn.commit()
        return jsonify({"success": True}), 201
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        conn.close()


@app.route("/api/wishlist/<int:listing_id>", methods=["DELETE"])
def remove_from_wishlist(listing_id):
    user_id = request.args.get("user_id")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM wishlist
        WHERE user_id = %s AND listing_id = %s
    """, (user_id, listing_id))
    conn.commit()

    cur.close()
    conn.close()

    return jsonify({"success": True}), 200


# ========================
# ADMIN
# ========================
@app.route("/api/admin/dashboard", methods=["GET"])
def get_admin_dashboard():
    role = request.args.get("role")

    if role != "admin":
        return jsonify({"error": "Forbidden"}), 403

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("SELECT COUNT(*) FROM users")
        total_users = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM listings")
        total_listings = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM listings WHERE COALESCE(status, 'active') = 'sold'")
        total_sold = cur.fetchone()[0]

        cur.execute("SELECT COALESCE(SUM(price), 0) FROM listings")
        total_value = cur.fetchone()[0]

        cur.execute("""
            SELECT id, email, username, role, created_at
            FROM users
            ORDER BY id ASC
        """)
        user_rows = cur.fetchall()

        cur.execute("""
            SELECT
                id,
                user_id,
                title,
                price,
                category,
                condition,
                seller,
                status,
                buyer_email
            FROM listings
            ORDER BY id DESC
        """)
        listing_rows = cur.fetchall()

        return jsonify({
            "summary": {
                "total_users": total_users,
                "total_listings": total_listings,
                "total_sold": total_sold,
                "total_value": float(total_value) if total_value is not None else 0
            },
            "users": [
                {
                    "id": r[0],
                    "email": r[1],
                    "username": r[2],
                    "role": r[3],
                    "created_at": str(r[4])
                }
                for r in user_rows
            ],
            "listings": [
                {
                    "id": r[0],
                    "user_id": r[1],
                    "title": r[2],
                    "price": float(r[3]) if r[3] is not None else 0,
                    "category": r[4],
                    "condition": r[5],
                    "seller": r[6],
                    "status": r[7],
                    "buyer_email": r[8]
                }
                for r in listing_rows
            ]
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    init_db()
    app.run(port=5001, debug=True)