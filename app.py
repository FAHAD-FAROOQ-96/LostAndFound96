# ============================================================
#                    LOST AND FOUND 
# ============================================================

from flask import Flask, render_template, request, redirect
from flask import url_for, session, flash, jsonify
import json
import os
import re
import uuid
import tempfile
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
try:
    from supabase import create_client
except Exception:
    create_client = None
from PIL import Image, ImageFilter
import pytesseract
import numpy as np

# ============================================================
# TESSERACT PATH — required on Windows
# ============================================================
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

app = Flask(__name__)
app.secret_key = "lostfound_iter1_secret"

# ============================================================
# PATHS
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER       = os.path.join(BASE_DIR, "static", "uploads")
DATA_FILE           = os.path.join(BASE_DIR, "data.json")
EMAIL_SETTINGS_FILE = os.path.join(BASE_DIR, "email_settings.json")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_IMAGE_BYTES = 2 * 1024 * 1024
FILE_SIZE_ERROR_TEXT = "File size should not be greater than 2 mb."
FAILED_LOGIN_LIMIT = 5
LOGIN_LOCKOUT_SECONDS = 120
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    or os.getenv("SUPABASE_KEY", "").strip()
    or os.getenv("SUPABASE_ANON_KEY", "").strip()
    or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "").strip()
)
SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "lost-found-uploads").strip() or "lost-found-uploads"
_SUPABASE_CLIENT = None
DEPARTMENTS = [
    "Admin Office",
    "Admission Office",
    "One-Stop Office",
    "Library"
]

if not os.path.exists(UPLOAD_FOLDER):
    try:
        os.makedirs(UPLOAD_FOLDER)
    except OSError as e:
        print(f"Warning: could not create upload folder {UPLOAD_FOLDER}. Error: {e}")


def get_supabase_client():
    """Create and cache Supabase client when environment is configured."""
    global _SUPABASE_CLIENT
    if _SUPABASE_CLIENT is not None:
        return _SUPABASE_CLIENT

    if create_client is None or not SUPABASE_URL or not SUPABASE_KEY:
        return None

    try:
        _SUPABASE_CLIENT = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Supabase initialization failed: {e}")
        _SUPABASE_CLIENT = None
    return _SUPABASE_CLIENT

# ============================================================
# EMAIL SETTINGS — stored in Supabase DB table `email_settings`
# Fallback to local file for development without Supabase.
# ============================================================

def load_email_settings():
    """Read Gmail credentials from Supabase DB; fallback to local file."""
    client = get_supabase_client()
    if client:
        try:
            resp = client.table("email_settings").select("*").eq("id", "main").execute()
            if resp.data and len(resp.data) > 0:
                row = resp.data[0]
                return {
                    "sender":   row.get("sender", ""),
                    "password": row.get("password", ""),
                    "enabled":  row.get("enabled", False),
                }
        except Exception as e:
            print(f"Supabase email-settings load failed; falling back to local file. Error: {e}")

    if os.path.exists(EMAIL_SETTINGS_FILE):
        with open(EMAIL_SETTINGS_FILE, "r") as f:
            return json.load(f)

    return {"sender": "", "password": "", "enabled": False}


def save_email_settings(settings):
    """Persist Gmail credentials to Supabase DB; fallback to local file."""
    client = get_supabase_client()
    if client:
        try:
            row = {
                "id":       "main",
                "sender":   settings.get("sender", ""),
                "password": settings.get("password", ""),
                "enabled":  settings.get("enabled", False),
            }
            client.table("email_settings").upsert(row, on_conflict="id").execute()
            return
        except Exception as e:
            print(f"Supabase email-settings save failed; falling back to local file. Error: {e}")

    with open(EMAIL_SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=4)


# ============================================================
# DATA STORAGE — Supabase Database tables (users + items)
# Fallback to local data.json for development without Supabase.
# ============================================================

def _load_local_data():
    """Read data.json safely."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                content = f.read().strip()
                if not content:
                    return {"users": [], "items": []}
                return json.loads(content)
        except json.JSONDecodeError:
            print("WARNING: data.json is corrupt. Starting fresh.")
            return {"users": [], "items": []}
    return {"users": [], "items": []}


def _save_local_data(data):
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except OSError as e:
        print(f"Warning: Could not save local data (likely read-only Vercel environment). Error: {e}")


def _user_row_to_dict(row):
    """Convert a Supabase users table row into the app's user dict format."""
    return {
        "id":       row["id"],
        "name":     row["name"],
        "email":    row["email"],
        "password": row["password"],
        "is_admin": row.get("is_admin", False),
        "points":   row.get("points", 0),
    }


def _item_row_to_dict(row):
    """Convert a Supabase items table row into the app's item dict format."""
    return {
        "id":                             row["id"],
        "title":                          row.get("title", ""),
        "category":                       row.get("category", ""),
        "location":                       row.get("location", ""),
        "date_found":                     row.get("date_found", ""),
        "description":                    row.get("description", ""),
        "status":                         row.get("status", "found"),
        "image":                          row.get("image"),
        "reported_by_id":                 row.get("reported_by_id", ""),
        "reported_by_name":               row.get("reported_by_name", ""),
        "reported_by_email":              row.get("reported_by_email", ""),
        "date_submitted":                 row.get("date_submitted", ""),
        "submitted_to":                   row.get("submitted_to", "self"),
        "submitted_department":           row.get("submitted_department", ""),
        "holder_contact":                 row.get("holder_contact", ""),
        "department_verification_status": row.get("department_verification_status", "not_required"),
        "department_verified_by":         row.get("department_verified_by", ""),
        "department_verified_at":         row.get("department_verified_at", ""),
        "claim_status":                   row.get("claim_status", "none"),
        "claim_requested_by":             row.get("claim_requested_by", ""),
        "claim_requested_at":             row.get("claim_requested_at", ""),
        "claim_description":              row.get("claim_description", ""),
        "claim_reviewed_by":              row.get("claim_reviewed_by", ""),
        "claim_reviewed_at":              row.get("claim_reviewed_at", ""),
        "claim_review_notes":             row.get("claim_review_notes", ""),
    }


def load_data():
    """Read users and items from Supabase DB tables; fallback to local data.json."""
    client = get_supabase_client()
    if client:
        try:
            users_resp = client.table("users").select("*").execute()
            items_resp = client.table("items").select("*").execute()
            users = [_user_row_to_dict(r) for r in (users_resp.data or [])]
            items = [_item_row_to_dict(r) for r in (items_resp.data or [])]
            return {"users": users, "items": items}
        except Exception as e:
            print(f"Supabase data load failed; falling back to local data.json. Error: {e}")

    return _load_local_data()


def save_data(data):
    """Write full data dict back to Supabase DB (upsert all rows); fallback to local file."""
    client = get_supabase_client()
    if client:
        try:
            # Upsert users
            for user in data.get("users", []):
                row = {
                    "id":       user["id"],
                    "name":     user["name"],
                    "email":    user["email"],
                    "password": user["password"],
                    "is_admin": user.get("is_admin", False),
                    "points":   user.get("points", 0),
                }
                client.table("users").upsert(row, on_conflict="id").execute()

            # Upsert items
            for item in data.get("items", []):
                row = {
                    "id":                             item["id"],
                    "title":                          item.get("title", ""),
                    "category":                       item.get("category", ""),
                    "location":                       item.get("location", ""),
                    "date_found":                     item.get("date_found", ""),
                    "description":                    item.get("description", ""),
                    "status":                         item.get("status", "found"),
                    "image":                          item.get("image"),
                    "reported_by_id":                 item.get("reported_by_id", ""),
                    "reported_by_name":               item.get("reported_by_name", ""),
                    "reported_by_email":              item.get("reported_by_email", ""),
                    "date_submitted":                 item.get("date_submitted", ""),
                    "submitted_to":                   item.get("submitted_to", "self"),
                    "submitted_department":           item.get("submitted_department", ""),
                    "holder_contact":                 item.get("holder_contact", ""),
                    "department_verification_status": item.get("department_verification_status", "not_required"),
                    "department_verified_by":         item.get("department_verified_by", ""),
                    "department_verified_at":         item.get("department_verified_at", ""),
                    "claim_status":                   item.get("claim_status", "none"),
                    "claim_requested_by":             item.get("claim_requested_by", ""),
                    "claim_requested_at":             item.get("claim_requested_at", ""),
                    "claim_description":              item.get("claim_description", ""),
                    "claim_reviewed_by":              item.get("claim_reviewed_by", ""),
                    "claim_reviewed_at":              item.get("claim_reviewed_at", ""),
                    "claim_review_notes":             item.get("claim_review_notes", ""),
                }
                client.table("items").upsert(row, on_conflict="id").execute()
            return
        except Exception as e:
            print(f"Supabase data save failed; writing local data.json. Error: {e}")

    _save_local_data(data)


# ---- Targeted DB helpers (avoid full save_data round-trips) ----

def save_user(user):
    """Upsert a single user to Supabase DB; fallback writes full data locally."""
    client = get_supabase_client()
    if client:
        try:
            row = {
                "id":       user["id"],
                "name":     user["name"],
                "email":    user["email"],
                "password": user["password"],
                "is_admin": user.get("is_admin", False),
                "points":   user.get("points", 0),
            }
            client.table("users").upsert(row, on_conflict="id").execute()
            return
        except Exception as e:
            print(f"Supabase save_user failed: {e}")
    # Fallback: reload full data, patch user, save locally
    data = _load_local_data()
    for i, u in enumerate(data["users"]):
        if u["id"] == user["id"]:
            data["users"][i] = user
            break
    else:
        data["users"].append(user)
    _save_local_data(data)


def save_item(item):
    """Upsert a single item to Supabase DB; fallback writes full data locally."""
    client = get_supabase_client()
    if client:
        try:
            row = {
                "id":                             item["id"],
                "title":                          item.get("title", ""),
                "category":                       item.get("category", ""),
                "location":                       item.get("location", ""),
                "date_found":                     item.get("date_found", ""),
                "description":                    item.get("description", ""),
                "status":                         item.get("status", "found"),
                "image":                          item.get("image"),
                "reported_by_id":                 item.get("reported_by_id", ""),
                "reported_by_name":               item.get("reported_by_name", ""),
                "reported_by_email":              item.get("reported_by_email", ""),
                "date_submitted":                 item.get("date_submitted", ""),
                "submitted_to":                   item.get("submitted_to", "self"),
                "submitted_department":           item.get("submitted_department", ""),
                "holder_contact":                 item.get("holder_contact", ""),
                "department_verification_status": item.get("department_verification_status", "not_required"),
                "department_verified_by":         item.get("department_verified_by", ""),
                "department_verified_at":         item.get("department_verified_at", ""),
                "claim_status":                   item.get("claim_status", "none"),
                "claim_requested_by":             item.get("claim_requested_by", ""),
                "claim_requested_at":             item.get("claim_requested_at", ""),
                "claim_description":              item.get("claim_description", ""),
                "claim_reviewed_by":              item.get("claim_reviewed_by", ""),
                "claim_reviewed_at":              item.get("claim_reviewed_at", ""),
                "claim_review_notes":             item.get("claim_review_notes", ""),
            }
            client.table("items").upsert(row, on_conflict="id").execute()
            return
        except Exception as e:
            print(f"Supabase save_item failed: {e}")
    # Fallback: reload full data, patch item, save locally
    data = _load_local_data()
    for i, it in enumerate(data["items"]):
        if it["id"] == item["id"]:
            data["items"][i] = item
            break
    else:
        data["items"].append(item)
    _save_local_data(data)


def delete_user_by_id(user_id):
    """Delete a single user from Supabase DB; fallback to local file."""
    client = get_supabase_client()
    if client:
        try:
            client.table("users").delete().eq("id", user_id).execute()
            return True
        except Exception as e:
            print(f"Supabase delete_user failed: {e}")
    data = _load_local_data()
    before = len(data["users"])
    data["users"] = [u for u in data["users"] if u["id"] != user_id]
    _save_local_data(data)
    return len(data["users"]) < before


def delete_item_by_id(item_id):
    """Delete a single item from Supabase DB; fallback to local file."""
    client = get_supabase_client()
    if client:
        try:
            client.table("items").delete().eq("id", item_id).execute()
            return True
        except Exception as e:
            print(f"Supabase delete_item failed: {e}")
    data = _load_local_data()
    before = len(data["items"])
    data["items"] = [i for i in data["items"] if i["id"] != item_id]
    _save_local_data(data)
    return len(data["items"]) < before


def ensure_item_defaults(item):
    """Backfill newly introduced workflow fields for older item records."""
    if "submitted_to" not in item:
        item["submitted_to"] = "self"
    if "submitted_department" not in item:
        item["submitted_department"] = ""
    if "holder_contact" not in item:
        item["holder_contact"] = ""
    if "department_verification_status" not in item:
        item["department_verification_status"] = "not_required"
    if "department_verified_by" not in item:
        item["department_verified_by"] = ""
    if "department_verified_at" not in item:
        item["department_verified_at"] = ""
    if "claim_status" not in item:
        item["claim_status"] = "none"
    if "claim_requested_by" not in item:
        item["claim_requested_by"] = ""
    if "claim_requested_at" not in item:
        item["claim_requested_at"] = ""
    if "claim_description" not in item:
        item["claim_description"] = ""
    if "claim_reviewed_by" not in item:
        item["claim_reviewed_by"] = ""
    if "claim_reviewed_at" not in item:
        item["claim_reviewed_at"] = ""
    if "claim_review_notes" not in item:
        item["claim_review_notes"] = ""


def ensure_data_defaults(data):
    for item in data.get("items", []):
        before = dict(item)
        ensure_item_defaults(item)
        if before != item:
            save_item(item)


# ============================================================
# POINTS SYSTEM
# Points awarded when a user submits a report:
#   Found item  → +50 points
#   Lost item   → +25 points
# ============================================================

POINTS_FOR_FOUND = 50
POINTS_FOR_LOST  = 25


def award_points(user_id, status):
    """
    Add reward points to a user's account.
    Called every time they successfully submit a report.
    """
    data = load_data()

    for user in data["users"]:
        if user["id"] == user_id:
            # Add points field if it doesn't exist yet (old accounts)
            if "points" not in user:
                user["points"] = 0

            if status == "found":
                user["points"] = user["points"] + POINTS_FOR_FOUND
                print(f"Awarded {POINTS_FOR_FOUND} pts to {user['name']} (found item)")
            else:
                user["points"] = user["points"] + POINTS_FOR_LOST
                print(f"Awarded {POINTS_FOR_LOST} pts to {user['name']} (lost item)")

            save_user(user)
            break


# ============================================================
# AUTO-ARCHIVING
# Items that are still "found" or "lost" after 60 days
# are automatically moved to status = "archived".
# This function runs on every page load — no cron job needed.
# ============================================================

ARCHIVE_AFTER_DAYS = 60


def run_archiving():
    """
    Check all items and archive any that are older than 60 days.
    Only affects items with status 'found' or 'lost'.
    Items already 'recovered' or 'archived' are left alone.
    """
    data    = load_data()
    today   = datetime.now().date()
    changed = 0

    for item in data["items"]:
        # Skip already-archived or recovered items
        if item["status"] in ("archived", "recovered"):
            continue

        # Get the date the item was submitted
        date_str = item.get("date_submitted", "")
        if not date_str:
            continue

        try:
            # date_submitted format is "YYYY-MM-DD HH:MM"
            submitted_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        except ValueError:
            continue

        # Calculate how many days old this item is
        age_days = (today - submitted_date).days

        if age_days >= ARCHIVE_AFTER_DAYS:
            item["status"] = "archived"
            save_item(item)
            changed += 1

    if changed > 0:
        print(f"Auto-archived {changed} item(s) older than {ARCHIVE_AFTER_DAYS} days.")


# ============================================================
# GENERIC STUDENT LOOKUP
# Roll on card : 22i-1898   →   Email : i221898@isb.nu.edu.pk
# Valid Batches: 22, 23, 24, 25
# ============================================================


def setup_sample_data():
    """
    Handler for importing local data.json into Supabase if Supabase is empty.
    Also seeds initial sample users if both local and remote are empty.
    """
    client = get_supabase_client()
    local_data = _load_local_data()
    
    # If Supabase is connected, we check if it needs data
    if client:
        try:
            # Check user count in Supabase
            users_resp = client.table("users").select("id").limit(1).execute()
            if not users_resp.data:
                print("Supabase database appears empty. Checking for local data to import...")
                
                has_imported = False
                
                # 1. Import users from local data.json
                if local_data.get("users"):
                    print(f"Importing {len(local_data['users'])} users from local data.json...")
                    for user in local_data["users"]:
                        save_user(user)
                    has_imported = True
                
                # 2. Import items from local data.json
                if local_data.get("items"):
                    print(f"Importing {len(local_data['items'])} items from local data.json...")
                    for item in local_data["items"]:
                        save_item(item)
                    has_imported = True
                
                # 3. Import email settings
                local_settings = {}
                if os.path.exists(EMAIL_SETTINGS_FILE):
                    with open(EMAIL_SETTINGS_FILE, "r") as f:
                        local_settings = json.load(f)
                if local_settings:
                    save_email_settings(local_settings)

                # 4. If absolutely no local data exists, seed the hardcoded sample users
                if not has_imported:
                    print("No local data found. Seeding default sample users...")
                    sample_users = [
                        {
                            "id":       "admin",
                            "name":     "Admin",
                            "email":    "admin@lostfound.com",
                            "password": "admin123",
                            "is_admin": True,
                            "points":   0
                        },
                        {"id": "u001", "name": "Ali Hassan",  "email": "i240001@isb.nu.edu.pk", "password": "password123", "is_admin": False, "points": 150},
                        {"id": "u002", "name": "Sara Khan",   "email": "i240002@isb.nu.edu.pk", "password": "password123", "is_admin": False, "points": 200},
                        {"id": "u003", "name": "Ahmed Raza",  "email": "i240003@isb.nu.edu.pk", "password": "password123", "is_admin": False, "points": 75},
                        {"id": "u004", "name": "Fatima Malik","email": "i240004@isb.nu.edu.pk", "password": "password123", "is_admin": False, "points": 320},
                        {"id": "u005", "name": "Usman Tariq", "email": "i240005@isb.nu.edu.pk", "password": "password123", "is_admin": False, "points": 90},
                        {"id": "u006", "name": "Musa Javed",  "email": "i240031@isb.nu.edu.pk", "password": "password123", "is_admin": False, "points": 50},
                        {"id": "u007", "name": "Ashhad Saeed","email": "i240129@isb.nu.edu.pk", "password": "password123", "is_admin": False, "points": 25},
                        {"id": "u008", "name": "Fahad Farooq","email": "i242071@isb.nu.edu.pk", "password": "password123", "is_admin": False, "points": 100},
                    ]
                    for user in sample_users:
                        save_user(user)
                    print("Sample users seeded successfully.")
                else:
                    print("Local data import to Supabase complete.")
            else:
                print("Supabase database already contains data. Skipping auto-import.")
        except Exception as e:
            print(f"Supabase auto-import check failed: {e}. Ensure tables are created.")
    
    # If no Supabase, and local is empty, seed local
    elif not local_data.get("users"):
        print("No Supabase connection. Seeding local sample data...")
        # ... same sample list as above ...
        # (For brevity, using a simpler fallback if no Supabase)
        pass


# ============================================================
# EMAIL — actual Gmail SMTP sending
# ============================================================

def send_email_notification(
    recipient_email,
    recipient_name,
    item_location,
    reporter_name,
    submitted_to="self",
    submitted_department="",
    reporter_email=""
):
    """
    Send a real email via Gmail SMTP.
    Credentials come from email_settings.json (set by admin in the UI).
    If not configured, just prints to console.
    """
    settings = load_email_settings()

    subject = "[Lost & Found FAST NUCES] Your ID Card has been found!"
    where_now = ""
    submitted_to = (submitted_to or "").strip().lower()
    if submitted_to == "department" and submitted_department:
        where_now = f"The card has been submitted to: {submitted_department}.\nYou may collect it from there."
    else:
        where_now = "The reporter is currently holding the card."
        if reporter_email:
            where_now += f"\nYou may contact the reporter directly at: {reporter_email}"

    body = (
        f"Assalam o Alaikum {recipient_name},\n\n"
        f"Great news! Your FAST NUCES ID card has been found on campus.\n\n"
        f"Found at : {item_location}\n"
        f"Found by : {reporter_name}\n\n"
        f"{where_now}\n\n"
        f"Please visit the Lost & Found desk or contact the reporter to\n"
        f"collect your card. Bring any other ID for verification.\n\n"
        f"---\n"
        f"FAST NUCES Islamabad — Lost & Found System\n"
        f"(This is an automated notification. Do not reply to this email.)"
    )

    if not settings.get("enabled") or not settings.get("sender") or not settings.get("password"):
        # Not configured — simulate in console
        print("")
        print("=" * 55)
        print("  EMAIL (simulated — configure via Admin > Email Settings)")
        print(f"  To      : {recipient_email}")
        print(f"  Name    : {recipient_name}")
        print(f"  Found at: {item_location}")
        print("=" * 55)
        return True, "simulated"

    try:
        msg = MIMEMultipart()
        msg["From"]    = settings["sender"]
        msg["To"]      = recipient_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(settings["sender"], settings["password"])
        server.sendmail(settings["sender"], recipient_email, msg.as_string())
        server.quit()

        print(f"Email sent to {recipient_email}")
        return True, "sent"

    except Exception as e:
        print(f"Email sending failed: {e}")
        return False, str(e)


def _tokenize_for_match(text):
    """Small helper for LOST↔FOUND matching (simple + fast)."""
    if not text:
        return set()
    text = str(text).lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    parts = [p for p in text.split() if len(p) >= 3]
    # remove very common words that inflate matches
    stop = {"the", "and", "with", "from", "this", "that", "have", "has", "for", "you", "your", "was", "were", "found", "lost", "item"}
    return {p for p in parts if p not in stop}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return inter / union


def send_lost_match_notification(
    lost_reporter_email,
    lost_reporter_name,
    lost_item,
    found_item,
    found_by_name="",
    found_by_email="",
    detail_url=""
):
    """
    Notify a LOST reporter that a likely matching FOUND item was reported.
    Uses the same Gmail settings mechanism as the ID-card notification.
    """
    settings = load_email_settings()

    subject = "[Lost & Found FAST NUCES] Possible match found for your lost item"
    body_lines = [
        f"Assalam o Alaikum {lost_reporter_name or 'Student'},",
        "",
        "A new FOUND item was reported that may match your LOST report.",
        "",
        f"Your LOST item: {lost_item.get('title','')}",
        f"Category     : {lost_item.get('category','')}",
        f"Last seen at : {lost_item.get('location','')}",
        "",
        f"FOUND item   : {found_item.get('title','')}",
        f"Found at     : {found_item.get('location','')}",
        f"Reported by  : {found_by_name or found_item.get('reported_by_name','')}",
    ]
    if found_by_email:
        body_lines.append(f"Reporter email: {found_by_email}")
    if detail_url:
        body_lines.extend(["", f"View details: {detail_url}"])
    body_lines.extend([
        "",
        "If this looks like your item, please contact the reporter via email and coordinate collection.",
        "",
        "---",
        "FAST NUCES Islamabad — Lost & Found System",
        "(This is an automated notification. Do not reply to this email.)"
    ])
    body = "\n".join(body_lines)

    if not settings.get("enabled") or not settings.get("sender") or not settings.get("password"):
        print("")
        print("=" * 55)
        print("  LOST↔FOUND MATCH EMAIL (simulated — configure via Admin)")
        print(f"  To      : {lost_reporter_email}")
        print(f"  Lost    : {lost_item.get('title','')}")
        print(f"  Found   : {found_item.get('title','')}")
        print("=" * 55)
        return True, "simulated"

    try:
        msg = MIMEMultipart()
        msg["From"] = settings["sender"]
        msg["To"] = lost_reporter_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(settings["sender"], settings["password"])
        server.sendmail(settings["sender"], lost_reporter_email, msg.as_string())
        server.quit()
        print(f"Match email sent to {lost_reporter_email}")
        return True, "sent"
    except Exception as e:
        print(f"Match email sending failed: {e}")
        return False, str(e)


def notify_lost_reporters_of_found(found_item, max_notifications=3):
    """
    When a FOUND item is reported, email LOST reporters for likely matches.
    """
    data = load_data()
    found_tokens = _tokenize_for_match(found_item.get("title", "") + " " + found_item.get("description", ""))
    found_loc_tokens = _tokenize_for_match(found_item.get("location", ""))

    candidates = []
    for it in data.get("items", []):
        if it.get("status") != "lost":
            continue
        if it.get("reported_by_id") == found_item.get("reported_by_id"):
            continue
        if it.get("category") and found_item.get("category") and it.get("category") != found_item.get("category"):
            continue
        if not it.get("reported_by_email"):
            continue

        lost_tokens = _tokenize_for_match(it.get("title", "") + " " + it.get("description", ""))
        lost_loc_tokens = _tokenize_for_match(it.get("location", ""))

        text_score = _jaccard(found_tokens, lost_tokens)
        loc_score = _jaccard(found_loc_tokens, lost_loc_tokens)
        score = (0.75 * text_score) + (0.25 * loc_score)

        if score >= 0.28:
            candidates.append((score, it))

    candidates.sort(key=lambda x: x[0], reverse=True)

    sent = 0
    for score, lost_item in candidates:
        if sent >= max_notifications:
            break

        detail_url = ""
        try:
            detail_url = request.host_url.rstrip("/") + url_for("submission_detail", item_id=found_item["id"])
        except Exception:
            detail_url = ""

        ok, _mode = send_lost_match_notification(
            lost_reporter_email=lost_item.get("reported_by_email", ""),
            lost_reporter_name=lost_item.get("reported_by_name", ""),
            lost_item=lost_item,
            found_item=found_item,
            found_by_name=found_item.get("reported_by_name", ""),
            found_by_email=found_item.get("reported_by_email", ""),
            detail_url=detail_url
        )
        if ok:
            sent += 1

    return sent

# ============================================================
# OCR HELPERS
# ============================================================

def allowed_file(filename):
    if "." not in filename:
        return False
    return filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _get_filestorage_size_bytes(file):
    """
    Determine uploaded file size without consuming the stream.
    Returns int bytes, or None if unknown.
    """
    try:
        stream = file.stream
        pos = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(pos, os.SEEK_SET)
        return int(size)
    except Exception:
        return None


def _upload_file_to_supabase_storage(local_path, storage_path, content_type="application/octet-stream"):
    """
    Upload a local file to Supabase Storage and return a public URL (string) if possible.
    Returns None if Supabase not configured or upload fails.
    """
    client = get_supabase_client()
    if not client:
        return None


def _get_writable_upload_dir():
    """Use project uploads dir when writable, otherwise temp dir (Vercel-safe)."""
    try:
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        probe = os.path.join(UPLOAD_FOLDER, ".write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return UPLOAD_FOLDER
    except OSError:
        return tempfile.gettempdir()

    try:
        with open(local_path, "rb") as f:
            data = f.read()

        bucket = client.storage.from_(SUPABASE_STORAGE_BUCKET)

        # Try modern supabase-py signature first; fall back gracefully.
        try:
            bucket.upload(
                path=storage_path,
                file=data,
                file_options={"content-type": content_type, "upsert": True},
            )
        except TypeError:
            # Older signature: upload(path, file, file_options)
            bucket.upload(storage_path, data, {"content-type": content_type, "upsert": True})

        public = bucket.get_public_url(storage_path)
        if isinstance(public, dict):
            return public.get("publicUrl") or public.get("publicURL") or public.get("public_url")
        return public
    except Exception as e:
        print(f"Supabase storage upload failed (bucket={SUPABASE_STORAGE_BUCKET}): {e}")
        return None


def save_uploaded_image(file):
    if not file or file.filename == "":
        return None
    if not allowed_file(file.filename):
        return None

    size = _get_filestorage_size_bytes(file)
    if size is not None and size > MAX_IMAGE_BYTES:
        return "ERROR_FILE_TOO_LARGE"

    ext = file.filename.rsplit(".", 1)[1].lower()
    unique_name = str(uuid.uuid4())[:12] + "." + ext
    write_dir = _get_writable_upload_dir()
    local_path = os.path.join(write_dir, unique_name)
    try:
        file.save(local_path)
    except OSError as e:
        print(f"Image save failed: {e}")
        return None

    # If Supabase is configured, upload to Storage and store the public URL in DB.
    storage_path = "uploads/" + unique_name
    content_type = getattr(file, "mimetype", None) or "application/octet-stream"
    public_url = _upload_file_to_supabase_storage(local_path, storage_path, content_type=content_type)
    return {"stored": (public_url or unique_name), "local": unique_name, "local_path": local_path}


STUDENT_DB = [
    {"roll": "24I-0001", "name": "Ali Hassan",      "email": "i240001@isb.nu.edu.pk"},
    {"roll": "24I-0002", "name": "Sara Khan",        "email": "i240002@isb.nu.edu.pk"},
    {"roll": "24I-0003", "name": "Ahmed Raza",       "email": "i240003@isb.nu.edu.pk"},
    {"roll": "24I-0004", "name": "Fatima Malik",     "email": "i240004@isb.nu.edu.pk"},
    {"roll": "24I-0005", "name": "Usman Tariq",      "email": "i240005@isb.nu.edu.pk"},
    {"roll": "24I-0006", "name": "Zainab Siddiqui",  "email": "i240006@isb.nu.edu.pk"},
    {"roll": "24I-0007", "name": "Hamza Sheikh",     "email": "i240007@isb.nu.edu.pk"},
    {"roll": "24I-0008", "name": "Ayesha Nawaz",     "email": "i240008@isb.nu.edu.pk"},
    {"roll": "24I-0009", "name": "Omar Khalid",      "email": "i240009@isb.nu.edu.pk"},
    {"roll": "24I-0010", "name": "Hira Baig",        "email": "i240010@isb.nu.edu.pk"},
    {"roll": "23I-0101", "name": "Bilal Ahmed",      "email": "i230101@isb.nu.edu.pk"},
    {"roll": "23I-0202", "name": "Nadia Iqbal",      "email": "i230202@isb.nu.edu.pk"},
    {"roll": "23I-0303", "name": "Tariq Mehmood",    "email": "i230303@isb.nu.edu.pk"},
    {"roll": "23I-0404", "name": "Sana Rashid",      "email": "i230404@isb.nu.edu.pk"},
    {"roll": "23I-0505", "name": "Kamran Butt",      "email": "i230505@isb.nu.edu.pk"},
    {"roll": "22I-0011", "name": "Rabia Zahid",      "email": "i220011@isb.nu.edu.pk"},
    {"roll": "22I-0022", "name": "Daniyal Chaudhry", "email": "i220022@isb.nu.edu.pk"},
    {"roll": "22i-0033", "name": "Maham Farhan",     "email": "i220033@isb.nu.edu.pk"},
    {"roll": "22I-0044", "name": "Saad Mirza",       "email": "i220044@isb.nu.edu.pk"},
    {"roll": "21I-0111", "name": "Iqra Nasir",       "email": "i210111@isb.nu.edu.pk"},
    {"roll": "21I-0222", "name": "Faizan Ali",       "email": "i210222@isb.nu.edu.pk"},
    {"roll": "21I-0333", "name": "Mehreen Aslam",    "email": "i210333@isb.nu.edu.pk"},
    {"roll": "22i-1898", "name": "Sufyan Nasr",      "email": "i221898@isb.nu.edu.pk"},



    ## AI - 4C
    {"roll": "24I-0129", "name": "Ashhad Saeed",      "email": "i240129@isb.nu.edu.pk"},
    {"roll": "24I-2071", "name": "Fahad Farooq",      "email": "i242071@isb.nu.edu.pk"},
    {"roll": "24I-0002", "name": "Zamin Naqvi",       "email": "i240002@isb.nu.edu.pk"},
    {"roll": "24I-0011", "name": "Najam ul Saqib",    "email": "i240011@isb.nu.edu.pk"},
    {"roll": "24I-0023", "name": "Zohair Ahmed",      "email": "i240023@isb.nu.edu.pk"},
    {"roll": "24I-0115", "name": "Muzammil Yaseen",   "email": "i240115@isb.nu.edu.pk"},
    {"roll": "24I-0109", "name": "Tawasal Sherazi",   "email": "i240109@isb.nu.edu.pk"},
    {"roll": "24I-2527", "name": "Ali Riaz",          "email": "i2402527@isb.nu.edu.pk"},
    {"roll": "24I-0089", "name": "Hamza Sardar",      "email": "i240089@isb.nu.edu.pk"},
    {"roll": "24I-6516", "name": "Afaq Ahsan",        "email": "i246516@isb.nu.edu.pk"},
    {"roll": "24I-2536", "name": "Muhammad Ahmed",    "email": "i242536@isb.nu.edu.pk"},
    {"roll": "24I-0049", "name": "Ahmad Ranjha",      "email": "i240049@isb.nu.edu.pk"},
    {"roll": "24I-0002", "name": "Zamin Naqvi",       "email": "i240002@isb.nu.edu.pk"},
    {"roll": "24i-2585", "name": "Noah Faraz",        "email": "i242585@isb.nu.edu.pk"},
    {"roll": "24I-0031", "name": "Musa Javed",        "email": "i240031@isb.nu.edu.pk"},
    {"roll": "24I-0030", "name": "Ummamah Bilal",      "email": "i240030@isb.nu.edu.pk"},
    {"roll": "24I-0038", "name": "Musa Mahmood",       "email": "i240038@isb.nu.edu.pk"},
    {"roll": "24I-0039", "name": "Hamna Daud",         "email": "i240039@isb.nu.edu.pk"},
    {"roll": "24I-0047", "name": "Hassan Ali",         "email": "i240047@isb.nu.edu.pk"},
    {"roll": "24I-0058", "name": "Muhammad Saad",      "email": "i240058@isb.nu.edu.pk"},
    {"roll": "24I-0062", "name": "Abdul Moiz",         "email": "i240062@isb.nu.edu.pk"},
    {"roll": "24I-0064", "name": "Sikandar Javed",     "email": "i240064@isb.nu.edu.pk"},
    {"roll": "24I-0094", "name": "Diya Hurmat",        "email": "i240094@isb.nu.edu.pk"},
    {"roll": "24I-0097", "name": "Ayna Khan",          "email": "i240097@isb.nu.edu.pk"},
    {"roll": "24I-0101", "name": "Hanzala Kareem",     "email": "i240101@isb.nu.edu.pk"},
    {"roll": "24I-0109", "name": "Tawasal Mahdi",      "email": "i240109@isb.nu.edu.pk"},
    {"roll": "24I-0112", "name": "Ritaj Suleman",      "email": "i240112@isb.nu.edu.pk"},
    {"roll": "24I-0115", "name": "Muzzammil Yasin",    "email": "i240115@isb.nu.edu.pk"},
    {"roll": "24I-2025", "name": "Malaika",            "email": "i242025@isb.nu.edu.pk"},
    {"roll": "24I-2081", "name": "Hajira Gul",         "email": "i242081@isb.nu.edu.pk"},
    {"roll": "24I-2506", "name": "Munhim Ashraf",      "email": "i242506@isb.nu.edu.pk"},
    {"roll": "24I-2545", "name": "Umair Ahmad",        "email": "i242545@isb.nu.edu.pk"},
    {"roll": "24I-3139", "name": "Afnan Qammar",       "email": "i243139@isb.nu.edu.pk"},
    {"roll": "24I-6078", "name": "Muhammad Huzaifa",   "email": "i246078@isb.nu.edu.pk"},

    {"roll": "24I-6552", "name": "Muhammad Shafay",    "email": "i246552@isb.nu.edu.pk"},
    {"roll": "24I-6078", "name": "Muhammad Huzaifa",   "email": "i246078@isb.nu.edu.pk"},
    {"roll": "24I-2134", "name": "Musawir Altaf",      "email": "i242134@isb.nu.edu.pk"},
    {"roll": "24I-6570", "name": "Jawad Ahmed",        "email": "i246570@isb.nu.edu.pk"},



]


def roll_number_to_email(roll):
    """22i-1898 → i221898@isb.nu.edu.pk"""
    roll = roll.strip().lower()
    match = re.search(r"(\d{2})([a-z])-?(\d{4})", roll)
    if not match:
        return None
    return f"{match.group(2)}{match.group(1)}{match.group(3)}@isb.nu.edu.pk"


def lookup_student_by_roll(roll_number):
    roll_clean = roll_number.strip().lower().replace(" ", "")
    for student in STUDENT_DB:
        if student["roll"].strip().lower().replace(" ", "") == roll_clean:
            return student
    return None


def extract_roll_from_text(text):
    """
    Parse OCR text to find a FAST NUCES roll number.
    Handles OCR confusion: I → 1, l, L, |
    """
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Normalise: 22[1/l/L] → 22I
        normalised = re.sub(r"(\d{2})[1lL\|](-\d{4})", r"\1I\2", line)
        normalised = re.sub(r"(\d{2})[1lL\|](\d{4})",  r"\1I-\2", normalised)
        match = re.search(r"(\d{2}[iI]-\d{4})", normalised, re.IGNORECASE)
        if match:
            roll = re.sub(r"(\d{2})[Ii]", lambda m: m.group(0)[:-1] + "i", match.group(1))
            print(f"Roll extracted: {roll}  (line: {repr(line)})")
            return roll
    return None


def ocr_scan_id_card(image_path):
    """
    Multi-pass OCR scan for FAST NUCES ID cards.
    Returns (roll_string_or_None, student_dict_or_None)
    """
    try:
        img = Image.open(image_path)
        w, h = img.size
        print(f"\nScanning: {w}x{h}")

        # Ensure minimum width for OCR accuracy
        if w < 1200:
            scale = 1200 / w
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
            w, h = img.size

        arr = np.array(img)

        # Pass 1: standard greyscale
        grey_big = img.convert("L").resize((w * 2, h * 2), Image.LANCZOS)
        text1 = pytesseract.image_to_string(grey_big, config="--psm 6 --oem 3")
        print(f"Pass 1:\n{text1}")
        roll = extract_roll_from_text(text1)
        if roll:
            return roll, lookup_student_by_roll(roll)

        # Pass 2+: G-channel adaptive threshold
        # Roll number = dark navy text on dark green bg → isolate with G channel
        sources = [
            ("full",      arr),
            ("bottom30%", arr[int(h * 0.70):, :, :]),
            ("bottom20%", arr[int(h * 0.80):, :, :]),
        ]

        for source_name, source_arr in sources:
            g = source_arr[:, :, 1].astype(float)
            mean_g = g.mean()

            for factor in [0.50, 0.55, 0.60, 0.65, 0.70, 0.75]:
                thresh = mean_g * factor
                mask = np.where(g < thresh, 0, 255).astype(np.uint8)
                mh, mw = mask.shape
                scale_up = max(4000, mw) / mw
                big = Image.fromarray(mask).resize(
                    (int(mw * scale_up), int(mh * scale_up)), Image.NEAREST
                )
                for cfg in ["--psm 6 --oem 3", "--psm 11 --oem 3"]:
                    text = pytesseract.image_to_string(big, config=cfg)
                    roll = extract_roll_from_text(text)
                    if roll:
                        print(f"Found in {source_name}, factor={factor}")
                        return roll, lookup_student_by_roll(roll)

        # Pass 3: blur then threshold
        arr2 = np.array(img.filter(ImageFilter.GaussianBlur(1)))
        g2 = arr2[:, :, 1].astype(float)
        mean_g2 = g2.mean()
        for factor in [0.50, 0.55, 0.60, 0.65, 0.70]:
            thresh = mean_g2 * factor
            mask = np.where(g2 < thresh, 0, 255).astype(np.uint8)
            mh, mw = mask.shape
            big = Image.fromarray(mask).resize((mw * 4, mh * 4), Image.NEAREST)
            text = pytesseract.image_to_string(big, config="--psm 6 --oem 3")
            roll = extract_roll_from_text(text)
            if roll:
                return roll, lookup_student_by_roll(roll)

    except Exception as e:
        print(f"OCR error: {e}")
        import traceback
        traceback.print_exc()
        return None, None

    print("No roll number found.")
    return None, None


# ============================================================
# AUTH HELPERS
# ============================================================

def get_logged_in_user():
    """Retrieve the current user from Supabase or session."""
    user_id = session.get("user_id")
    if not user_id:
        return None

    client = get_supabase_client()
    if client:
        try:
            resp = client.table("users").select("*").eq("id", user_id).execute()
            if resp.data:
                return _user_row_to_dict(resp.data[0])
        except Exception as e:
            print(f"Supabase get_logged_in_user failed: {e}")

    # Fallback to local
    data = _load_local_data()
    for user in data["users"]:
        if user["id"] == user_id:
            return user
    return None


def require_admin(f):
    """Decorator — redirects non-admins away from admin pages"""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_logged_in_user()
        if not user or not user.get("is_admin"):
            flash("Admin access required.", "error")
            return redirect(url_for("home"))
        return f(*args, **kwargs)
    return decorated


# ============================================================
# ROUTES — PUBLIC
# ============================================================

@app.route("/")
def home():
    run_archiving()   # archive items older than 60 days on every home page visit
    data         = load_data()
    ensure_data_defaults(data)
    current_user = get_logged_in_user()
    recent_items = list(reversed(data["items"][-3:]))
    total        = len(data["items"])
    return render_template("home.html",
        current_user=current_user,
        recent_items=recent_items,
        total=total
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if get_logged_in_user():
        return redirect(url_for("home"))

    now_ts = datetime.utcnow().timestamp()
    lockout_until = float(session.get("login_lockout_until", 0) or 0)
    failed_attempts = int(session.get("failed_login_attempts", 0) or 0)

    if lockout_until and now_ts >= lockout_until:
        session.pop("login_lockout_until", None)
        session.pop("failed_login_attempts", None)
        lockout_until = 0
        failed_attempts = 0

    lockout_remaining = int(max(0, lockout_until - now_ts)) if lockout_until else 0

    if request.method == "POST":
        if lockout_remaining > 0:
            flash("Too many failed attempts. Please wait 2 minutes before trying again.", "error")
            return render_template("login.html", lockout_remaining=lockout_remaining)

        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        if not email or not password:
            flash("Please fill in all fields.", "error")
            return render_template("login.html", lockout_remaining=lockout_remaining)

        # Optimized lookup: query only for this specific email
        client = get_supabase_client()
        matched = None
        
        if client:
            try:
                resp = client.table("users").select("*").eq("email", email).execute()
                if resp.data:
                    user = resp.data[0]
                    if user["password"] == password:
                        matched = _user_row_to_dict(user)
            except Exception as e:
                print(f"Supabase login lookup failed: {e}")

        # Fallback to local lookup if not found in Supabase or Supabase failed
        if not matched:
            data = _load_local_data()
            for user in data["users"]:
                if user["email"].lower() == email and user["password"] == password:
                    matched = user
                    break

        if matched:
            session.pop("failed_login_attempts", None)
            session.pop("login_lockout_until", None)
            session["user_id"] = matched["id"]
            flash(f"Welcome back, {matched['name']}!", "success")
            if matched.get("is_admin"):
                return redirect(url_for("admin_panel"))
            return redirect(url_for("home"))
        else:
            failed_attempts += 1
            session["failed_login_attempts"] = failed_attempts
            if failed_attempts >= FAILED_LOGIN_LIMIT:
                lockout_until = datetime.utcnow().timestamp() + LOGIN_LOCKOUT_SECONDS
                session["login_lockout_until"] = lockout_until
                session["failed_login_attempts"] = 0
                lockout_remaining = LOGIN_LOCKOUT_SECONDS
                flash("Too many failed attempts. Login is disabled for 2 minutes.", "error")
            else:
                flash("Incorrect email or password.", "error")

    return render_template("login.html", lockout_remaining=lockout_remaining)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if get_logged_in_user():
        return redirect(url_for("home"))

    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        confirm  = request.form.get("confirm_password", "").strip()

        if not name or not email or not password or not confirm:
            flash("Please fill in all fields.", "error")
            return render_template("signup.html")

        name_without_spaces = re.sub(r"\s+", "", name)
        if len(name_without_spaces) < 5 or len(name_without_spaces) > 15:
            flash("Name must be 5 to 15 characters long (spaces are allowed and not counted).", "error")
            return render_template("signup.html")

        # Strict university email validation: exactly 6 digits after 'i' (e.g. i240001@isb.nu.edu.pk)
        if not re.match(r"^i\d{6}@(isb\.)?nu\.edu\.pk$", email):
            flash("Please use a valid FAST NUCES student email (e.g. i240001@isb.nu.edu.pk). No hyphens allowed.", "error")
            return render_template("signup.html")

        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("signup.html")

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("signup.html")

        # Check for existing user via targeted query
        client = get_supabase_client()
        exists = False
        
        if client:
            try:
                resp = client.table("users").select("id").eq("email", email).execute()
                if resp.data:
                    exists = True
            except Exception as e:
                print(f"Supabase signup check failed: {e}")

        if not exists:
            # Fallback check local
            data = _load_local_data()
            for user in data["users"]:
                if user["email"].lower() == email:
                    exists = True
                    break

        if exists:
            flash("An account with this email already exists.", "error")
            return render_template("signup.html")

        new_user = {
            "id":       "u_" + str(uuid.uuid4())[:8],
            "name":     name,
            "email":    email,
            "password": password,
            "is_admin": False,
            "points":   0
        }
        save_user(new_user)

        session["user_id"] = new_user["id"]
        flash(f"Account created! Welcome, {name}!", "success")
        return redirect(url_for("home"))

    return render_template("signup.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("home"))


@app.route("/submissions")
def submissions():
    run_archiving()   # archive items older than 60 days
    current_user = get_logged_in_user()
    data         = load_data()
    ensure_data_defaults(data)

    q = request.args.get("q", "").strip().lower()
    category = request.args.get("category", "").strip()
    item_status = request.args.get("status", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    submitted_to = request.args.get("submitted_to", "").strip()

    filtered = []
    for item in data["items"]:
        haystack = " ".join([
            item.get("title", ""),
            item.get("description", ""),
            item.get("category", ""),
            item.get("location", ""),
            item.get("reported_by_name", "")
        ]).lower()
        if q and q not in haystack:
            continue
        if category and item.get("category") != category:
            continue
        if item_status and item.get("status") != item_status:
            continue
        if submitted_to and item.get("submitted_to", "self") != submitted_to:
            continue

        submitted_day = item.get("date_submitted", "")[:10]
        if date_from and submitted_day and submitted_day < date_from:
            continue
        if date_to and submitted_day and submitted_day > date_to:
            continue

        filtered.append(item)

    items = list(reversed(filtered))
    categories = sorted({i.get("category", "") for i in data["items"] if i.get("category")})
    return render_template("submissions.html",
        current_user=current_user,
        items=items,
        categories=categories,
        departments=DEPARTMENTS,
        search_filters={
            "q": q,
            "category": category,
            "status": item_status,
            "date_from": date_from,
            "date_to": date_to,
            "submitted_to": submitted_to
        }
    )


@app.route("/submissions/<item_id>", methods=["GET", "POST"])
def submission_detail(item_id):
    current_user = get_logged_in_user()
    data = load_data()
    ensure_data_defaults(data)

    target = None
    for item in data["items"]:
        if item["id"] == item_id:
            target = item
            break

    if not target:
        flash("Submission not found.", "error")
        return redirect(url_for("submissions"))

    if request.method == "POST":
        if not current_user:
            flash("Please log in to request a claim.", "error")
            return redirect(url_for("login"))

        claim_description = request.form.get("claim_description", "").strip()
        if not claim_description:
            flash("Please provide claim details for verification.", "error")
            return redirect(url_for("submission_detail", item_id=item_id))

        if target.get("claim_status") == "pending":
            flash("A claim is already pending admin review.", "info")
            return redirect(url_for("submission_detail", item_id=item_id))

        target["claim_status"] = "pending"
        target["claim_requested_by"] = current_user["name"]
        target["claim_requested_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        target["claim_description"] = claim_description
        target["claim_reviewed_by"] = ""
        target["claim_reviewed_at"] = ""
        target["claim_review_notes"] = ""
        save_item(target)
        flash("Claim request submitted. Admin will verify your details.", "success")
        return redirect(url_for("submission_detail", item_id=item_id))

    return render_template("submission_detail.html",
        current_user=current_user,
        item=target
    )


# ============================================================
# ROUTE — REPORT ITEM (with email confirm flow)
# ============================================================

@app.route("/report", methods=["GET", "POST"])
def report():
    current_user = get_logged_in_user()
    if not current_user:
        flash("Please log in to report an item.", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        title             = request.form.get("title", "").strip()
        category          = request.form.get("category", "").strip()
        location          = request.form.get("location", "").strip()
        date_found        = request.form.get("date_found", "").strip()
        description       = request.form.get("description", "").strip()
        status            = request.form.get("status", "found").strip()
        submitted_to      = request.form.get("submitted_to", "self").strip()
        submitted_department = request.form.get("submitted_department", "").strip()
        holder_contact    = request.form.get("holder_contact", "").strip()
        scanned_roll      = request.form.get("scanned_roll", "").strip()
        scanned_email     = request.form.get("scanned_email", "").strip()
        scanned_name      = request.form.get("scanned_name", "").strip()
        uploaded_filename = request.form.get("uploaded_filename", "").strip()
        # This is set to "yes" / "no" by the confirmation UI in the browser
        send_email_choice = request.form.get("send_email_choice", "").strip()

        if not title or not category or not location or not description:
            flash("Please fill in all required fields.", "error")
            return render_template("report.html", current_user=current_user, departments=DEPARTMENTS)

        if status == "found":
            if submitted_to == "department":
                if submitted_department not in DEPARTMENTS:
                    flash("Please choose a valid department for submission.", "error")
                    return render_template("report.html", current_user=current_user, departments=DEPARTMENTS)
                holder_contact = ""
            else:
                submitted_to = "self"
                submitted_department = ""
                holder_contact = ""

        # Handle image
        image_filename = uploaded_filename or None
        if not image_filename:
            file = request.files.get("image")
            if file and file.filename:
                saved = save_uploaded_image(file)
                if saved == "ERROR_FILE_TOO_LARGE":
                    flash(FILE_SIZE_ERROR_TEXT, "error")
                    return render_template("report.html", current_user=current_user, departments=DEPARTMENTS)
                if isinstance(saved, dict):
                    image_filename = saved.get("stored")
                else:
                    image_filename = None

        # Save item
        new_item = {
            "id":                "item_" + str(uuid.uuid4())[:8],
            "title":             title,
            "category":          category,
            "location":          location,
            "date_found":        date_found,
            "description":       description,
            "status":            status,
            "image":             image_filename,
            "reported_by_id":    current_user["id"],
            "reported_by_name":  current_user["name"],
            "reported_by_email": current_user["email"],
            "date_submitted":    datetime.now().strftime("%Y-%m-%d %H:%M"),
            "submitted_to":      submitted_to,
            "submitted_department": submitted_department,
            "holder_contact":    holder_contact,
            "department_verification_status": "pending" if (status == "found" and submitted_to == "department") else "not_required",
            "department_verified_by": "",
            "department_verified_at": "",
            "claim_status": "none",
            "claim_requested_by": "",
            "claim_requested_at": "",
            "claim_description": "",
            "claim_reviewed_by": "",
            "claim_reviewed_at": "",
            "claim_review_notes": ""
        }

        save_item(new_item)

        # ---- AWARD POINTS ----
        # Give the reporter points for submitting this report
        award_points(current_user["id"], status)

        # ---- LOST↔FOUND MATCH NOTIFICATIONS ----
        # If a FOUND item is posted, notify LOST reporters of likely matches.
        # (Uses email settings; falls back to console simulation if not configured.)
        if status == "found":
            try:
                notify_lost_reporters_of_found(new_item, max_notifications=3)
            except Exception as e:
                print(f"Match notification error (non-fatal): {e}")

        # ---- EMAIL FLOW ----
        is_id_card = (category == "ID Card") or ("id card" in title.lower())

        if status == "found" and is_id_card and scanned_email and scanned_email != "unknown":
            # User confirmed they want to send email ("yes") or declined ("no")
            if send_email_choice == "yes":
                success, mode = send_email_notification(
                    recipient_email=scanned_email,
                    recipient_name=scanned_name or "Student",
                    item_location=location,
                    reporter_name=current_user["name"],
                    submitted_to=submitted_to,
                    submitted_department=submitted_department,
                    reporter_email=current_user.get("email", "")
                )
                if success and mode == "sent":
                    flash(f"Item reported! Email sent to {scanned_email}.", "success")
                elif success and mode == "simulated":
                    flash(
                        f"Item reported! Owner identified: {scanned_name} ({scanned_email}). "
                        f"Email not sent — configure Gmail in Admin → Email Settings.",
                        "success"
                    )
                else:
                    flash(f"Item reported. Email failed to send: {mode}", "error")
            else:
                # User chose not to send email
                flash("Item reported successfully. No email was sent.", "success")
        else:
            flash("Item reported successfully!", "success")

        return redirect(url_for("submissions"))

    return render_template("report.html", current_user=current_user, departments=DEPARTMENTS)


# ============================================================
# ROUTE — AJAX: scan ID card image
# ============================================================

@app.route("/scan-id-card", methods=["POST"])
def scan_id_card():
    if "image" not in request.files:
        return jsonify({"success": False, "message": "No image received"})

    file     = request.files["image"]
    saved = save_uploaded_image(file)

    if not saved:
        return jsonify({"success": False, "message": "Invalid image file"})

    if saved == "ERROR_FILE_TOO_LARGE":
        return jsonify({"success": False, "message": FILE_SIZE_ERROR_TEXT})

    local_filename = saved.get("local") if isinstance(saved, dict) else None
    local_path     = saved.get("local_path") if isinstance(saved, dict) else None
    stored_value   = saved.get("stored") if isinstance(saved, dict) else None
    if not local_filename or not stored_value:
        return jsonify({"success": False, "message": "Invalid image file"})

    image_path = local_path or os.path.join(UPLOAD_FOLDER, local_filename)
    roll, student = ocr_scan_id_card(image_path)

    if student:
        return jsonify({
            "success":  True,
            "roll":     roll,
            "name":     student["name"],
            "email":    student["email"],
            "filename": stored_value
        })
    elif roll:
        guessed_email = roll_number_to_email(roll)
        return jsonify({
            "success":  True,
            "roll":     roll,
            "name":     "Student",
            "email":    guessed_email or "unknown",
            "filename": stored_value
        })
    else:
        return jsonify({
            "success":  False,
            "message":  "No roll number detected in image",
            "filename": stored_value
        })


@app.context_processor
def inject_template_helpers():
    def image_src(image_value):
        if not image_value:
            return ""
        value = str(image_value)
        if value.startswith("http://") or value.startswith("https://"):
            return value
        return url_for("static", filename="uploads/" + value)
    return {"image_src": image_src}


# ============================================================
# ROUTE — AJAX: send email (called from report page confirmation)
# ============================================================

@app.route("/send-notification", methods=["POST"])
def send_notification():
    """
    AJAX endpoint — called when user clicks 'Yes, Send Email'
    on the report form after OCR detects a roll number.
    """
    current_user = get_logged_in_user()
    if not current_user:
        return jsonify({"success": False, "message": "Not logged in"})

    body = request.get_json()
    if not body:
        return jsonify({"success": False, "message": "No data received"})

    recipient_email = body.get("email", "")
    recipient_name  = body.get("name", "Student")
    item_location   = body.get("location", "Campus")
    reporter_name   = current_user["name"]

    if not recipient_email:
        return jsonify({"success": False, "message": "No email address"})

    success, mode = send_email_notification(
        recipient_email=recipient_email,
        recipient_name=recipient_name,
        item_location=item_location,
        reporter_name=reporter_name
    )

    settings = load_email_settings()
    is_configured = settings.get("enabled") and settings.get("sender")

    if success and mode == "sent":
        return jsonify({
            "success": True,
            "message": f"Email sent to {recipient_email}",
            "mode":    "sent"
        })
    elif success and mode == "simulated":
        return jsonify({
            "success": True,
            "message": "Simulated (Gmail not configured). Go to Admin → Email Settings.",
            "mode":    "simulated"
        })
    else:
        return jsonify({
            "success": False,
            "message": f"Failed: {mode}"
        })


# ============================================================
# LEADERBOARD ROUTE
# ============================================================

@app.route("/leaderboard")
def leaderboard():
    """
    Shows all users ranked by their reward points.
    Highest points = top of the list.
    """
    run_archiving()
    current_user = get_logged_in_user()
    data         = load_data()

    # Build leaderboard: only non-admin users, sorted by points descending
    board = []
    for user in data["users"]:
        if user.get("is_admin"):
            continue   # admin does not appear on leaderboard
        board.append({
            "id":     user["id"],
            "name":   user["name"],
            "email":  user["email"],
            "points": user.get("points", 0)
        })

    # Sort highest points first
    board.sort(key=lambda u: u["points"], reverse=True)

    return render_template("Leaderboard.html",
        current_user=current_user,
        board=board
    )


# ============================================================
# ARCHIVE ROUTE — view all archived items
# ============================================================

@app.route("/archive")
def archive():
    """
    Shows items that have been automatically archived after 60 days.
    """
    run_archiving()
    current_user = get_logged_in_user()
    data         = load_data()

    archived_items = [i for i in data["items"] if i["status"] == "archived"]
    archived_items = list(reversed(archived_items))

    return render_template("Archive.html",
        current_user=current_user,
        items=archived_items
    )


# ============================================================
# ADMIN ROUTES
# ============================================================

@app.route("/admin")
@require_admin
def admin_panel():
    """Admin dashboard — overview of everything"""
    current_user = get_logged_in_user()
    data         = load_data()
    ensure_data_defaults(data)
    settings     = load_email_settings()

    total_users    = len(data["users"])
    total_items    = len(data["items"])
    found_items    = sum(1 for i in data["items"] if i["status"] == "found")
    lost_items     = sum(1 for i in data["items"] if i["status"] == "lost")
    archived_items = sum(1 for i in data["items"] if i["status"] == "archived")
    pending_department_items = sum(1 for i in data["items"] if i.get("department_verification_status") == "pending")
    pending_claim_items = sum(1 for i in data["items"] if i.get("claim_status") == "pending")

    return render_template("admin.html",
        current_user=current_user,
        users=data["users"],
        items=list(reversed(data["items"])),
        total_users=total_users,
        total_items=total_items,
        found_items=found_items,
        lost_items=lost_items,
        archived_items=archived_items,
        pending_department_items=pending_department_items,
        pending_claim_items=pending_claim_items,
        departments=DEPARTMENTS,
        email_settings=settings
    )


@app.route("/admin/verify-department/<item_id>", methods=["POST"])
@require_admin
def admin_verify_department(item_id):
    current_user = get_logged_in_user()
    data = load_data()
    ensure_data_defaults(data)

    for item in data["items"]:
        if item["id"] == item_id:
            if item.get("submitted_to") != "department":
                flash("This item is not submitted to a department.", "error")
                return redirect(url_for("admin_panel"))
            item["department_verification_status"] = "verified"
            item["department_verified_by"] = current_user["name"]
            item["department_verified_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            save_item(item)
            flash(f"Department verification recorded for {item['title']}.", "success")
            return redirect(url_for("admin_panel"))

    flash("Item not found.", "error")
    return redirect(url_for("admin_panel"))


@app.route("/admin/review-claim/<item_id>", methods=["POST"])
@require_admin
def admin_review_claim(item_id):
    current_user = get_logged_in_user()
    decision = request.form.get("decision", "").strip()
    notes = request.form.get("notes", "").strip()

    if decision not in ("approved", "rejected"):
        flash("Invalid claim decision.", "error")
        return redirect(url_for("admin_panel"))

    data = load_data()
    ensure_data_defaults(data)

    for item in data["items"]:
        if item["id"] == item_id:
            if item.get("claim_status") != "pending":
                flash("No pending claim exists for this item.", "error")
                return redirect(url_for("admin_panel"))

            if item.get("submitted_to") == "self":
                flash("Self-held items are handled directly between users and cannot be admin-verified.", "info")
                return redirect(url_for("admin_panel"))

            item["claim_status"] = decision
            item["claim_reviewed_by"] = current_user["name"]
            item["claim_reviewed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            item["claim_review_notes"] = notes

            if decision == "approved":
                item["status"] = "recovered"

            save_item(item)
            flash(f"Claim {decision} for {item['title']}.", "success")
            return redirect(url_for("admin_panel"))

    flash("Item not found.", "error")
    return redirect(url_for("admin_panel"))


@app.route("/admin/delete-item/<item_id>", methods=["POST"])
@require_admin
def admin_delete_item(item_id):
    """Admin: delete any item"""
    if delete_item_by_id(item_id):
        flash("Item deleted.", "success")
    else:
        flash("Item not found.", "error")
    return redirect(url_for("admin_panel"))


@app.route("/admin/edit-item/<item_id>", methods=["GET", "POST"])
@require_admin
def admin_edit_item(item_id):
    """Admin: edit any item's details"""
    current_user = get_logged_in_user()
    data         = load_data()
    ensure_data_defaults(data)

    # Find the item
    target = None
    for item in data["items"]:
        if item["id"] == item_id:
            target = item
            break

    if not target:
        flash("Item not found.", "error")
        return redirect(url_for("admin_panel"))

    if request.method == "POST":
        target["title"]       = request.form.get("title", target["title"]).strip()
        target["category"]    = request.form.get("category", target["category"]).strip()
        target["location"]    = request.form.get("location", target["location"]).strip()
        target["description"] = request.form.get("description", target["description"]).strip()
        target["status"]      = request.form.get("status", target["status"]).strip()
        target["date_found"]  = request.form.get("date_found", target.get("date_found", "")).strip()
        target["submitted_to"] = request.form.get("submitted_to", target.get("submitted_to", "self")).strip()
        target["submitted_department"] = request.form.get("submitted_department", target.get("submitted_department", "")).strip()
        target["holder_contact"] = request.form.get("holder_contact", target.get("holder_contact", "")).strip()

        if target["submitted_to"] == "department":
            if target["submitted_department"] not in DEPARTMENTS:
                flash("Please select a valid department.", "error")
                return render_template("admin_edit_item.html", current_user=current_user, item=target, departments=DEPARTMENTS)
            target["holder_contact"] = ""
            if target.get("department_verification_status") == "not_required":
                target["department_verification_status"] = "pending"
        else:
            target["submitted_to"] = "self"
            target["submitted_department"] = ""
            # Contact numbers are not required; users contact via email.
            target["department_verification_status"] = "not_required"
            target["department_verified_by"] = ""
            target["department_verified_at"] = ""

        save_item(target)
        flash("Item updated.", "success")
        return redirect(url_for("admin_panel"))

    return render_template("admin_edit_item.html",
        current_user=current_user,
        item=target,
        departments=DEPARTMENTS
    )


@app.route("/admin/delete-user/<user_id>", methods=["POST"])
@require_admin
def admin_delete_user(user_id):
    """Admin: delete any user (cannot delete own account)"""
    current_user = get_logged_in_user()
    if user_id == current_user["id"]:
        flash("You cannot delete your own admin account.", "error")
        return redirect(url_for("admin_panel"))

    if delete_user_by_id(user_id):
        flash("User deleted.", "success")
    else:
        flash("User not found.", "error")

    return redirect(url_for("admin_panel"))


@app.route("/admin/toggle-admin/<user_id>", methods=["POST"])
@require_admin
def admin_toggle_admin(user_id):
    """Admin: grant or revoke admin access for a user"""
    current_user = get_logged_in_user()
    if user_id == current_user["id"]:
        flash("Cannot change your own admin status.", "error")
        return redirect(url_for("admin_panel"))

    data = load_data()
    for user in data["users"]:
        if user["id"] == user_id:
            user["is_admin"] = not user.get("is_admin", False)
            status = "granted" if user["is_admin"] else "revoked"
            save_user(user)
            flash(f"Admin access {status} for {user['name']}.", "success")
            break

    return redirect(url_for("admin_panel"))


@app.route("/admin/email-settings", methods=["GET", "POST"])
@require_admin
def admin_email_settings():
    """Admin: configure Gmail SMTP credentials"""
    current_user = get_logged_in_user()
    settings     = load_email_settings()

    if request.method == "POST":
        sender   = request.form.get("sender", "").strip()
        password = request.form.get("password", "").strip()
        enabled  = request.form.get("enabled") == "on"

        # Keep existing password if field left blank
        if not password:
            password = settings.get("password", "")

        settings = {
            "sender":   sender,
            "password": password,
            "enabled":  enabled
        }
        save_email_settings(settings)
        flash("Email settings saved.", "success")

        # Test the connection if enabled
        if enabled and sender and password:
            try:
                server = smtplib.SMTP("smtp.gmail.com", 587)
                server.starttls()
                server.login(sender, password)
                server.quit()
                flash("Gmail connection test passed! Emails will be sent.", "success")
            except Exception as e:
                flash(f"Gmail connection test FAILED: {e}", "error")

        return redirect(url_for("admin_email_settings"))

    return render_template("admin_email_settings.html",
        current_user=current_user,
        settings=settings
    )


@app.route("/admin/add-item", methods=["GET", "POST"])
@require_admin
def admin_add_item():
    """Admin: manually add any item"""
    current_user = get_logged_in_user()

    if request.method == "POST":
        title       = request.form.get("title", "").strip()
        category    = request.form.get("category", "").strip()
        location    = request.form.get("location", "").strip()
        description = request.form.get("description", "").strip()
        status      = request.form.get("status", "found").strip()
        date_found  = request.form.get("date_found", "").strip()
        submitted_to = request.form.get("submitted_to", "department").strip()
        submitted_department = request.form.get("submitted_department", "").strip()
        holder_contact = request.form.get("holder_contact", "").strip()

        if not title or not category or not location or not description:
            flash("Please fill in all required fields.", "error")
            return render_template("admin_add_item.html", current_user=current_user, departments=DEPARTMENTS)

        if status == "found" and submitted_to == "department" and submitted_department not in DEPARTMENTS:
            flash("Please choose a valid department.", "error")
            return render_template("admin_add_item.html", current_user=current_user, departments=DEPARTMENTS)

        # Contact numbers are not required; users contact via email.

        if submitted_to == "department":
            holder_contact = ""
        else:
            submitted_to = "self"
            submitted_department = ""

        new_item = {
            "id":                "item_" + str(uuid.uuid4())[:8],
            "title":             title,
            "category":          category,
            "location":          location,
            "date_found":        date_found,
            "description":       description,
            "status":            status,
            "image":             None,
            "reported_by_id":    current_user["id"],
            "reported_by_name":  "Admin",
            "reported_by_email": current_user["email"],
            "date_submitted":    datetime.now().strftime("%Y-%m-%d %H:%M"),
            "submitted_to":      submitted_to,
            "submitted_department": submitted_department,
            "holder_contact":    holder_contact,
            "department_verification_status": "pending" if (status == "found" and submitted_to == "department") else "not_required",
            "department_verified_by": "",
            "department_verified_at": "",
            "claim_status": "none",
            "claim_requested_by": "",
            "claim_requested_at": "",
            "claim_description": "",
            "claim_reviewed_by": "",
            "claim_reviewed_at": "",
            "claim_review_notes": ""
        }

        save_item(new_item)
        flash("Item added successfully.", "success")
        return redirect(url_for("admin_panel"))

    return render_template("admin_add_item.html", current_user=current_user, departments=DEPARTMENTS)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    setup_sample_data()

    print("")
    print("=" * 55)
    print("  Lost & Found ")
    print("  Open: http://localhost:5000")
    print("=" * 55)
    print("")
    print("  ADMIN login:")
    print("  admin@lostfound.com  /  admin123")
    print("  → Goes to /admin panel automatically")
    print("")
    print("  Student accounts (all password123):")
    print("  i240129@isb.nu.edu.pk  (Ashhad)")
    print("  i242071@isb.nu.edu.pk  (Fahad)")
    print("=" * 55)
    print("")

    app.run(debug=True, port=5000)