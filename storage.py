"""
Approval Workflow & Request Storage Manager
Handles:
1. Request storage & Excel file persistence.
2. Master Admin (Kenil/Canon) authentication.
3. Multi-Admin credential management (Add, Edit, Delete Admin accounts).
4. Date-wise filtering for requests.
"""

import os
import json
import time
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
FILES_DIR = DATA_DIR / "files"
REQUESTS_FILE = DATA_DIR / "requests.json"
CONFIG_FILE = DATA_DIR / "admin_config.json"

# Master Admin Credentials (Kenil / Canon)
MASTER_USERNAMES = ["kenil", "canon", "shahkenil01"]
MASTER_PASSWORDS = ["kenil", "canon"]

# Active session tokens {token: {"type": "admin"|"master", "user": "...", "expires": timestamp}}
ACTIVE_SESSIONS = {}


def init_storage():
    """Ensure data directories and request store exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FILES_DIR.mkdir(parents=True, exist_ok=True)

    if not REQUESTS_FILE.exists():
        with open(REQUESTS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2)

    # Initialize or migrate admin_config.json
    should_write_config = False
    config_data = {}
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config_data = json.load(f)
        except Exception:
            config_data = {}

    # Ensure 'admins' list exists
    if "admins" not in config_data or not isinstance(config_data.get("admins"), list) or len(config_data.get("admins")) == 0:
        config_data["admins"] = [
            {
                "id": "adm_default",
                "username": "automationpaglu",
                "password": "automationpaglu",
                "name": "Automation Paglu (Admin)",
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
        ]
        should_write_config = True

    # Ensure 'master' block exists
    if "master" not in config_data:
        config_data["master"] = {
            "usernames": MASTER_USERNAMES,
            "passwords": MASTER_PASSWORDS
        }
        should_write_config = True

    if should_write_config:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)


def get_config():
    init_storage()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"admins": [], "master": {"usernames": MASTER_USERNAMES, "passwords": MASTER_PASSWORDS}}


def save_config(cfg):
    init_storage()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# =============================================================================
# AUTHENTICATION
# =============================================================================

def verify_admin_login(username, password):
    """Verifies credentials for normal admin dashboard."""
    init_storage()
    u_clean = str(username or "").strip().lower()
    p_clean = str(password or "").strip()

    cfg = get_config()
    admins = cfg.get("admins", [])

    for adm in admins:
        if adm.get("username", "").strip().lower() == u_clean and adm.get("password", "") == p_clean:
            token = secrets.token_hex(24)
            ACTIVE_SESSIONS[token] = {
                "type": "admin",
                "username": adm.get("username"),
                "name": adm.get("name"),
                "expires": time.time() + (7 * 86400)
            }
            return True, token, adm

    # Fallback: Master Admin can also log in as normal Admin
    is_master, m_token = verify_master_login(username, password)
    if is_master:
        return True, m_token, {"username": "Master Admin (Kenil)", "name": "Super Admin"}

    return False, None, None


def verify_master_login(username, password):
    """Verifies Master Admin (Kenil/Canon) credentials."""
    u_clean = str(username or "").strip().lower()
    p_clean = str(password or "").strip().lower()

    if u_clean in MASTER_USERNAMES and p_clean in MASTER_PASSWORDS:
        token = secrets.token_hex(24)
        ACTIVE_SESSIONS[token] = {
            "type": "master",
            "username": "kenil",
            "name": "Master Admin (Kenil)",
            "expires": time.time() + (7 * 86400)
        }
        return True, token
    return False, None


def is_valid_admin_token(token):
    if not token:
        return False
    clean = token.replace("Bearer ", "").strip()
    session = ACTIVE_SESSIONS.get(clean)
    if session and session.get("expires", 0) > time.time():
        return True
    return False


def is_valid_master_token(token):
    if not token:
        return False
    clean = token.replace("Bearer ", "").strip()
    session = ACTIVE_SESSIONS.get(clean)
    if session and session.get("type") == "master" and session.get("expires", 0) > time.time():
        return True
    return False


# =============================================================================
# ADMIN CREDENTIALS MANAGEMENT (MASTER ONLY)
# =============================================================================

def list_all_admins():
    cfg = get_config()
    return cfg.get("admins", [])


def add_admin_account(username, password, name=""):
    u_clean = str(username or "").strip()
    p_clean = str(password or "").strip()
    if not u_clean or not p_clean:
        raise ValueError("Username and Password are required.")

    cfg = get_config()
    admins = cfg.get("admins", [])

    # Check if username already exists
    for adm in admins:
        if adm.get("username", "").strip().lower() == u_clean.lower():
            raise ValueError(f"Admin username '{u_clean}' already exists.")

    new_adm = {
        "id": "adm_" + secrets.token_hex(4),
        "username": u_clean,
        "password": p_clean,
        "name": str(name or u_clean).strip(),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    admins.append(new_adm)
    cfg["admins"] = admins
    save_config(cfg)
    return new_adm


def update_admin_account(admin_id, username, password, name=""):
    u_clean = str(username or "").strip()
    p_clean = str(password or "").strip()
    if not u_clean or not p_clean:
        raise ValueError("Username and Password are required.")

    cfg = get_config()
    admins = cfg.get("admins", [])

    found = None
    for adm in admins:
        if adm["id"] == admin_id:
            found = adm
            break

    if not found:
        raise ValueError("Admin account not found.")

    # Check uniqueness of username against other admins
    for adm in admins:
        if adm["id"] != admin_id and adm.get("username", "").strip().lower() == u_clean.lower():
            raise ValueError(f"Admin username '{u_clean}' is already in use by another account.")

    found["username"] = u_clean
    found["password"] = p_clean
    if name:
        found["name"] = str(name).strip()
    found["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    cfg["admins"] = admins
    save_config(cfg)
    return found


def delete_admin_account(admin_id):
    cfg = get_config()
    admins = cfg.get("admins", [])

    new_admins = [a for a in admins if a["id"] != admin_id]
    if len(new_admins) == len(admins):
        raise ValueError("Admin account not found.")

    cfg["admins"] = new_admins
    save_config(cfg)
    return True


# =============================================================================
# REQUESTS PERSISTENCE & DATE FILTERING
# =============================================================================

def load_all_requests(date_filter=None):
    """
    Loads all requests, optionally filtered by date (e.g. '2026-11-25').
    """
    init_storage()
    try:
        with open(REQUESTS_FILE, "r", encoding="utf-8") as f:
            all_reqs = json.load(f)
    except Exception:
        all_reqs = []

    if not date_filter or date_filter.strip().lower() in ("all", ""):
        return all_reqs

    df = date_filter.strip()
    filtered = []
    for r in all_reqs:
        # Match target_date or created_at prefix
        t_date = str(r.get("target_date") or "").strip()
        c_at = str(r.get("created_at") or "").strip()
        if t_date == df or c_at.startswith(df):
            filtered.append(r)
    return filtered


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
    init_storage()
    req_id = "REQ-" + time.strftime("%Y%m%d-") + secrets.token_hex(3).upper()

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
        "status": "PENDING",
        "approved_at": None,
        "rejection_reason": None,
        "preview_comparisons": stats.get("preview_comparisons", [])[:50]
    }

    requests = load_all_requests(date_filter=None)
    requests.insert(0, req_data)
    save_all_requests(requests)
    return req_data


def get_request_by_id(req_id):
    requests = load_all_requests(date_filter=None)
    for r in requests:
        if r["id"] == req_id:
            return r
    return None


def approve_request(req_id):
    requests = load_all_requests(date_filter=None)
    for r in requests:
        if r["id"] == req_id:
            r["status"] = "APPROVED"
            r["approved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            save_all_requests(requests)
            return True, r
    return False, None


def reject_request(req_id, reason="Timing mismatch or excessive break taken"):
    requests = load_all_requests(date_filter=None)
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
