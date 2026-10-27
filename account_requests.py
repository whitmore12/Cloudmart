#Name: Makaila Williams
#Course: CSC-404
#account_requests.py: account deletion requests for eCamp
#a user asks to delete their account, an admin approves or denies it
#approving does not drop the row. it wipes the personal info so old sales and wallet history still make sense

import secrets
import time

import bcrypt
import psycopg
from flask import Blueprint, jsonify, request

accountRequests = Blueprint("accountRequests", __name__)

REASON_MAX = 500
NOTE_MAX = 500
MAX_TRIES = 5
LOCK_SECONDS = 300
#same lock number create_admin uses, so admin changes never run at the same time
ADMIN_LOCK = 781204926

dbFactory = None
tableReady = False
fileRemover = None
failedTries = {}

#initAccountRequests
#purpose: app.py calls this once. hands us its db connection and turns the routes on
def initAccountRequests(app, getConn, removeFile=None):
    global dbFactory, fileRemover, tableReady
    dbFactory = getConn
    fileRemover = removeFile
    tableReady = False
    if "accountRequests" not in app.blueprints:
        app.register_blueprint(accountRequests)

#makeTable
#purpose: builds the requests table if it is not there yet. the unique index means one pending request per user
def makeTable(cur):
    cur.execute("""
    CREATE TABLE IF NOT EXISTS account_deletion_requests (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES users(id),
        reason TEXT,
        status VARCHAR(20) DEFAULT 'pending',
        admin_id INTEGER REFERENCES users(id),
        admin_note TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        reviewed_at TIMESTAMP
    )
    """)
    cur.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS one_pending_deletion
    ON account_deletion_requests (user_id) WHERE status = 'pending'
    """)

#openDb
#purpose: gives back a connection and makes sure the table exists, only checks once per run
def openDb():
    global tableReady
    conn = dbFactory()
    if not tableReady:
        cur = conn.cursor()
        makeTable(cur)
        conn.commit()
        cur.close()
        tableReady = True
    return conn

#toInt
#purpose: turns a value into an int, gives back None if it cannot
def toInt(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

#passwordMatches
#purpose: checks a typed password against the saved hash
def passwordMatches(password, savedHash):
    try:
        return bcrypt.checkpw(password.encode(), savedHash.encode())
    except (ValueError, AttributeError):
        return False

#lockedOut
#purpose: true if this key missed the password too many times recently
def lockedOut(key):
    entry = failedTries.get(key)
    return bool(entry) and time.time() < entry["until"]

#noteFail
#purpose: counts a wrong password, locks the key for a bit after MAX_TRIES
def noteFail(key):
    entry = failedTries.get(key, {"fails": 0, "until": 0})
    entry["fails"] += 1
    if entry["fails"] >= MAX_TRIES:
        entry["until"] = time.time() + LOCK_SECONDS
        entry["fails"] = 0
    failedTries[key] = entry

#clearFails
#purpose: forgets the misses after a good password
def clearFails(key):
    failedTries.pop(key, None)

#rowToDict
#purpose: one request row from the admin or mine query as a dict
def rowToDict(r):
    return {
        "id": r[0],
        "user_id": r[1],
        "username": r[2],
        "email": r[3],
        "role": r[4],
        "reason": r[5],
        "status": r[6],
        "admin_note": r[7],
        "created_at": str(r[8]) if r[8] else None,
        "reviewed_at": str(r[9]) if r[9] else None,
    }

REQUEST_COLUMNS = """
    r.id, r.user_id, u.username, u.email, u.role, r.reason,
    r.status, r.admin_note, r.created_at, r.reviewed_at
"""

#getAdminHash
#purpose: looks the person up in the db and checks the role there. gives back their password hash or None. we do not trust a role sent from the browser
def getAdminHash(cur, adminId):
    cur.execute("SELECT password_hash, role FROM users WHERE id = %s", (adminId,))
    row = cur.fetchone()
    if not row or (row[1] or "").lower() != "admin":
        return None
    return row[0]

#blockers
#purpose: reasons this account cannot be deleted right now, empty list means good to go
def blockers(cur, userId):
    problems = []
    cur.execute("""
        SELECT COUNT(*) FROM return_requests
        WHERE status = 'pending' AND (seller_id = %s OR buyer_id = %s)
    """, (userId, userId))
    if cur.fetchone()[0] > 0:
        problems.append("This user still has pending return requests. Finish those first.")

    cur.execute("SELECT role FROM users WHERE id = %s", (userId,))
    row = cur.fetchone()
    if row and (row[0] or "").lower() == "admin":
        cur.execute("SELECT COUNT(*) FROM users WHERE LOWER(role) = 'admin' AND id <> %s", (userId,))
        if cur.fetchone()[0] == 0:
            problems.append("This is the only admin. Make another admin first.")
    return problems

#wipeAccount
#purpose: removes the personal info for one user and takes their stuff off the marketplace. gives back the old profile picture url so it can be deleted after the commit
def wipeAccount(cur, userId):
    cur.execute("SELECT email, profile_image FROM users WHERE id = %s FOR UPDATE", (userId,))
    row = cur.fetchone()
    if not row:
        raise ValueError("user %s does not exist" % userId)
    oldEmail, oldImage = row
    tag = "deleted_%s" % userId
    newEmail = tag + "@deleted.invalid"

    #active listings come off the marketplace, sold ones stay as history with the new name
    cur.execute("""
        UPDATE listings SET status = 'deleted', buyer_email = NULL
        WHERE user_id = %s AND COALESCE(status, 'active') = 'active'
    """, (userId,))
    cur.execute("UPDATE listings SET seller = %s WHERE user_id = %s", (tag, userId))

    #anything that still holds the old email as a buyer gets the new one
    if oldEmail:
        cur.execute("UPDATE listings SET buyer_email = %s WHERE LOWER(buyer_email) = LOWER(%s)", (newEmail, oldEmail))
        cur.execute("UPDATE return_requests SET buyer_email = %s WHERE LOWER(buyer_email) = LOWER(%s)", (newEmail, oldEmail))

    cur.execute("DELETE FROM wishlist WHERE user_id = %s", (userId,))

    #a real hash of a random password so login just fails with invalid credentials
    junk = bcrypt.hashpw(secrets.token_urlsafe(32).encode(), bcrypt.gensalt()).decode()
    cur.execute("""
        UPDATE users
        SET email = %s, username = %s, password_hash = %s, profile_image = NULL, role = 'deleted'
        WHERE id = %s
    """, (newEmail, tag, junk, userId))
    return oldImage

#dropImage
#purpose: tries to remove the old profile picture file. never stops the deletion if it fails
def dropImage(imageUrl):
    if fileRemover is None or not imageUrl:
        return
    try:
        fileRemover(imageUrl)
    except Exception:
        pass


#createRequest
@accountRequests.post("/api/account-requests")
def createRequest():
    data = request.get_json(silent=True) or {}
    userId = toInt(data.get("user_id"))
    password = data.get("password") or ""
    reason = (data.get("reason") or "").strip()

    if userId is None or not password:
        return jsonify({"error": "user_id and your password are required."}), 400
    if len(reason) > REASON_MAX:
        return jsonify({"error": "Reason must be %s characters or less." % REASON_MAX}), 400

    key = "user:%s" % userId
    if lockedOut(key):
        return jsonify({"error": "Too many wrong passwords. Try again later."}), 429

    conn = openDb()
    cur = conn.cursor()
    try:
        cur.execute("SELECT password_hash, role FROM users WHERE id = %s", (userId,))
        row = cur.fetchone()
        if not row or (row[1] or "").lower() == "deleted" or not passwordMatches(password, row[0]):
            noteFail(key)
            return jsonify({"error": "Wrong password."}), 401
        clearFails(key)

        cur.execute("""
            INSERT INTO account_deletion_requests (user_id, reason)
            VALUES (%s, %s) RETURNING id
        """, (userId, reason or None))
        newId = cur.fetchone()[0]
        conn.commit()
        return jsonify({"success": True, "message": "Deletion request sent to the admins.", "request_id": newId}), 201
    except psycopg.errors.UniqueViolation:
        conn.rollback()
        return jsonify({"error": "You already have a pending deletion request."}), 409
    except Exception:
        conn.rollback()
        return jsonify({"error": "Could not send the request."}), 500
    finally:
        cur.close()
        conn.close()

#see your own latest request
@accountRequests.get("/api/account-requests/mine")
def myRequest():
    userId = toInt(request.args.get("user_id"))
    if userId is None:
        return jsonify({"error": "user_id is required."}), 400

    conn = openDb()
    cur = conn.cursor()
    try:
        query = """
            SELECT %s FROM account_deletion_requests r
            JOIN users u ON u.id = r.user_id
            WHERE r.user_id = %%s
            ORDER BY r.created_at DESC, r.id DESC LIMIT 1
        """ % REQUEST_COLUMNS
        cur.execute(query, (userId,))
        row = cur.fetchone()
        return jsonify({"request": rowToDict(row) if row else None}), 200
    finally:
        cur.close()
        conn.close()

#take your request back
@accountRequests.put("/api/account-requests/<int:requestId>/cancel")
def cancelRequest(requestId):
    data = request.get_json(silent=True) or {}
    userId = toInt(data.get("user_id"))
    if userId is None:
        return jsonify({"error": "user_id is required."}), 400

    conn = openDb()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE account_deletion_requests
            SET status = 'cancelled', reviewed_at = CURRENT_TIMESTAMP
            WHERE id = %s AND user_id = %s AND status = 'pending'
        """, (requestId, userId))
        if cur.rowcount == 0:
            conn.rollback()
            return jsonify({"error": "No pending request of yours with that id."}), 404
        conn.commit()
        return jsonify({"success": True, "message": "Request cancelled."}), 200
    except Exception:
        conn.rollback()
        return jsonify({"error": "Could not cancel the request."}), 500
    finally:
        cur.close()
        conn.close()

#admin list
@accountRequests.get("/api/admin/account-requests")
def listRequests():
    adminId = toInt(request.args.get("admin_id"))
    status = (request.args.get("status") or "").strip().lower()
    if adminId is None:
        return jsonify({"error": "admin_id is required."}), 400
    if status and status not in ("pending", "approved", "denied", "cancelled"):
        return jsonify({"error": "Unknown status."}), 400

    conn = openDb()
    cur = conn.cursor()
    try:
        if getAdminHash(cur, adminId) is None:
            return jsonify({"error": "Forbidden"}), 403
        where = "WHERE r.status = %s" if status else ""
        args = (status,) if status else ()
        cur.execute("""
            SELECT %s FROM account_deletion_requests r
            JOIN users u ON u.id = r.user_id
            %s
            ORDER BY CASE WHEN r.status = 'pending' THEN 0 ELSE 1 END, r.created_at DESC, r.id DESC
        """ % (REQUEST_COLUMNS, where), args)
        return jsonify([rowToDict(r) for r in cur.fetchall()]), 200
    finally:
        cur.close()
        conn.close()

#admin approve or deny
@accountRequests.put("/api/admin/account-requests/<int:requestId>/review")
def reviewRequest(requestId):
    data = request.get_json(silent=True) or {}
    adminId = toInt(data.get("admin_id"))
    action = (data.get("action") or "").strip().lower()
    note = (data.get("admin_note") or "").strip()
    adminPassword = data.get("admin_password") or ""

    if adminId is None:
        return jsonify({"error": "admin_id is required."}), 400
    if action not in ("approve", "deny"):
        return jsonify({"error": "Action must be approve or deny."}), 400
    if len(note) > NOTE_MAX:
        return jsonify({"error": "Note must be %s characters or less." % NOTE_MAX}), 400

    key = "admin:%s" % adminId
    if lockedOut(key):
        return jsonify({"error": "Too many wrong passwords. Try again later."}), 429

    conn = openDb()
    cur = conn.cursor()
    imageToDrop = None
    try:
        #only one admin change at a time, so two admins cannot delete each other
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (ADMIN_LOCK,))

        adminHash = getAdminHash(cur, adminId)
        if adminHash is None:
            conn.rollback()
            return jsonify({"error": "Forbidden"}), 403

        #deleting is permanent so approving needs the admin password again
        if action == "approve":
            if not passwordMatches(adminPassword, adminHash):
                conn.rollback()
                noteFail(key)
                return jsonify({"error": "Wrong admin password."}), 403
            clearFails(key)

        cur.execute("""
            SELECT user_id, status FROM account_deletion_requests
            WHERE id = %s FOR UPDATE
        """, (requestId,))
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return jsonify({"error": "Request not found."}), 404
        userId, current = row
        if current != "pending":
            conn.rollback()
            return jsonify({"error": "This request was already handled."}), 400

        if action == "approve":
            if userId == adminId:
                conn.rollback()
                return jsonify({"error": "Another admin has to approve your own request."}), 400
            problems = blockers(cur, userId)
            if problems:
                conn.rollback()
                return jsonify({"error": " ".join(problems)}), 409
            imageToDrop = wipeAccount(cur, userId)

        newStatus = "approved" if action == "approve" else "denied"
        cur.execute("""
            UPDATE account_deletion_requests
            SET status = %s, admin_id = %s, admin_note = %s, reviewed_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (newStatus, adminId, note or None, requestId))
        conn.commit()
    except Exception:
        conn.rollback()
        return jsonify({"error": "Could not finish the review."}), 500
    finally:
        cur.close()
        conn.close()

    #only after the commit, so a failed delete never loses the picture
    dropImage(imageToDrop)
    return jsonify({"success": True, "message": "Request %s." % newStatus}), 200