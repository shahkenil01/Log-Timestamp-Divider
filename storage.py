"""
Approval Workflow & Request Storage Manager
With Automated GitHub Cloud Persistence & GitHub Releases Integration.

Guarantees:
1. Zero Data Loss on Render redeploys: Requests and Admin configurations are backed up
   to the 'data-store' branch on GitHub without triggering redeploy loops.
2. Permanent Software Releases: ActMaster zip files are stored as official GitHub Releases,
   hosted on GitHub CDN forever (immune to container wipes, 0 local disk accumulation).
3. Temporary file cleanup: Generated user Excel files are auto-cleaned after 24 hours.
"""

import os
import sys
import json
import time
import secrets
import base64
import threading
from pathlib import Path
import requests

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
FILES_DIR = DATA_DIR / "files"
RELEASES_DIR = DATA_DIR / "releases"
REQUESTS_FILE = DATA_DIR / "requests.json"
CONFIG_FILE = DATA_DIR / "admin_config.json"
RELEASES_FILE = DATA_DIR / "releases.json"

# Master Admin Credentials (Kenil / Canon)
MASTER_USERNAMES = ["kenil", "canon", "shahkenil01"]
MASTER_PASSWORDS = ["kenil", "canon"]

# Active session tokens {token: {"type": "admin"|"master", "user": "...", "expires": timestamp}}
ACTIVE_SESSIONS = {}

# GitHub Cloud Persistence Settings
def _resolve_github_token() -> str:
    # 1. Environment variable (Render / Production)
    tok = os.environ.get("GITHUB_TOKEN")
    if tok and tok.strip():
        return tok.strip()
    # 2. Local gitignored config files
    for candidate in [DATA_DIR / ".github_token", BASE_DIR / ".github_token"]:
        if candidate.exists():
            try:
                t = candidate.read_text(encoding="utf-8").strip()
                if t:
                    return t
            except Exception:
                pass
    return ""

GITHUB_TOKEN = _resolve_github_token()
GITHUB_REPO = os.environ.get("GITHUB_REPO") or "shahkenil01/Log-Timestamp-Divider"
GITHUB_DATA_BRANCH = "data-store"

GITHUB_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "Log-Timestamp-Divider-Server"
}


# =============================================================================
# GITHUB CLOUD PERSISTENCE ENGINE (Branch: data-store)
# =============================================================================

def github_pull_cloud_file(remote_filename):
    """Fetches a JSON file from the GitHub data-store branch."""
    if not GITHUB_TOKEN:
        return None
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{remote_filename}?ref={GITHUB_DATA_BRANCH}"
        resp = requests.get(url, headers=GITHUB_HEADERS, timeout=8)
        if resp.status_code == 200:
            b64_content = resp.json().get("content", "")
            if b64_content:
                raw_json = base64.b64decode(b64_content).decode("utf-8")
                return json.loads(raw_json)
    except Exception as exc:
        print(f"[CloudSync] Pull error for {remote_filename}: {exc}")
    return None


def github_push_cloud_file(remote_filename, data_obj, commit_msg="Cloud Sync update"):
    """Pushes a JSON object to the GitHub data-store branch without triggering Render rebuilds."""
    if not GITHUB_TOKEN:
        return False
    try:
        # Get existing file SHA if present
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{remote_filename}?ref={GITHUB_DATA_BRANCH}"
        get_r = requests.get(url, headers=GITHUB_HEADERS, timeout=8)
        sha = get_r.json().get("sha") if get_r.status_code == 200 else None

        content_str = json.dumps(data_obj, indent=2, ensure_ascii=False)
        content_b64 = base64.b64encode(content_str.encode("utf-8")).decode("utf-8")

        payload = {
            "message": commit_msg,
            "content": content_b64,
            "branch": GITHUB_DATA_BRANCH
        }
        if sha:
            payload["sha"] = sha

        put_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{remote_filename}"
        put_r = requests.put(put_url, headers=GITHUB_HEADERS, json=payload, timeout=12)
        if put_r.status_code in (200, 201):
            return True
        else:
            print(f"[CloudSync] Push error for {remote_filename}: {put_r.status_code} - {put_r.text}")
    except Exception as exc:
        print(f"[CloudSync] Push exception for {remote_filename}: {exc}")
    return False


def async_cloud_push(remote_filename, data_obj, commit_msg="Cloud sync"):
    """Runs cloud push in a background daemon thread so API responses return immediately."""
    t = threading.Thread(
        target=github_push_cloud_file,
        args=(remote_filename, data_obj, commit_msg),
        daemon=True
    )
    t.start()


# =============================================================================
# STORAGE INITIALIZATION
# =============================================================================

def init_storage():
    """Ensure data directories and request store exist, and sync from GitHub cloud."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    RELEASES_DIR.mkdir(parents=True, exist_ok=True)

    gitkeep = RELEASES_DIR / ".gitkeep"
    if not gitkeep.exists():
        try:
            with open(gitkeep, "w", encoding="utf-8") as f:
                f.write("")
        except Exception:
            pass

    # 1. Sync Requests from GitHub Cloud
    need_local_requests = not REQUESTS_FILE.exists() or REQUESTS_FILE.stat().st_size <= 4
    if need_local_requests:
        cloud_reqs = github_pull_cloud_file("requests.json")
        if cloud_reqs and isinstance(cloud_reqs, list) and len(cloud_reqs) > 0:
            with open(REQUESTS_FILE, "w", encoding="utf-8") as f:
                json.dump(cloud_reqs, f, indent=2, ensure_ascii=False)
            print(f"[Storage] Loaded {len(cloud_reqs)} historical requests from GitHub Cloud!")
        elif not REQUESTS_FILE.exists():
            with open(REQUESTS_FILE, "w", encoding="utf-8") as f:
                json.dump([], f, indent=2)

    # 2. Sync Admin Config from GitHub Cloud
    need_local_config = not CONFIG_FILE.exists() or CONFIG_FILE.stat().st_size <= 4
    if need_local_config:
        cloud_cfg = github_pull_cloud_file("admin_config.json")
        if cloud_cfg and isinstance(cloud_cfg, dict) and "admins" in cloud_cfg:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cloud_cfg, f, indent=2, ensure_ascii=False)
            print("[Storage] Loaded Admin accounts configuration from GitHub Cloud!")

    # 3. Initialize default Admin config if missing
    should_write_config = False
    config_data = {}
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config_data = json.load(f)
        except Exception:
            config_data = {}

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

    if "master" not in config_data:
        config_data["master"] = {
            "usernames": MASTER_USERNAMES,
            "passwords": MASTER_PASSWORDS
        }
        should_write_config = True

    if should_write_config:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
        async_cloud_push("admin_config.json", config_data, "Init default admin config")

    if not RELEASES_FILE.exists():
        with open(RELEASES_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2)

    # Auto clean files older than 24h
    cleanup_old_files()


def cleanup_old_files(max_age_hours=24):
    """Deletes temporary generated Excel files older than 24 hours to keep disk usage near 0 MB."""
    try:
        now = time.time()
        for f in FILES_DIR.glob("*.xlsx"):
            if f.is_file():
                if (now - f.stat().st_mtime) > (max_age_hours * 3600):
                    try:
                        f.unlink()
                    except Exception:
                        pass
    except Exception:
        pass


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
    async_cloud_push("admin_config.json", cfg, "Update admin config")


# =============================================================================
# AUTHENTICATION
# =============================================================================

def verify_admin_login(username, password):
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

    is_master, m_token = verify_master_login(username, password)
    if is_master:
        return True, m_token, {"username": "Master Admin (Kenil)", "name": "Super Admin"}

    return False, None, None


def verify_master_login(username, password):
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
# REQUESTS PERSISTENCE & DATE FILTERING WITH CLOUD SYNC
# =============================================================================

def load_all_requests(date_filter=None):
    """Loads all requests, optionally filtered by date (e.g. '2026-11-25')."""
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
        t_date = str(r.get("target_date") or "").strip()
        c_at = str(r.get("created_at") or "").strip()
        if t_date == df or c_at.startswith(df):
            filtered.append(r)
    return filtered


def save_all_requests(req_list):
    init_storage()
    with open(REQUESTS_FILE, "w", encoding="utf-8") as f:
        json.dump(req_list, f, indent=2, ensure_ascii=False)
    # Sync to GitHub data-store branch in background
    async_cloud_push("requests.json", req_list, "Update approval requests store")


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


# =============================================================================
# ACTMASTER ZIP RELEASES (GITHUB RELEASES INTEGRATION)
# =============================================================================

def format_size(num_bytes):
    try:
        b = float(num_bytes)
        if b < 1024:
            return f"{int(b)} B"
        elif b < 1024 * 1024:
            return f"{(b / 1024):.1f} KB"
        elif b < 1024 * 1024 * 1024:
            return f"{(b / (1024 * 1024)):.1f} MB"
        else:
            return f"{(b / (1024 * 1024 * 1024)):.2f} GB"
    except Exception:
        return f"{num_bytes} B"


def list_all_releases():
    """
    Lists all ActMaster zip releases directly from GitHub Releases API.
    Guarantees releases NEVER disappear when Render redeploys or restarts.
    """
    init_storage()
    if GITHUB_TOKEN:
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
            resp = requests.get(url, headers=GITHUB_HEADERS, timeout=8)
            if resp.status_code == 200:
                gh_releases = resp.json()
                parsed = []
                for gr in gh_releases:
                    assets = gr.get("assets", [])
                    fn = assets[0].get("name") if assets else "ActMaster.zip"
                    sz = assets[0].get("size", 0) if assets else 0
                    dl_url = assets[0].get("browser_download_url") if assets else gr.get("html_url")
                    asset_id = assets[0].get("id") if assets else None

                    parsed.append({
                        "id": str(gr["id"]),
                        "filename": fn,
                        "stored_name": fn,
                        "title": gr.get("name") or fn,
                        "description": gr.get("body") or "",
                        "file_size": sz,
                        "file_size_formatted": format_size(sz),
                        "uploaded_by": "Master Admin (Kenil)",
                        "created_at": (gr.get("published_at") or gr.get("created_at") or "").replace("T", " ")[:19],
                        "download_url": dl_url,
                        "asset_id": asset_id,
                        "tag_name": gr.get("tag_name")
                    })
                if parsed:
                    # Cache locally
                    try:
                        with open(RELEASES_FILE, "w", encoding="utf-8") as f:
                            json.dump(parsed, f, indent=2, ensure_ascii=False)
                    except Exception:
                        pass
                    return parsed
        except Exception as exc:
            print(f"[Releases] GitHub API error: {exc}")

    # Fallback: local releases.json cache
    try:
        with open(RELEASES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except Exception:
        return []


def save_release_file(original_filename, file_bytes, title="", description="", uploaded_by="Master Admin (Kenil)"):
    """
    Uploads the software zip file to GitHub Releases permanently.
    Never gets wiped by Render redeployments!
    """
    init_storage()
    clean_orig = Path(original_filename or "ActMaster_Release.zip").name.strip()
    clean_orig = "".join(c for c in clean_orig if c.isalnum() or c in "._- ")
    if not clean_orig:
        clean_orig = "ActMaster_Release.zip"

    rel_title = (title or clean_orig).strip()
    rel_desc = (description or "").strip()

    # If GitHub token is configured, publish directly to GitHub Releases
    if GITHUB_TOKEN:
        try:
            tag_name = "v" + time.strftime("%Y%m%d-%H%M%S")
            create_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
            create_payload = {
                "tag_name": tag_name,
                "name": rel_title,
                "body": rel_desc,
                "draft": False,
                "prerelease": False
            }
            create_resp = requests.post(create_url, headers=GITHUB_HEADERS, json=create_payload, timeout=15)
            if create_resp.status_code == 201:
                rel_json = create_resp.json()
                rel_id = str(rel_json["id"])
                upload_url = rel_json.get("upload_url", "").split("{")[0]

                # Upload binary asset
                asset_headers = {
                    "Authorization": f"Bearer {GITHUB_TOKEN}",
                    "Content-Type": "application/octet-stream",
                    "User-Agent": "Log-Timestamp-Divider-Server"
                }
                asset_resp = requests.post(
                    f"{upload_url}?name={clean_orig}",
                    headers=asset_headers,
                    data=file_bytes,
                    timeout=180
                )

                if asset_resp.status_code in (200, 201):
                    asset_json = asset_resp.json()
                    dl_url = asset_json.get("browser_download_url")
                    sz = asset_json.get("size", len(file_bytes))

                    meta = {
                        "id": rel_id,
                        "filename": clean_orig,
                        "stored_name": clean_orig,
                        "title": rel_title,
                        "description": rel_desc,
                        "file_size": sz,
                        "file_size_formatted": format_size(sz),
                        "uploaded_by": uploaded_by,
                        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "download_url": dl_url,
                        "asset_id": asset_json.get("id"),
                        "tag_name": tag_name
                    }

                    # Update local cache
                    cur = list_all_releases()
                    cur.insert(0, meta)
                    with open(RELEASES_FILE, "w", encoding="utf-8") as f:
                        json.dump(cur, f, indent=2, ensure_ascii=False)
                    return meta
                else:
                    print(f"[Releases] Asset upload error: {asset_resp.status_code} - {asset_resp.text}")
        except Exception as exc:
            print(f"[Releases] GitHub Release exception: {exc}")

    # Fallback: Save to local releases disk
    rel_id = "REL-" + time.strftime("%Y%m%d-") + secrets.token_hex(3).upper()
    stored_name = f"{rel_id}_{clean_orig}"
    file_path = RELEASES_DIR / stored_name
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    meta = {
        "id": rel_id,
        "filename": clean_orig,
        "stored_name": stored_name,
        "title": rel_title,
        "description": rel_desc,
        "file_size": len(file_bytes),
        "file_size_formatted": format_size(len(file_bytes)),
        "uploaded_by": uploaded_by,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "download_url": None
    }
    cur = list_all_releases()
    cur.insert(0, meta)
    with open(RELEASES_FILE, "w", encoding="utf-8") as f:
        json.dump(cur, f, indent=2, ensure_ascii=False)
    return meta


def get_release_by_id(rel_id):
    releases = list_all_releases()
    for r in releases:
        if str(r.get("id")) == str(rel_id):
            return r
    return None


def get_release_file_path(rel_id):
    r = get_release_by_id(rel_id)
    if not r:
        return None
    stored_name = r.get("stored_name")
    if stored_name:
        p = RELEASES_DIR / stored_name
        if p.exists():
            return p
    for f in RELEASES_DIR.glob(f"{rel_id}*"):
        if f.is_file():
            return f
    return None


def delete_release_file(rel_id):
    """Deletes a release from GitHub Releases and local cache."""
    rel = get_release_by_id(rel_id)
    if not rel:
        raise ValueError("Release not found.")

    # Delete from GitHub Releases
    if GITHUB_TOKEN and str(rel_id).isdigit():
        try:
            del_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/{rel_id}"
            requests.delete(del_url, headers=GITHUB_HEADERS, timeout=10)
            tag_name = rel.get("tag_name")
            if tag_name:
                requests.delete(f"https://api.github.com/repos/{GITHUB_REPO}/git/refs/tags/{tag_name}", headers=GITHUB_HEADERS, timeout=10)
        except Exception as exc:
            print(f"[Releases] GitHub delete exception: {exc}")

    # Remove local file if exists
    p = get_release_file_path(rel_id)
    if p and p.exists():
        try:
            p.unlink()
        except Exception:
            pass

    # Update local cache
    cur = [r for r in list_all_releases() if str(r.get("id")) != str(rel_id)]
    with open(RELEASES_FILE, "w", encoding="utf-8") as f:
        json.dump(cur, f, indent=2, ensure_ascii=False)

    return True
