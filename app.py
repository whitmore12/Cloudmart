from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from sshtunnel import SSHTunnelForwarder
import psycopg
import bcrypt
import secrets
import hashlib
from datetime import datetime, timedelta
from email_config import send_reset_email, APP_BASE_URL
import os
import uuid
import subprocess
import hmac
import re
import time
from dotenv import load_dotenv

                     
"""
Edited by Vaughn Huey 9/24/26
"""

# Load environment variables from .env
load_dotenv()

# S3 config
from s3_config import s3, BUCKET_NAME, AWS_REGION
from account_requests import initAccountRequests

app = Flask(__name__)
# Explicit WSGI alias for Vercel's Python entrypoint detector.
handler = app
CORS(app)


@app.get("/")
def homepage():
    return send_from_directory("Frontend", "index.html")


@app.get("/Resources/<path:filename>")
def resource_file(filename):
    return send_from_directory("Resources", filename)


@app.get("/<path:filename>")
def frontend_file(filename):
    return send_from_directory("Frontend", filename)

# Database & Tunnel Configuration
SSH_HOST = os.getenv("SSH_HOST")
SSH_USER = os.getenv("SSH_USER")
SSH_KEY_PATH = os.getenv("SSH_KEY_PATH")
# RDS Configuration
RDS_HOST = os.getenv("RDS_HOST")
RDS_PORT = 5432
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER =os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

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

def log_action(who, action, target):
    """Logs an action to the action_logs database table."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO action_logs (who, action, target)
            VALUES (%s, %s, %s)
        """, (str(who), str(action), str(target)))
        conn.commit()
    except Exception as e:
        conn.rollback()
        app.logger.error(f"Failed to record action log: {e}")
    finally:
        cur.close()
        conn.close()

# Account deletion requests (Makaila)
def remove_profile_image(image_url):
    prefix = "/api/profile-images/"
    if image_url and image_url.startswith(prefix + "profiles/"):
        s3.delete_object(Bucket=BUCKET_NAME, Key=image_url[len(prefix):])


# the lambda looks get_db_connection up each time so tests can swap it
initAccountRequests(app, lambda: get_db_connection(), remove_profile_image, log_action)


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
    CREATE TABLE IF NOT EXISTS password_resets (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token_hash TEXT NOT NULL UNIQUE,
        expires_at TIMESTAMP NOT NULL,
        used BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS profile_image TEXT
    """)

    cur.execute("""
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS pirate_dollars NUMERIC DEFAULT 100.00
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
    ALTER TABLE listings
    ADD COLUMN IF NOT EXISTS size VARCHAR(20)
    """)
    cur.execute("""
    ALTER TABLE listings
    ADD COLUMN IF NOT EXISTS fit VARCHAR(20)
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
    CREATE TABLE IF NOT EXISTS transactions (
        id SERIAL PRIMARY KEY,
        from_user_id INTEGER REFERENCES users(id),
        to_user_id INTEGER REFERENCES users(id),
        amount NUMERIC,
        type VARCHAR(20),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS action_logs 
    (
       id SERIAL PRIMARY KEY,
       who VARCHAR(255) NOT NULL,
       action VARCHAR(100) NOT NULL,
       target VARCHAR(255) NOT NULL,
       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
   )
       """)

    # In-app messaging: one row per message
    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id SERIAL PRIMARY KEY,
        sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        receiver_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
        body TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_read BOOLEAN NOT NULL DEFAULT FALSE
    )
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_messages_chat
    ON messages (listing_id, sender_id, receiver_id, created_at)
    """)

    conn.commit()
    cur.close()
    conn.close()


# ========================
# AUTH
# ========================
@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not email or not username or not password:
        return jsonify({"error": "Email, username, and password are required."}), 400
    if not email.endswith("@my.hamptonu.edu"):
        return jsonify({"error": "Use a Hampton email address."}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400
    if len(username) > 50 or len(password.encode("utf-8")) > 72:
        return jsonify({"error": "Username or password is too long."}), 400

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    role = "user"

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            "INSERT INTO users (email, username, password_hash, role) VALUES (%s, %s, %s, %s) RETURNING id",
            (email, username, password_hash, role)
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


@app.get("/api/auth/admin-setup-status")
def admin_setup_status():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT EXISTS (SELECT 1 FROM users WHERE LOWER(role) = 'admin')")
        admins_exist = cur.fetchone()[0]
        return jsonify({"bootstrapAvailable": not admins_exist}), 200
    finally:
        cur.close()
        conn.close()


@app.post("/api/auth/create-admin")
def create_admin():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not email or not email.endswith("@my.hamptonu.edu"):
        return jsonify({"error": "Use a Hampton email address."}), 400
    if not username or len(username) > 50 or not re.fullmatch(r"[A-Za-z0-9_.-]+", username):
        return jsonify({"error": "Enter a valid username (letters, numbers, periods, underscores, or hyphens)."}), 400
    if len(password) < 8 or len(password.encode("utf-8")) > 72:
        return jsonify({"error": "Password must be at least 8 characters and no more than 72 bytes."}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Serialize setup requests so two concurrent requests cannot both bootstrap.
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (781204926,))
        cur.execute("SELECT EXISTS (SELECT 1 FROM users WHERE LOWER(role) = 'admin')")
        admins_exist = cur.fetchone()[0]

        if not admins_exist:
            expected_token = os.getenv("ADMIN_BOOTSTRAP_TOKEN", "")
            supplied_token = data.get("bootstrapToken", "")
            if not expected_token:
                return jsonify({"error": "Admin setup is not configured on the server."}), 503
            if not isinstance(supplied_token, str) or not hmac.compare_digest(supplied_token, expected_token):
                return jsonify({"error": "Invalid admin setup code."}), 403
        else:
            creator_username = (data.get("creatorUsername") or "").strip()
            creator_password = data.get("creatorPassword") or ""
            cur.execute(
                "SELECT password_hash FROM users WHERE LOWER(username) = LOWER(%s) AND LOWER(role) = 'admin'",
                (creator_username,),
            )
            creator = cur.fetchone()
            if not creator or not bcrypt.checkpw(creator_password.encode(), creator[0].encode()):
                return jsonify({"error": "Verify with an existing admin account."}), 403

        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        cur.execute(
            "INSERT INTO users (email, username, password_hash, role) VALUES (%s, %s, %s, 'admin') RETURNING id",
            (email, username, password_hash),
        )
        user_id = cur.fetchone()[0]
        conn.commit()
        return jsonify({"user_id": user_id, "username": username, "email": email, "role": "admin"}), 201
    except Exception as e:
        conn.rollback()
        if getattr(e, "sqlstate", None) == "23505":
            return jsonify({"error": "That email or username is already in use."}), 409
        app.logger.exception("Admin account creation failed")
        return jsonify({"error": "Could not create the admin account."}), 500
    finally:
        cur.close()
        conn.close()


# Simple brute-force protection: after MAX_LOGIN_ATTEMPTS failed logins,
# an account is locked out, with the lockout getting longer each time:
# 1 min, then 5, 10, 15 (capped at 15). Resets on server restart.
_login_attempts = {}
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATIONS = [60, 300, 600, 900]  # 1m, 5m, 10m, 15m


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username") or ""

    # cheap reject before the slow bcrypt check
    now = time.time()
    entry = _login_attempts.get(username)
    if entry and now < entry.get("locked_until", 0):
        return jsonify({"error": "Too many login attempts. Try again later."}), 429

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
        entry = _login_attempts.get(username, {"fails": 0, "locked_until": 0, "lockouts": 0})
        entry["fails"] += 1
        if entry["fails"] >= MAX_LOGIN_ATTEMPTS:
            duration = LOCKOUT_DURATIONS[min(entry.get("lockouts", 0), len(LOCKOUT_DURATIONS) - 1)]
            entry["locked_until"] = now + duration
            entry["fails"] = 0
            entry["lockouts"] = entry.get("lockouts", 0) + 1
        _login_attempts[username] = entry
        return jsonify({"error": "Invalid credentials"}), 401

    _login_attempts.pop(username, None)
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
# S3 UPLOADS - Nick
# ========================


@app.route("/api/auth/forgot-password", methods=["POST"])
def forgot_password():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    generic = {"message": "If that email is registered, a reset link has been sent."}

    if not email:
        return jsonify(generic), 200

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM users WHERE LOWER(email) = %s", (email,))
        row = cur.fetchone()
        if row:
            user_id = row[0]
            token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            expires_at = datetime.utcnow() + timedelta(minutes=30)
            cur.execute(
                "INSERT INTO password_resets (user_id, token_hash, expires_at) "
                "VALUES (%s, %s, %s)",
                (user_id, token_hash, expires_at),
            )
            conn.commit()
            link = f"{APP_BASE_URL}/reset-password.html?token={token}"
            try:
                send_reset_email(email, link)
            except Exception as e:
                app.logger.error(f"Email send failed: {e}")
    finally:
        cur.close()
        conn.close()

    return jsonify(generic), 200


@app.route("/api/auth/reset-password", methods=["POST"])
def reset_password():
    data = request.get_json() or {}
    token = data.get("token") or ""
    new_password = data.get("password") or ""

    if not token or len(new_password) < 8:
        return jsonify({"error": "Invalid request"}), 400

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, user_id, expires_at, used FROM password_resets "
            "WHERE token_hash = %s FOR UPDATE",
            (token_hash,),
        )
        row = cur.fetchone()
        if not row or row[3] or row[2] < datetime.utcnow():
            return jsonify({"error": "Link is invalid or expired"}), 400

        reset_id, user_id = row[0], row[1]
        password_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, user_id))
        cur.execute("UPDATE password_resets SET used = TRUE WHERE id = %s", (reset_id,))
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return jsonify({"message": "Password updated"}), 200

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

#Nickodemus
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


@app.post("/api/uploads/profile")
def upload_profile_image():
    image = request.files.get("file")
    if not image or not image.filename:
        return jsonify({"error": "Choose a profile image to upload."}), 400

    content_type = image.mimetype or "application/octet-stream"
    if not content_type.startswith("image/"):
        return jsonify({"error": "The selected file must be an image."}), 400

    try:
        ext = os.path.splitext(image.filename)[1].lower()
        if ext not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            return jsonify({"error": "Use a PNG, JPG, GIF, or WebP image."}), 400

        key = f"profiles/{uuid.uuid4()}{ext}"
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=image.stream,
            ContentType=content_type,
        )
        return jsonify({"imageUrl": f"/api/profile-images/{key}"}), 200
    except Exception as e:
        app.logger.exception("Profile image upload failed")
        return jsonify({"error": "Could not upload profile image to S3."}), 500


@app.get("/api/profile-images/<path:key>")
def serve_profile_image(key):
    if not key.startswith("profiles/"):
        return jsonify({"error": "Image not found."}), 404

    try:
        obj = s3.get_object(Bucket=BUCKET_NAME, Key=key)
        return Response(
            obj["Body"].read(),
            mimetype=obj.get("ContentType", "application/octet-stream"),
            headers={"Cache-Control": "public, max-age=3600"},
        )
    except Exception:
        return jsonify({"error": "Image not found."}), 404


@app.post("/api/uploads/listing")
def upload_listing_image():
    image = request.files.get("file")
    if not image or not image.filename:
        return jsonify({"error": "Choose a listing image to upload."}), 400

    content_type = image.mimetype or "application/octet-stream"
    ext = os.path.splitext(image.filename)[1].lower()
    if not content_type.startswith("image/") or ext not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        return jsonify({"error": "Use a PNG, JPG, GIF, or WebP image."}), 400

    key = f"listings/{uuid.uuid4()}{ext}"
    try:
        s3.put_object(Bucket=BUCKET_NAME, Key=key, Body=image.stream, ContentType=content_type)
        return jsonify({"imageUrl": f"/api/listing-images/{key}"}), 200
    except Exception:
        app.logger.exception("Listing image upload failed")
        return jsonify({"error": "Could not upload listing image."}), 500


@app.get("/api/listing-images/<path:key>")
def serve_listing_image(key):
    if not key.startswith("listings/"):
        return jsonify({"error": "Image not found."}), 404

    try:
        obj = s3.get_object(Bucket=BUCKET_NAME, Key=key)
        return Response(
            obj["Body"].read(),
            mimetype=obj.get("ContentType", "application/octet-stream"),
            headers={"Cache-Control": "public, max-age=3600"},
        )
    except Exception:
        return jsonify({"error": "Image not found."}), 404


# ========================
# LISTINGS
# ========================

# Edited by Makaila Williams 11/12/26
# Purpose: make sure the category, condition, size and fit are real choices
# the dropdowns on the sell page can be changed in the browser, so the server checks them too
ALLOWED_CATEGORIES = [
    "Clothing", "Shoes", "Bags & Accessories", "Electronics", "Books",
    "Furniture", "Appliances", "Dorm & Home", "Beauty", "Other",
]
ALLOWED_CONDITIONS = ["New", "Used"]
ALLOWED_FITS = ["Women's", "Men's", "Unisex"]
SIZES_BY_CATEGORY = {
    "Clothing": ["XS", "S", "M", "L", "XL", "XXL"],
    "Shoes": ["US " + str(n) for n in range(1, 16)],
}


def check_listing_fields(data):
    # gives back an error message, or None if it is all good
    category = data.get("category")
    if category not in ALLOWED_CATEGORIES:
        return "Please pick a valid category."
    if data.get("condition") not in ALLOWED_CONDITIONS:
        return "Please pick a valid condition."

    # only clothing and shoes need a size and fit
    if category in SIZES_BY_CATEGORY:
        if data.get("fit") not in ALLOWED_FITS:
            return "Please pick a fit."
        if data.get("size") not in SIZES_BY_CATEGORY[category]:
            return "Please pick a valid size."
    return None


def size_and_fit(data):
    # every other category gets no size or fit saved
    if data.get("category") in SIZES_BY_CATEGORY:
        return data.get("size"), data.get("fit")
    return None, None


@app.route("/api/listings", methods=["POST"])
def create_listing():
    data = request.get_json() or {}
    image = (data.get("image") or "").strip()

    if not image or image == "https://picsum.photos/300":
        return jsonify({"error": "A picture is required to post a listing."}), 400

    field_error = check_listing_fields(data)
    if field_error:
        return jsonify({"error": field_error}), 400
    size, fit = size_and_fit(data)

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("SELECT username FROM users WHERE id = %s", (data["user_id"],))
        seller_row = cur.fetchone()
        if not seller_row:
            conn.rollback()
            return jsonify({"error": "Your saved sign-in is no longer active. Sign out and sign in again."}), 401
        seller_name = seller_row[0]

        cur.execute("""
            INSERT INTO listings (user_id, title, price, category, condition, image, seller, status, size, fit)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            data["user_id"],
            data["title"],
            data["price"],
            data["category"],
            data["condition"],
            image,
            seller_name,
            "active",
            size,
            fit
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

#Tyson
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
            l.buyer_email,
            l.size,
            l.fit
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
    "buyer_email": r[9],
    "size": r[10],
    "fit": r[11]
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
            l.buyer_email,
            l.size,
            l.fit
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
    "buyer_email": row[9],
    "size": row[10],
    "fit": row[11]
    }), 200


@app.route("/api/listings/<int:listing_id>", methods=["PUT"])
def update_listing(listing_id):
    data = request.get_json()
    user_id = data.get("user_id")
    user_role = data.get("role")

    field_error = check_listing_fields(data)
    if field_error:
        return jsonify({"error": field_error}), 400
    size, fit = size_and_fit(data)

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
                image = %s,
                size = %s,
                fit = %s
            WHERE id = %s
        """, (
            data["title"],
            data["price"],
            data["category"],
            data["condition"],
            data["image"],
            size,
            fit,
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
#Tyson

# Edited By Taj Brown
@app.route("/api/listings/<int:listing_id>/mark-sold", methods=["PUT"])
def mark_listing_sold(listing_id):
    data = request.get_json()
    user_id = data.get("user_id")
    user_role = data.get("role")
    buyer_email = (data.get("buyer_email") or "").strip().lower()
  
    password = data.get("password") or ""

    if not buyer_email:
        return jsonify({"error": "Buyer email is required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,))
        auth_row = cur.fetchone()
        if not auth_row or not auth_row[0] or not bcrypt.checkpw(password.encode(), auth_row[0].encode()):
            conn.rollback()
            return jsonify({"error": "Incorrect password. Purchase verification failed."}), 401
      
      cur.execute("SELECT user_id, price, COALESCE(status, 'active') FROM listings WHERE id = %s FOR UPDATE", (listing_id,))
        row = cur.fetchone()

        if not row:
            return jsonify({"error": "Listing not found"}), 404

        seller_id, price, current_status = row[0], float(row[1] or 0), (row[2] or "active").lower()

        if current_status == "sold":
            return jsonify({"error": "Listing is already sold"}), 400

        if current_status == "deleted":
            return jsonify({"error": "Deleted listings cannot be marked as sold"}), 400

        cur.execute("SELECT id, email FROM users WHERE LOWER(email) = LOWER(%s)", (buyer_email,))
        buyer_row = cur.fetchone()

        if not buyer_row:
            return jsonify({"error": "Buyer email does not belong to a registered user"}), 400

        buyer_id = buyer_row[0]

        if int(buyer_id) == int(seller_id):
            return jsonify({"error": "You cannot buy your own listing."}), 400
        
        if user_role != "admin" and int(user_id) not in (int(seller_id), int(buyer_id)):
            return jsonify({"error": "Not authorized"}), 403

        # Check buyer has sufficient funds
        cur.execute("SELECT pirate_dollars FROM users WHERE id = %s FOR UPDATE", (buyer_id,))
        buyer_balance_row = cur.fetchone()
        if not buyer_balance_row or float(buyer_balance_row[0]) < price:
            conn.rollback()
            return jsonify({"error": "Insufficient funds"}), 400

        # Lock seller row
        cur.execute("SELECT pirate_dollars FROM users WHERE id = %s FOR UPDATE", (seller_id,))
        seller_balance_row = cur.fetchone()
        if not seller_balance_row:
            conn.rollback()
            return jsonify({"error": "Seller not found"}), 404

        # Transfer funds
        new_buyer_balance = float(buyer_balance_row[0]) - price
        new_seller_balance = float(seller_balance_row[0]) + price

        cur.execute("UPDATE users SET pirate_dollars = %s WHERE id = %s", (new_buyer_balance, buyer_id))
        cur.execute("UPDATE users SET pirate_dollars = %s WHERE id = %s", (new_seller_balance, seller_id))

        # Record transactions
        cur.execute("""
            INSERT INTO transactions (from_user_id, to_user_id, amount, type)
            VALUES (%s, %s, %s, 'purchase')
        """, (buyer_id, seller_id, price))
        cur.execute("""
            INSERT INTO transactions (from_user_id, to_user_id, amount, type)
            VALUES (%s, %s, %s, 'sale')
        """, (buyer_id, seller_id, price))

        # Mark listing as sold
        cur.execute("""
            UPDATE listings
            SET status = 'sold',
                buyer_email = %s
            WHERE id = %s
              AND COALESCE(status, 'active') = 'active'
        """, (buyer_row[1], listing_id))

        if cur.rowcount != 1:
            conn.rollback()
            return jsonify({"error": "Listing is no longer available"}), 409

        conn.commit()
        return jsonify({"success": True, "message": "Listing marked as sold"}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cur.close()
        conn.close()


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

#Ayinde
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

        actor = f"Admin (ID: {user_id})" if user_role == "admin" else f"User {user_id}"
        log_action(actor, "DELETE_LISTING", f"Listing #{listing_id}")
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
        SELECT id, username, role, profile_image, created_at
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
        "username": row[1],
        "role": row[2],
        "profile_image": row[3],
        "created_at": str(row[4])
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

#Nickodemus
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


@app.route("/api/returns/buyer/<path:buyer_email>", methods=["GET"])
def get_return_requests_for_buyer(buyer_email):
    """Get all return requests made by a buyer (for return history)"""
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
        WHERE LOWER(rr.buyer_email) = LOWER(%s)
        ORDER BY rr.created_at DESC
    """, (buyer_email,))

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

#Nickodemus
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
        return jsonify({"error": "Action must be approve or deny"}), 4 00

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
      
        actor = f"Admin (ID: {user_id})" if user_role == "admin" else f"User {user_id}"
        log_action(actor, "DELETE_LISTING", f"Listing #{listing_id}")

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
# MESSAGES (in-app messaging, no live chat)
# ========================
MAX_MESSAGE_LENGTH = 2000


# 1) Send a message about an item
@app.route("/api/messages", methods=["POST"])
def send_message():
    data = request.get_json() or {}
    sender_id = data.get("sender_id")
    receiver_id = data.get("receiver_id")
    listing_id = data.get("listing_id")
    body = (data.get("body") or "").strip()

    if not sender_id or not receiver_id or not listing_id or not body:
        return jsonify({"error": "sender_id, receiver_id, listing_id, and body are required"}), 400

    try:
        sender_id = int(sender_id)
        receiver_id = int(receiver_id)
        listing_id = int(listing_id)
    except (TypeError, ValueError):
        return jsonify({"error": "sender_id, receiver_id, and listing_id must be numbers"}), 400

    if sender_id == receiver_id:
        return jsonify({"error": "You cannot message yourself"}), 400

    if len(body) > MAX_MESSAGE_LENGTH:
        return jsonify({"error": f"Message must be {MAX_MESSAGE_LENGTH} characters or fewer"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("SELECT id FROM users WHERE id IN (%s, %s)", (sender_id, receiver_id))
        if len(cur.fetchall()) != 2:
            return jsonify({"error": "Sender or receiver not found"}), 404

        cur.execute("SELECT user_id FROM listings WHERE id = %s", (listing_id,))
        listing_row = cur.fetchone()
        if not listing_row:
            return jsonify({"error": "Listing not found"}), 404

        seller_id = listing_row[0]

        # Every chat is between the item's seller and one other user
        if sender_id != seller_id and receiver_id != seller_id:
            return jsonify({"error": "Messages about an item must involve its seller"}), 403

        cur.execute("""
            INSERT INTO messages (sender_id, receiver_id, listing_id, body, is_read)
            VALUES (%s, %s, %s, %s, FALSE)
            RETURNING id, created_at
        """, (sender_id, receiver_id, listing_id, body))
        new_row = cur.fetchone()
        conn.commit()

        return jsonify({
            "success": True,
            "message": {
                "id": new_row[0],
                "sender_id": sender_id,
                "receiver_id": receiver_id,
                "listing_id": listing_id,
                "body": body,
                "created_at": str(new_row[1]),
                "is_read": False
            }
        }), 201

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cur.close()
        conn.close()


# 2) List my chats (one per item + other person, newest first)
@app.route("/api/messages/chats", methods=["GET"])
def list_my_chats():
    user_id = request.args.get("user_id", type=int)

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            WITH my_msgs AS (
                SELECT m.*,
                       CASE WHEN m.sender_id = %s THEN m.receiver_id ELSE m.sender_id END AS other_id
                FROM messages m
                WHERE m.sender_id = %s OR m.receiver_id = %s
            )
            SELECT DISTINCT ON (mm.listing_id, mm.other_id)
                mm.listing_id,
                l.title,
                l.image,
                mm.other_id,
                u.username,
                mm.body,
                mm.created_at,
                mm.sender_id,
                (
                    SELECT COUNT(*)
                    FROM messages x
                    WHERE x.listing_id = mm.listing_id
                      AND x.sender_id = mm.other_id
                      AND x.receiver_id = %s
                      AND x.is_read = FALSE
                ) AS unread_count
            FROM my_msgs mm
            JOIN listings l ON l.id = mm.listing_id
            JOIN users u ON u.id = mm.other_id
            ORDER BY mm.listing_id, mm.other_id, mm.created_at DESC, mm.id DESC
        """, (user_id, user_id, user_id, user_id))

        rows = cur.fetchall()

        chats = [{
            "listing_id": r[0],
            "listing_title": r[1],
            "listing_image": r[2],
            "other_user_id": r[3],
            "other_username": r[4],
            "last_message": r[5],
            "last_message_time": str(r[6]),
            "last_message_from_me": r[7] == user_id,
            "unread_count": r[8]
        } for r in rows]

        # Newest conversation first
        chats.sort(key=lambda c: c["last_message_time"], reverse=True)

        return jsonify(chats), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cur.close()
        conn.close()


# 3) Open one chat (all messages for one item between me and one other person)
@app.route("/api/messages/chat", methods=["GET"])
def get_chat():
    user_id = request.args.get("user_id", type=int)
    other_user_id = request.args.get("other_user_id", type=int)
    listing_id = request.args.get("listing_id", type=int)

    if not user_id or not other_user_id or not listing_id:
        return jsonify({"error": "user_id, other_user_id, and listing_id are required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT l.id, l.title, l.image, l.user_id, u.username
            FROM listings l, users u
            WHERE l.id = %s AND u.id = %s
        """, (listing_id, other_user_id))
        info = cur.fetchone()

        if not info:
            return jsonify({"error": "Listing or user not found"}), 404

        cur.execute("""
            SELECT id, sender_id, receiver_id, body, created_at, is_read
            FROM messages
            WHERE listing_id = %s
              AND (
                    (sender_id = %s AND receiver_id = %s)
                 OR (sender_id = %s AND receiver_id = %s)
              )
            ORDER BY created_at ASC, id ASC
        """, (listing_id, user_id, other_user_id, other_user_id, user_id))

        rows = cur.fetchall()

        return jsonify({
            "listing": {
                "id": info[0],
                "title": info[1],
                "image": info[2],
                "seller_id": info[3]
            },
            "other_user": {
                "id": other_user_id,
                "username": info[4]
            },
            "messages": [{
                "id": r[0],
                "sender_id": r[1],
                "receiver_id": r[2],
                "body": r[3],
                "created_at": str(r[4]),
                "is_read": r[5]
            } for r in rows]
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cur.close()
        conn.close()


# 4) Mark a chat as read (only messages sent TO me)
@app.route("/api/messages/read", methods=["PUT"])
def mark_chat_read():
    data = request.get_json() or {}
    user_id = data.get("user_id")
    other_user_id = data.get("other_user_id")
    listing_id = data.get("listing_id")

    if not user_id or not other_user_id or not listing_id:
        return jsonify({"error": "user_id, other_user_id, and listing_id are required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            UPDATE messages
            SET is_read = TRUE
            WHERE receiver_id = %s
              AND sender_id = %s
              AND listing_id = %s
              AND is_read = FALSE
        """, (user_id, other_user_id, listing_id))

        updated = cur.rowcount
        conn.commit()

        return jsonify({"success": True, "marked_read": updated}), 200

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
# WALLET
# ========================
@app.route("/api/wallet/balance", methods=["GET"])
def get_wallet_balance():
    user_id = request.args.get("user_id", type=int)
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    try:
        from backend.Wallet import get_balance
        return jsonify({"balance": get_balance(user_id)}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/wallet/history", methods=["GET"])
def get_wallet_history():
    user_id = request.args.get("user_id", type=int)
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    try:
        from backend.Wallet import get_transaction_history
        return jsonify(get_transaction_history(user_id, 50, 0)), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/wallet/transfer", methods=["POST"])
def wallet_transfer():
    data = request.get_json() or {}
    password = data.get("password") or ""
    try:
        buyer_id = int(data.get("buyer_id"))
        seller_id = int(data.get("seller_id"))
        amount = float(data.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid parameters"}), 400

    if not password:
        return jsonify({"error": "Password confirmation (2FA) is required to transfer money."}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT password_hash FROM users WHERE id = %s", (buyer_id,))
        user_row = cur.fetchone()
        if not user_row or not user_row[0] or not bcrypt.checkpw(password.encode(), user_row[0].encode()):
            conn.rollback()
            return jsonify({"error": "Incorrect password. Transfer verification failed."}), 401
    finally:
        cur.close()
        conn.close()

    try:
        from backend.Wallet import transfer_money
        result = transfer_money(buyer_id, seller_id, amount)
        return jsonify({"success": result == 0, "error": "Insufficient funds" if result else None}), 200 if result == 0 else 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========================
# ADMIN
# ========================
@app.route("/api/admin/dashboard", methods=["GET"])
def get_admin_dashboard():
    role = request.args.get("role")

    if role != "admin":
        return jsonify({"error": "Forbidden"}), 403

   #  LOG ACTION 
    log_action("Admin", "VIEW_ADMIN_DASHBOARD", "Admin Dashboard")

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
            SELECT id, who, action, target, created_at
            FROM action_logs
            ORDER BY created_at DESC
            LIMIT 50
        """)
        action_log_rows = cur.fetchall()

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

        cur.execute("""
            SELECT
                rr.id,
                rr.listing_id,
                l.title,
                rr.seller_id,
                rr.buyer_id,
                rr.buyer_email,
                rr.reason,
                rr.status,
                rr.seller_note,
                rr.created_at,
                rr.reviewed_at
            FROM return_requests rr
            LEFT JOIN listings l ON rr.listing_id = l.id
            ORDER BY rr.created_at DESC
        """)
        return_request_rows = cur.fetchall()

        

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
            ],
            "return_requests": [
                {
                    "id": r[0],
                    "listing_id": r[1],
                    "title": r[2],
                    "seller_id": r[3],
                    "buyer_id": r[4],
                    "buyer_email": r[5],
                    "reason": r[6],
                    "status": r[7],
                    "seller_note": r[8],
                    "created_at": str(r[9]) if r[9] else None,
                    "reviewed_at": str(r[10]) if r[10] else None
                }
                for r in return_request_rows
            ],
            "action_logs": [
                {
                    "id": r[0],
                    "who": r[1],
                    "action": r[2],
                    "target": r[3],
                    "created_at": str(r[4]) if r[4] else None
                }
                for r in action_log_rows
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
