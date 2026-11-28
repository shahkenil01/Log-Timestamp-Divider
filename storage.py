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
import hmac
import hashlib
import json
import time
import secrets
import base64
import threading
import datetime
import re
from pathlib import Path
try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    requests = None
    HTTPAdapter = None
    Retry = None

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
FILES_DIR = DATA_DIR / "files"
RELEASES_DIR = DATA_DIR / "releases"
REQUESTS_FILE = DATA_DIR / "requests.json"
CONFIG_FILE = DATA_DIR / "admin_config.json"
RELEASES_FILE = DATA_DIR / "releases.json"

# Active session cache + thread synchronization locks
ACTIVE_SESSIONS = {}
DOWNLOAD_TOKENS = {}

_STORAGE_LOCK = threading.RLock()
_CLOUD_PUSH_LOCK = threading.Lock()
_CLOUD_INIT_DONE = False
_LAST_REQ_SYNC_TS = 0.0
_HTTP_SESSION = None


def _get_http_session():
    """Returns a reusable HTTP session with automatic retry on transient network/SSL errors."""
    global _HTTP_SESSION
    if not requests:
        return None
    if _HTTP_SESSION is None:
        sess = requests.Session()
        if Retry and HTTPAdapter:
            retry_cfg = Retry(
                total=3,
                backoff_factor=0.35,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET", "PUT", "POST", "PATCH", "DELETE"]
            )
            sess.mount("https://", HTTPAdapter(max_retries=retry_cfg))
        _HTTP_SESSION = sess
    return _HTTP_SESSION

# Indian Standard Time (IST / UTC+05:30)
IST_TIMEZONE = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

def get_current_ist_datetime() -> datetime.datetime:
    return datetime.datetime.now(IST_TIMEZONE)

def get_current_ist_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return datetime.datetime.now(IST_TIMEZONE).strftime(fmt)

def format_iso_to_ist(iso_str: str) -> str:
    """Converts UTC ISO timestamp from GitHub or server into Indian Standard Time (IST)."""
    if not iso_str:
        return get_current_ist_str()
    try:
        clean = iso_str.rstrip("Z")
        if "T" in clean:
            dt = datetime.datetime.fromisoformat(clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt.astimezone(IST_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    return iso_str.replace("T", " ")[:19]

def generate_download_token(release_id: str) -> str:
    token = secrets.token_urlsafe(24)
    DOWNLOAD_TOKENS[token] = {
        "rel_id": str(release_id),
        "expires": time.time() + 900 # 15 minutes
    }
    return token

def verify_download_token(release_id: str, token: str) -> bool:
    if not token or token not in DOWNLOAD_TOKENS:
        return False
    entry = DOWNLOAD_TOKENS[token]
    if time.time() > entry["expires"]:
        del DOWNLOAD_TOKENS[token]
        return False
    if entry["rel_id"] != str(release_id):
        return False
    return True

# GitHub Cloud Persistence Settings
def _find_env_file() -> Path:
    """Locates the .env file. Searches project root first, then common locations."""
    candidates = [
        BASE_DIR / ".env",
        Path.cwd() / ".env",
        Path.cwd() / "Log_Timestamp_Divider" / ".env"
    ]
    for ep in candidates:
        if ep.exists() and ep.is_file():
            return ep
    # Default: create in project root
    return BASE_DIR / ".env"


def read_env_file() -> dict:
    """
    Reads all key=value pairs from .env file.
    This is the SINGLE SOURCE OF TRUTH for all credentials and configuration.
    Every login attempt, API call, or config read calls this function fresh,
    so edits to .env take effect immediately without server restart.
    """
    env_path = _find_env_file()
    result = {}
    if not env_path.exists():
        return result
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    result[k] = v
    except Exception:
        pass
    return result


def write_env_file(updates: dict) -> bool:
    """
    Updates specific keys in the .env file while preserving comments and structure.
    Creates .env if it does not exist yet, and updates os.environ immediately so
    changes take effect in the running server with zero restart needed.
    """
    env_path = _find_env_file()
    lines = []
    existing_keys = set()

    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            pass

    clean_updates = {str(k).strip().upper(): str(v).strip() for k, v in updates.items() if str(k).strip()}

    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip().upper()
            if key in clean_updates:
                new_lines.append(f"{key}={clean_updates[key]}\n")
                existing_keys.add(key)
                continue
        new_lines.append(line)

    # Append any new keys that weren't already in the file
    for key, val in clean_updates.items():
        if key not in existing_keys:
            new_lines.append(f"{key}={val}\n")

    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        # Sync to running process environment immediately
        for key, val in clean_updates.items():
            os.environ[key] = val
        return True
    except Exception:
        return False


def delete_env_key(key: str) -> bool:
    """Removes a key from the .env file and running process environment."""
    clean_key = str(key or "").strip().upper()
    if not clean_key:
        return False
    env_path = _find_env_file()
    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            new_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k = stripped.split("=", 1)[0].strip().upper()
                    if k == clean_key:
                        continue
                new_lines.append(line)
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception:
            return False
    os.environ.pop(clean_key, None)
    return True


def get_env_value(key: str, default: str = "") -> str:
    """
    Gets a value from .env file FIRST (so live UI/.env edits apply immediately),
    with OS environment fallback (for cloud hosts like Render).
    """
    env_data = read_env_file()
    if key in env_data and env_data[key] != "":
        return env_data[key]
    os_val = os.environ.get(key, "").strip()
    if os_val:
        return os_val
    return default


def get_github_token() -> str:
    """Dynamically resolves GitHub/Cloud API token from .env or OS environment only."""
    tok = get_env_value("GITHUB_TOKEN", "").strip()
    if tok and not tok.startswith("your_"):
        return tok
    return ""


def get_github_repo() -> str:
    """Dynamically resolves GitHub repo (owner/repo) from .env or OS environment."""
    repo = get_env_value("GITHUB_REPO", "").strip()
    if not repo or repo == "owner/repository" or repo.startswith("your_"):
        return ""
    m = re.match(r"^(?:https?://)?(?:www\.)?github\.com/([^/\s]+)/([^/\s]+)", repo, re.IGNORECASE)
    if m:
        owner = m.group(1)
        name = m.group(2)
        if name.endswith(".git"):
            name = name[:-4]
        return f"{owner}/{name}"
    return repo.strip("/")


def get_github_data_branch() -> str:
    """Dynamically resolves GitHub cloud sync branch from .env or OS environment."""
    return get_env_value("GITHUB_DATA_BRANCH", "data-store").strip() or "data-store"


def get_github_headers() -> dict:
    """Builds authorization headers dynamically using current .env token."""
    return {
        "Authorization": f"Bearer {get_github_token()}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Log-Timestamp-Divider-Server"
    }


# =============================================================================
# GITHUB CLOUD PERSISTENCE ENGINE (LOCKED & RETRY-SAFE)
# =============================================================================

def github_pull_raw_bytes(remote_path: str):
    """Fetches raw file bytes from the configured GitHub cloud branch."""
    token = get_github_token()
    repo = get_github_repo()
    branch = get_github_data_branch()
    sess = _get_http_session()
    if not token or not repo or not sess:
        return None
    try:
        url = f"https://api.github.com/repos/{repo}/contents/{remote_path}?ref={branch}"
        resp = sess.get(url, headers=get_github_headers(), timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            b64_content = data.get("content", "")
            if b64_content:
                return base64.b64decode(b64_content)
            # Files >1MB don't include inline content; fetch via git blob API
            file_sha = data.get("sha")
            if file_sha:
                blob_r = sess.get(
                    f"https://api.github.com/repos/{repo}/git/blobs/{file_sha}",
                    headers=get_github_headers(),
                    timeout=15
                )
                if blob_r.status_code == 200:
                    b64_blob = blob_r.json().get("content", "")
                    if b64_blob:
                        return base64.b64decode(b64_blob)
    except Exception as exc:
        print(f"[CloudSync] Pull error for {remote_path}: {exc}")
    return None


def github_pull_cloud_file(remote_filename):
    """Fetches a JSON file from the configured GitHub cloud branch."""
    raw = github_pull_raw_bytes(remote_filename)
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        print(f"[CloudSync] JSON decode error for {remote_filename}: {exc}")
        return None


def github_push_raw_bytes(remote_path: str, raw_bytes: bytes, commit_msg: str = "Cloud Sync update") -> bool:
    """Pushes raw bytes safely to GitHub cloud branch with lock + 409 conflict retry."""
    token = get_github_token()
    repo = get_github_repo()
    branch = get_github_data_branch()
    sess = _get_http_session()
    if not token or not repo or not sess:
        return False

    content_b64 = base64.b64encode(raw_bytes).decode("utf-8")
    with _CLOUD_PUSH_LOCK:
        headers = get_github_headers()
        get_url = f"https://api.github.com/repos/{repo}/contents/{remote_path}?ref={branch}"
        put_url = f"https://api.github.com/repos/{repo}/contents/{remote_path}"

        for attempt in range(4):
            try:
                get_r = sess.get(get_url, headers=headers, timeout=10)
                sha = get_r.json().get("sha") if get_r.status_code == 200 else None

                payload = {
                    "message": commit_msg,
                    "content": content_b64,
                    "branch": branch
                }
                if sha:
                    payload["sha"] = sha

                put_r = sess.put(put_url, headers=headers, json=payload, timeout=15)
                if put_r.status_code in (200, 201):
                    return True
                if put_r.status_code in (409, 422):
                    time.sleep(0.4 * (attempt + 1))
                    continue
                print(f"[CloudSync] Push error for {remote_path}: {put_r.status_code} - {put_r.text[:300]}")
                return False
            except Exception as exc:
                print(f"[CloudSync] Push exception for {remote_path} (try {attempt+1}): {exc}")
                time.sleep(0.4 * (attempt + 1))
    return False


def github_push_cloud_file(remote_filename, data_obj, commit_msg="Cloud Sync update"):
    """Pushes a JSON object to the configured GitHub cloud branch without triggering rebuilds."""
    content_str = json.dumps(data_obj, indent=2, ensure_ascii=False)
    return github_push_raw_bytes(remote_filename, content_str.encode("utf-8"), commit_msg)


def async_cloud_push(remote_filename, data_obj, commit_msg="Cloud sync"):
    """Runs cloud JSON push in a background daemon thread using shared cloud lock."""
    t = threading.Thread(
        target=github_push_cloud_file,
        args=(remote_filename, data_obj, commit_msg),
        daemon=True
    )
    t.start()


def async_cloud_push_bytes(remote_path: str, raw_bytes: bytes, commit_msg: str = "Cloud file sync"):
    """Runs cloud binary push (e.g., approved Excel backup) in background using shared lock."""
    t = threading.Thread(
        target=github_push_raw_bytes,
        args=(remote_path, raw_bytes, commit_msg),
        daemon=True
    )
    t.start()


# =============================================================================
# LOSSLESS MERGE HELPERS & STORAGE INITIALIZATION
# =============================================================================

_STATUS_PRIORITY = {"PENDING": 1, "REJECTED": 2, "APPROVED": 3}


def _merge_requests_lists(local_list: list, cloud_list: list) -> list:
    """
    Combines two request lists by request ID without ever dropping historical entries.
    Resolves status conflicts cleanly (APPROVED/REJECTED overrides PENDING).
    """
    by_id = {}
    for src in (cloud_list or [], local_list or []):
        if not isinstance(src, list):
            continue
        for item in src:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("id") or "").strip()
            if not rid or rid == "REQ-INIT":
                continue
            prev = by_id.get(rid)
            if not prev:
                by_id[rid] = dict(item)
                continue

            prev_pri = _STATUS_PRIORITY.get(str(prev.get("status") or ""), 0)
            curr_pri = _STATUS_PRIORITY.get(str(item.get("status") or ""), 0)
            if curr_pri > prev_pri:
                by_id[rid] = dict(item)
            elif curr_pri == prev_pri:
                # Prefer whichever has more timestamps / approved_at populated
                prev_ts = str(prev.get("approved_at") or prev.get("created_at") or "")
                curr_ts = str(item.get("approved_at") or item.get("created_at") or "")
                if curr_ts >= prev_ts:
                    by_id[rid] = dict(item)

    merged = list(by_id.values())
    merged.sort(key=lambda r: (str(r.get("created_at") or ""), str(r.get("id") or "")), reverse=True)
    return merged


def _read_local_json_list(path: Path) -> list:
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _sync_requests_from_cloud(force: bool = False) -> list:
    """Pulls cloud requests.json and merges into local storage without data loss."""
    global _LAST_REQ_SYNC_TS
    with _STORAGE_LOCK:
        local_reqs = _read_local_json_list(REQUESTS_FILE)
        now = time.time()
        if not force and _LAST_REQ_SYNC_TS > 0 and (now - _LAST_REQ_SYNC_TS) < 20.0:
            return local_reqs

        cloud_reqs = github_pull_cloud_file("requests.json")
        if isinstance(cloud_reqs, list):
            merged = _merge_requests_lists(local_reqs, cloud_reqs)
            if merged != local_reqs or not REQUESTS_FILE.exists():
                with open(REQUESTS_FILE, "w", encoding="utf-8") as f:
                    json.dump(merged, f, indent=2, ensure_ascii=False)
            _LAST_REQ_SYNC_TS = time.time()
            return merged
        elif not REQUESTS_FILE.exists():
            with open(REQUESTS_FILE, "w", encoding="utf-8") as f:
                json.dump([], f, indent=2)
        return local_reqs


def init_storage():
    """Ensure data directories exist and ALWAYS sync cloud history on startup regardless of file size."""
    global _CLOUD_INIT_DONE
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

    if not _CLOUD_INIT_DONE:
        with _STORAGE_LOCK:
            if not _CLOUD_INIT_DONE:
                # Mark first to avoid recursive loops during initial sync
                _CLOUD_INIT_DONE = True

                # 1. Always merge Requests from GitHub Cloud on boot (even if requests.json already exists in Git)
                merged_reqs = _sync_requests_from_cloud(force=True)
                if merged_reqs:
                    print(f"[Storage] Synced {len(merged_reqs)} historical requests from GitHub Cloud!")

                # 2. Always merge Admin Config from GitHub Cloud on boot
                local_cfg = {}
                if CONFIG_FILE.exists():
                    try:
                        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                            local_cfg = json.load(f) or {}
                    except Exception:
                        local_cfg = {}
                local_admins = local_cfg.get("admins", []) if isinstance(local_cfg.get("admins"), list) else []

                cloud_cfg = github_pull_cloud_file("admin_config.json")
                if isinstance(cloud_cfg, dict) and isinstance(cloud_cfg.get("admins"), list):
                    adm_map = {a.get("id"): a for a in cloud_cfg["admins"] if isinstance(a, dict) and a.get("id")}
                    for a in local_admins:
                        if isinstance(a, dict) and a.get("id"):
                            adm_map[a["id"]] = a
                    local_admins = list(adm_map.values())
                    print(f"[Storage] Synced {len(local_admins)} admin config account(s) from GitHub Cloud!")

                clean_cfg = {"admins": local_admins}
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(clean_cfg, f, indent=2, ensure_ascii=False)

                # 3. Sync Releases Metadata from GitHub Cloud if local cache empty
                if not RELEASES_FILE.exists() or RELEASES_FILE.stat().st_size <= 4:
                    cloud_rels = github_pull_cloud_file("releases.json")
                    if cloud_rels and isinstance(cloud_rels, list):
                        with open(RELEASES_FILE, "w", encoding="utf-8") as f:
                            json.dump(cloud_rels, f, indent=2, ensure_ascii=False)
                        print(f"[Storage] Loaded {len(cloud_rels)} releases metadata from GitHub Cloud!")
                    elif not RELEASES_FILE.exists():
                        with open(RELEASES_FILE, "w", encoding="utf-8") as f:
                            json.dump([], f, indent=2)

                # Auto clean local Excel cache older than 7 days (cloud keeps full archive)
                cleanup_old_files(max_age_hours=168)


def cleanup_old_files(max_age_hours=168):
    """Deletes temporary local Excel cache files older than 7 days (cloud backup remains intact)."""
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
    with _STORAGE_LOCK:
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    data.pop("master", None)
                    return data
        except Exception:
            pass
    return {"admins": []}


def save_config(cfg):
    init_storage()
    with _STORAGE_LOCK:
        clean_cfg = dict(cfg) if isinstance(cfg, dict) else {"admins": []}
        clean_cfg.pop("master", None)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(clean_cfg, f, indent=2, ensure_ascii=False)
        github_push_cloud_file("admin_config.json", clean_cfg, "Update admin config")


# =============================================================================
# AUTHENTICATION (.env EXCLUSIVE + STATELESS HMAC SESSIONS)
# =============================================================================

def _get_session_hmac_key() -> bytes:
    """Derives session signing key dynamically from .env credentials so restarts keep sessions valid."""
    seed = "|".join([
        get_env_value("SESSION_SECRET", ""),
        get_env_value("MASTER_USERNAME", ""),
        get_env_value("MASTER_PASSWORD", ""),
        get_env_value("ADMIN_USERNAME", ""),
        get_env_value("ADMIN_PASSWORD", ""),
    ])
    return hashlib.sha256(seed.encode("utf-8")).digest()


def _issue_session_token(sess_type: str, username: str, name: str, ttl_days: int = 7) -> str:
    expires = int(time.time() + (ttl_days * 86400))
    payload_obj = {
        "t": sess_type,
        "u": str(username or ""),
        "n": str(name or ""),
        "exp": expires,
        "j": secrets.token_hex(6)
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload_obj, separators=(",", ":")).encode("utf-8")).decode("utf-8")
    sig = hmac.new(_get_session_hmac_key(), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    token = f"{payload_b64}.{sig}"
    ACTIVE_SESSIONS[token] = {"type": sess_type, "username": username, "name": name, "expires": expires}
    return token


def _verify_session_token(token: str, required_type: str = None) -> bool:
    if not token:
        return False
    clean = token.replace("Bearer ", "").strip()

    # Check signed stateless HMAC token first (survives Render container restarts)
    if "." in clean:
        try:
            payload_b64, sig = clean.split(".", 1)
            expected_sig = hmac.new(_get_session_hmac_key(), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected_sig):
                return False
            payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8"))
            if payload.get("exp", 0) <= time.time():
                return False
            if required_type and payload.get("t") != required_type:
                return False
            return True
        except Exception:
            return False

    # Legacy in-memory fallback
    session = ACTIVE_SESSIONS.get(clean)
    if session and session.get("expires", 0) > time.time():
        if required_type and session.get("type") != required_type:
            return False
        return True
    return False


def get_admin_credentials() -> tuple[str, str, str]:
    """
    Reads primary Admin Portal credentials EXCLUSIVELY from .env / environment.
    Changes in .env take effect immediately without server restart.
    """
    username = get_env_value("ADMIN_USERNAME", "").strip()
    password = get_env_value("ADMIN_PASSWORD", "").strip()
    display_name = get_env_value("ADMIN_NAME", "Shift Admin").strip() or "Shift Admin"
    return username, password, display_name


def verify_admin_login(username, password):
    init_storage()
    u_clean = str(username or "").strip().lower()
    p_clean = str(password or "").strip()

    # 1. Check primary Admin credentials from .env
    env_u, env_p, env_name = get_admin_credentials()
    if env_u and env_p and u_clean == env_u.lower() and p_clean == env_p:
        token = _issue_session_token("admin", env_u, env_name)
        return True, token, {"username": env_u, "name": env_name}

    # 2. Check optional additional sub-admins managed via Master Portal
    cfg = get_config()
    admins = cfg.get("admins", [])
    for adm in admins:
        if adm.get("username", "").strip().lower() == u_clean and adm.get("password", "") == p_clean:
            token = _issue_session_token("admin", adm.get("username"), adm.get("name"))
            return True, token, adm

    # 3. Allow Master Admin login into Admin Dashboard too
    is_master, m_token = verify_master_login(username, password)
    if is_master:
        master_name = get_env_value("MASTER_USERNAME", "Master Admin")
        master_disp = get_env_value("MASTER_DISPLAY_NAME", "Super Admin")
        return True, m_token, {"username": master_name, "name": master_disp}

    return False, None, None


def get_master_credentials() -> tuple[str, str]:
    """
    Reads Master Admin credentials EXCLUSIVELY from .env / environment.
    Zero hardcoded credentials anywhere in codebase!
    Changes in .env take effect instantly on next login — no restart needed.
    """
    username = get_env_value("MASTER_USERNAME", "").strip()
    password = get_env_value("MASTER_PASSWORD", "").strip()
    return username, password


def verify_master_login(username, password):
    u_clean = str(username or "").strip().lower()
    p_clean = str(password or "").strip()

    master_u, master_p = get_master_credentials()

    if not master_u or not master_p:
        return False, None

    if u_clean == master_u.lower() and p_clean == master_p:
        disp = get_env_value("MASTER_DISPLAY_NAME", "Master Admin")
        token = _issue_session_token("master", u_clean, disp)
        return True, token
    return False, None


def is_valid_admin_token(token):
    return _verify_session_token(token, required_type=None)


def is_valid_master_token(token):
    return _verify_session_token(token, required_type="master")


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
        "created_at": get_current_ist_str()
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
    found["updated_at"] = get_current_ist_str()

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
# REQUESTS PERSISTENCE & DATE FILTERING WITH LOSSLESS CLOUD MERGE
# =============================================================================

def load_all_requests(date_filter=None, sync_cloud: bool = False):
    """Loads all requests with cloud merge sync, optionally filtered by date (e.g. '2026-11-28')."""
    init_storage()
    all_reqs = _sync_requests_from_cloud(force=sync_cloud)

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


def save_all_requests(req_list, sync_mode: bool = True):
    """Merges with cloud and persists requests cleanly to both disk and GitHub cloud."""
    global _LAST_REQ_SYNC_TS
    init_storage()
    with _STORAGE_LOCK:
        cloud_reqs = github_pull_cloud_file("requests.json")
        merged = _merge_requests_lists(req_list, cloud_reqs if isinstance(cloud_reqs, list) else [])
        with open(REQUESTS_FILE, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
        _LAST_REQ_SYNC_TS = time.time()
        if sync_mode:
            github_push_cloud_file("requests.json", merged, "Update approval requests store")
        else:
            async_cloud_push("requests.json", merged, "Update approval requests store")


def _mutate_requests(mutator_fn, commit_msg: str):
    """
    Atomically pulls & merges latest cloud requests, applies mutator_fn(requests_list),
    saves locally, and pushes synchronously to GitHub cloud inside _STORAGE_LOCK.
    Prevents historical request data loss on Render restarts or concurrent requests.
    """
    global _LAST_REQ_SYNC_TS
    init_storage()
    with _STORAGE_LOCK:
        local_reqs = _read_local_json_list(REQUESTS_FILE)
        cloud_reqs = github_pull_cloud_file("requests.json")
        merged = _merge_requests_lists(local_reqs, cloud_reqs if isinstance(cloud_reqs, list) else [])

        result = mutator_fn(merged)
        merged.sort(key=lambda r: (str(r.get("created_at") or ""), str(r.get("id") or "")), reverse=True)

        with open(REQUESTS_FILE, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
        _LAST_REQ_SYNC_TS = time.time()

        # Push synchronously to cloud so Render restart immediately after never loses this record
        github_push_cloud_file("requests.json", merged, commit_msg)
        return result


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
    req_id = "REQ-" + get_current_ist_str("%Y%m%d-") + secrets.token_hex(3).upper()

    file_path = FILES_DIR / f"{req_id}.xlsx"
    with open(file_path, "wb") as f:
        f.write(excel_bytes)

    req_data = {
        "id": req_id,
        "created_at": get_current_ist_str(),
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

    def _insert(reqs_list):
        reqs_list.insert(0, req_data)
        return req_data

    _mutate_requests(_insert, f"Create approval request {req_id}")
    # Also back up generated Excel to cloud so Admin/User can still download after Render sleeps
    if excel_bytes:
        async_cloud_push_bytes(f"files/{req_id}.xlsx", excel_bytes, f"Backup Excel for {req_id}")
    return req_data


def get_request_by_id(req_id):
    all_requests = load_all_requests(date_filter=None, sync_cloud=False)
    for r in all_requests:
        if r.get("id") == req_id:
            return r
    # Fallback: force cloud refresh if not present locally yet
    refreshed = load_all_requests(date_filter=None, sync_cloud=True)
    for r in refreshed:
        if r.get("id") == req_id:
            return r
    return None


def approve_request(req_id):
    def _approve(reqs_list):
        for r in reqs_list:
            if r.get("id") == req_id:
                r["status"] = "APPROVED"
                r["approved_at"] = get_current_ist_str()
                return True, r
        return False, None
    return _mutate_requests(_approve, f"Approve request {req_id}")


def reject_request(req_id, reason="Timing mismatch or excessive break taken"):
    def _reject(reqs_list):
        for r in reqs_list:
            if r.get("id") == req_id:
                r["status"] = "REJECTED"
                r["rejection_reason"] = reason or "Rejected by Admin"
                return True, r
        return False, None
    return _mutate_requests(_reject, f"Reject request {req_id}")


def get_request_excel_path(req_id):
    init_storage()
    file_path = FILES_DIR / f"{req_id}.xlsx"
    if file_path.exists():
        return file_path
    # Restore from cloud backup if Render restarted or local cache expired
    cloud_bytes = github_pull_raw_bytes(f"files/{req_id}.xlsx")
    if cloud_bytes:
        try:
            with open(file_path, "wb") as f:
                f.write(cloud_bytes)
            return file_path
        except Exception:
            pass
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


def load_local_releases_cache() -> list:
    """Loads releases from local cache or initializes empty list."""
    try:
        if RELEASES_FILE.exists():
            with open(RELEASES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception:
        pass
    return []


def list_all_releases(public_view: bool = False):
    """
    Lists all ActMaster zip releases directly from GitHub Releases API + data-store releases.json.
    Guarantees releases, download URLs, and passwords NEVER disappear when Render redeploys.
    """
    init_storage()
    cached = load_local_releases_cache()
    pw_map = {str(r.get("id")): str(r.get("download_password") or "").strip() for r in cached if r.get("download_password")}

    token = get_github_token()
    repo = get_github_repo()
    if token and repo and requests:
        try:
            url = f"https://api.github.com/repos/{repo}/releases"
            resp = requests.get(url, headers=get_github_headers(), timeout=8)
            if resp.status_code == 200:
                gh_releases = resp.json()
                parsed = []
                default_uploader = get_env_value("MASTER_DISPLAY_NAME", "Master Admin")
                for gr in gh_releases:
                    assets = gr.get("assets", [])
                    fn = assets[0].get("name") if assets else "ActMaster.zip"
                    sz = assets[0].get("size", 0) if assets else 0
                    dl_url = assets[0].get("browser_download_url") if assets else gr.get("html_url")
                    asset_id = assets[0].get("id") if assets else None
                    rel_id = str(gr["id"])

                    body_raw = gr.get("body") or ""
                    clean_desc = body_raw
                    pw = pw_map.get(rel_id, "")

                    m = re.search(r"<!--\s*meta:\s*(\{.*?\})\s*-->", body_raw, re.DOTALL)
                    if m:
                        try:
                            meta_info = json.loads(m.group(1))
                            if not pw and meta_info.get("password"):
                                pw = str(meta_info.get("password")).strip()
                        except Exception:
                            pass
                        clean_desc = re.sub(r"<!--\s*meta:\s*(\{.*?\})\s*-->", "", body_raw, flags=re.DOTALL).strip()

                    # Convert GitHub UTC ISO timestamp to Indian Standard Time (IST)
                    created_ist = format_iso_to_ist(gr.get("published_at") or gr.get("created_at") or "")

                    parsed.append({
                        "id": rel_id,
                        "filename": fn,
                        "stored_name": fn,
                        "title": gr.get("name") or fn,
                        "description": clean_desc,
                        "file_size": sz,
                        "file_size_formatted": format_size(sz),
                        "uploaded_by": default_uploader,
                        "created_at": created_ist,
                        "download_url": dl_url,
                        "asset_id": asset_id,
                        "tag_name": gr.get("tag_name"),
                        "download_password": pw,
                        "has_password": bool(pw)
                    })
                if parsed:
                    # Update local cache
                    try:
                        with open(RELEASES_FILE, "w", encoding="utf-8") as f:
                            json.dump(parsed, f, indent=2, ensure_ascii=False)
                    except Exception:
                        pass
                    
                    if public_view:
                        # Mask plain password from public response for security
                        return [{**r, "download_password": ""} for r in parsed]
                    return parsed
        except Exception as exc:
            print(f"[Releases] GitHub API error: {exc}")

    # Fallback to local cache
    cached = load_local_releases_cache()
    if public_view:
        return [{**r, "download_password": ""} for r in cached]
    return cached


def save_release_file(original_filename, file_bytes, title="", description="", download_password="", uploaded_by=None):
    """
    Uploads the software zip file to GitHub Releases permanently with security password.
    Never gets wiped by Render redeployments!
    """
    init_storage()
    if not uploaded_by:
        uploaded_by = get_env_value("MASTER_DISPLAY_NAME", "Master Admin")
    clean_orig = Path(original_filename or "ActMaster_Release.zip").name.strip()
    clean_orig = "".join(c for c in clean_orig if c.isalnum() or c in "._- ")
    if not clean_orig:
        clean_orig = "ActMaster_Release.zip"

    rel_title = (title or clean_orig).strip()
    rel_desc = (description or "").strip()
    clean_pw = (download_password or "").strip()
    now_ist = get_current_ist_str()

    # If GitHub token & repo are configured, publish directly to GitHub Releases
    token = get_github_token()
    repo = get_github_repo()
    if token and repo and requests:
        try:
            tag_name = "v" + get_current_ist_str("%Y%m%d-%H%M%S")
            create_url = f"https://api.github.com/repos/{repo}/releases"

            body_with_meta = rel_desc
            if clean_pw:
                body_with_meta += f"\n\n<!-- meta: {json.dumps({'password': clean_pw})} -->"

            create_payload = {
                "tag_name": tag_name,
                "name": rel_title,
                "body": body_with_meta,
                "draft": False,
                "prerelease": False
            }
            create_resp = requests.post(create_url, headers=get_github_headers(), json=create_payload, timeout=15)
            if create_resp.status_code == 201:
                rel_json = create_resp.json()
                rel_id = str(rel_json["id"])
                upload_url = rel_json.get("upload_url", "").split("{")[0]

                import urllib.parse
                enc_name = urllib.parse.quote(clean_orig)

                # Upload binary asset
                asset_headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/octet-stream",
                    "User-Agent": "Log-Timestamp-Divider-Server"
                }
                asset_resp = requests.post(
                    f"{upload_url}?name={enc_name}",
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
                        "created_at": now_ist,
                        "download_url": dl_url,
                        "asset_id": asset_json.get("id"),
                        "tag_name": tag_name,
                        "download_password": clean_pw,
                        "has_password": bool(clean_pw)
                    }

                    # Update local cache & push to data-store branch
                    cur = [r for r in load_local_releases_cache() if str(r.get("id")) != str(rel_id)]
                    cur.insert(0, meta)
                    with open(RELEASES_FILE, "w", encoding="utf-8") as f:
                        json.dump(cur, f, indent=2, ensure_ascii=False)
                    github_push_cloud_file("releases.json", cur, f"Update releases: {rel_title}")
                    return meta
                else:
                    print(f"[Releases] Asset upload error: {asset_resp.status_code} - {asset_resp.text}")
        except Exception as exc:
            print(f"[Releases] GitHub Release exception: {exc}")

    # Fallback: Save to local releases disk
    rel_id = "REL-" + get_current_ist_str("%Y%m%d-") + secrets.token_hex(3).upper()
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
        "created_at": now_ist,
        "download_url": None,
        "download_password": clean_pw,
        "has_password": bool(clean_pw)
    }
    cur = [r for r in load_local_releases_cache() if str(r.get("id")) != str(rel_id)]
    cur.insert(0, meta)
    with open(RELEASES_FILE, "w", encoding="utf-8") as f:
        json.dump(cur, f, indent=2, ensure_ascii=False)
    async_cloud_push("releases.json", cur, f"Update releases with password: {rel_title}")
    return meta


def update_release_password(rel_id: str, new_password: str) -> bool:
    """Updates the security download password for an existing release."""
    init_storage()
    clean_pw = (new_password or "").strip()
    cur = load_local_releases_cache()
    found = None
    for r in cur:
        if str(r.get("id")) == str(rel_id):
            r["download_password"] = clean_pw
            r["has_password"] = bool(clean_pw)
            found = r
            break
    
    if not found:
        all_rels = list_all_releases(public_view=False)
        for r in all_rels:
            if str(r.get("id")) == str(rel_id):
                r["download_password"] = clean_pw
                r["has_password"] = bool(clean_pw)
                found = r
                cur.insert(0, r)
                break

    if not found:
        return False

    with open(RELEASES_FILE, "w", encoding="utf-8") as f:
        json.dump(cur, f, indent=2, ensure_ascii=False)
    async_cloud_push("releases.json", cur, f"Update password for release {rel_id}")

    # Also update GitHub release body if possible
    token = get_github_token()
    repo = get_github_repo()
    if token and repo and requests and str(rel_id).isdigit():
        try:
            headers = get_github_headers()
            rel_url = f"https://api.github.com/repos/{repo}/releases/{rel_id}"
            get_r = requests.get(rel_url, headers=headers, timeout=8)
            if get_r.status_code == 200:
                body = get_r.json().get("body") or ""
                clean_body = re.sub(r"<!--\s*meta:\s*(\{.*?\})\s*-->", "", body, flags=re.DOTALL).strip()
                if clean_pw:
                    clean_body += f"\n\n<!-- meta: {json.dumps({'password': clean_pw})} -->"
                requests.patch(rel_url, headers=headers, json={"body": clean_body}, timeout=10)
        except Exception as exc:
            print(f"[Releases] Error updating release body on GitHub: {exc}")

    return True


def get_release_by_id(rel_id):
    releases = list_all_releases(public_view=False)
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
    """Deletes a release from GitHub Releases, local cache, and data-store branch."""
    rel = get_release_by_id(rel_id)
    if not rel:
        raise ValueError("Release not found.")

    # Delete from GitHub Releases
    token = get_github_token()
    repo = get_github_repo()
    if token and repo and requests and str(rel_id).isdigit():
        try:
            headers = get_github_headers()
            del_url = f"https://api.github.com/repos/{repo}/releases/{rel_id}"
            requests.delete(del_url, headers=headers, timeout=10)
            tag_name = rel.get("tag_name")
            if tag_name:
                requests.delete(f"https://api.github.com/repos/{repo}/git/refs/tags/{tag_name}", headers=headers, timeout=10)
        except Exception as exc:
            print(f"[Releases] GitHub delete exception: {exc}")

    # Remove local file if exists
    p = get_release_file_path(rel_id)
    if p and p.exists():
        try:
            p.unlink()
        except Exception:
            pass

    # Update local cache & sync to GitHub data-store branch
    cur = [r for r in load_local_releases_cache() if str(r.get("id")) != str(rel_id)]
    with open(RELEASES_FILE, "w", encoding="utf-8") as f:
        json.dump(cur, f, indent=2, ensure_ascii=False)
    async_cloud_push("releases.json", cur, f"Delete release {rel_id}")

    return True
