"""
Approval Workflow & Request Storage Manager
Stores approval requests and generated Excel files securely on disk.
Handles Admin authentication and request approval/rejection.
"""

import os
import json
import time
import uuid
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
FILES_DIR = DATA_DIR / "files"
REQUESTS_FILE = DATA_DIR / "requests.json"
CONFIG_FILE = DATA_DIR / "admin_config.json"

DEFAULT_ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
DEFAULT_ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "admin")

# Active admin session tokens {token: expire_timestamp}
ACTIVE_SESSIONS = {}


def init_storage():
    """Ensure data directories and request store exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    if not REQUESTS_FILE.exists():
        with open(REQUESTS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2)
    if not CONFIG_FILE.exists():
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "username": DEFAULT_ADMIN_USER,
                "password": DEFAULT_ADMIN_PASS
            }, f, indent=2)


def get_admin_credentials():
    init_storage()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("username", DEFAULT_ADMIN_USER), data.get("password", DEFAULT_ADMIN_PASS)
    except Exception:
        return DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASS


def verify_admin_login(username, password):
    u, p = get_admin_credentials()
    if username == u and password == p:
        token = secrets.token_hex(24)
        # Session valid for 7 days
        ACTIVE_SESSIONS[token] = time.time() + (7 * 86400)
        return True, token
    return False, None


def is_valid_admin_token(token):
    if not token:
        return False
    clean_token = token.replace("Bearer ", "").strip()
    exp = ACTIVE_SESSIONS.get(clean_token)
    if exp and exp > time.time():
        return True
    return False


def load_all_requests():
    init_storage()
    try:
        with open(REQUESTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_all_requests(req_list):
    init_storage()
    with open(REQUESTS_FILE, "w", encoding="utf-8") as f:
        json.dump(req_list, f, indent=2, ensure_ascii=False)


def create_approval_request(
    user_name,
    original_filename,
    target_date,
    shift_start,
    shift_end,
    lunch_start,
    lunch_end,
    break2_enabled,
    break2_start,
    break2_end,
    stats,
    excel_bytes
):
    """
    Creates an approval request in PENDING state and writes the generated
    Excel file to disk.
    """
    init_storage()
    req_id = "REQ-" + time.strftime("%Y%m%d-") + secrets.token_hex(3).upper()

    # Save excel file
    file_path = FILES_DIR / f"{req_id}.xlsx"
    with open(file_path, "wb") as f:
        f.write(excel_bytes)

    req_data = {
        "id": req_id,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "user_name": str(user_name or "Anonymous").strip(),
        "filename": original_filename,
        "target_date": target_date,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "lunch_start": lunch_start,
        "lunch_end": lunch_end,
        "break2_enabled": bool(break2_enabled),
        "break2_start": break2_start if break2_enabled else None,
        "break2_end": break2_end if break2_enabled else None,
        "num_rows": stats.get("num_rows", 0),
        "working_hours": stats.get("working_hours", 0),
        "avg_minutes_per_log": stats.get("avg_minutes_per_log", 0),
        "first_timestamp": stats.get("first_timestamp"),
        "last_timestamp": stats.get("last_timestamp"),
        "status": "PENDING",  # PENDING | APPROVED | REJECTED
        "approved_at": None,
        "rejection_reason": None,
        "preview_comparisons": stats.get("preview_comparisons", [])[:50]
    }

    requests = load_all_requests()
    requests.insert(0, req_data)
    save_all_requests(requests)
    return req_data


def get_request_by_id(req_id):
    requests = load_all_requests()
    for r in requests:
        if r["id"] == req_id:
            return r
    return None


def approve_request(req_id):
    requests = load_all_requests()
    for r in requests:
        if r["id"] == req_id:
            r["status"] = "APPROVED"
            r["approved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            save_all_requests(requests)
            return True, r
    return False, None


def reject_request(req_id, reason="Timing mismatch or excessive break taken"):
    requests = load_all_requests()
    for r in requests:
        if r["id"] == req_id:
            r["status"] = "REJECTED"
            r["rejection_reason"] = reason or "Rejected by Admin"
            save_all_requests(requests)
            return True, r
    return False, None


def get_request_excel_path(req_id):
    file_path = FILES_DIR / f"{req_id}.xlsx"
    if file_path.exists():
        return file_path
    return None
