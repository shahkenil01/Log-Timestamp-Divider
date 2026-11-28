#!/usr/bin/env python3
"""
Log Timestamp Divider - Web Server with Approval Workflow & Multi-Admin Management
Features:
1. Public preview (strictly limited to 50 rows).
2. User / Team Member approval submission with Requester Name.
3. Locked download (users CANNOT download until Admin approves).
4. Protected Admin Dashboard with Date-wise filter & live status management.
5. Master Admin Portal to manage Admin accounts, Releases, and .env configuration.
"""

import os
import re
import sys
import json
import base64
import argparse
import webbrowser
import threading
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import io

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Import core engine & storage
from engine import detect_excel_info, distribute_excel_timestamps
from storage import (
    init_storage,
    verify_admin_login,
    verify_master_login,
    is_valid_admin_token,
    is_valid_master_token,
    list_all_admins,
    add_admin_account,
    update_admin_account,
    delete_admin_account,
    create_approval_request,
    get_request_by_id,
    load_all_requests,
    approve_request,
    reject_request,
    get_request_excel_path,
    list_all_releases,
    save_release_file,
    update_release_password,
    generate_download_token,
    verify_download_token,
    get_release_by_id,
    get_release_file_path,
    delete_release_file,
    read_env_file,
    write_env_file,
    delete_env_key,
    get_env_value
)

TEMPLATES_DIR = BASE_DIR / "templates"
INDEX_HTML = TEMPLATES_DIR / "index.html"

# Initialize data store
init_storage()

app = FastAPI(title="Log Timestamp Divider with Admin Approval & Master Control", version="2.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serve the primary application page."""
    if not INDEX_HTML.exists():
        return HTMLResponse("<h2>Error: index.html not found!</h2>", status_code=500)
    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.post("/api/inspect")
async def inspect_excel(file: UploadFile = File(...), sheet_name: str = Form(None)):
    """Inspects the uploaded Excel file to extract metadata, headers, and row count."""
    try:
        content = await file.read()
        info = detect_excel_info(content, sheet_name=sheet_name)
        info["filename"] = file.filename
        return JSONResponse({"success": True, "data": info})
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=400)


@app.post("/api/preview")
async def preview_distribution(
    file: UploadFile = File(...),
    target_date: str = Form(...),
    shift_start: str = Form(...),
    shift_end: str = Form(...),
    lunch_start: str = Form("13:00"),
    lunch_end: str = Form("14:00"),
    break2_enabled: str = Form("false"),
    break2_start: str = Form("16:30"),
    break2_end: str = Form("16:45"),
    sheet_name: str = Form(None),
    timestamp_col: str = Form(None),
    mode: str = Form("natural"),
    start_buffer: int = Form(8),
    end_buffer: int = Form(8),
    apply_theme: str = Form("false")
):
    """Calculates timestamps and returns preview comparisons strictly limited to 50 rows."""
    try:
        content = await file.read()
        breaks = [(lunch_start, lunch_end)]
        if break2_enabled.lower() == "true":
            breaks.append((break2_start, break2_end))

        stats, _ = distribute_excel_timestamps(
            file_bytes_or_path=content,
            target_date_str=target_date,
            shift_start_str=shift_start,
            shift_end_str=shift_end,
            breaks_list=breaks,
            sheet_name=sheet_name or None,
            timestamp_col=timestamp_col or None,
            mode=mode,
            start_buffer_minutes=start_buffer,
            end_buffer_minutes=end_buffer,
            apply_light_blue_theme=(apply_theme.lower() == "true")
        )

        # Strictly cap preview comparisons to 50 rows max
        stats["preview_comparisons"] = stats.get("preview_comparisons", [])[:50]

        return JSONResponse({"success": True, "stats": stats})
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=400)


@app.post("/api/request-approval")
async def submit_approval_request(
    file: UploadFile = File(...),
    user_name: str = Form(...),
    target_date: str = Form(...),
    shift_start: str = Form(...),
    shift_end: str = Form(...),
    lunch_start: str = Form("13:00"),
    lunch_end: str = Form("14:00"),
    break2_enabled: str = Form("false"),
    break2_start: str = Form("16:30"),
    break2_end: str = Form("16:45"),
    sheet_name: str = Form(None),
    timestamp_col: str = Form(None),
    mode: str = Form("natural"),
    start_buffer: int = Form(8),
    end_buffer: int = Form(8),
    apply_theme: str = Form("false")
):
    """
    User submits their Excel log and shift configuration for Admin approval.
    The file is divided and saved on the server in PENDING state.
    Download is strictly LOCKED until Admin approves.
    """
    clean_user = str(user_name or "").strip()
    if not clean_user:
        return JSONResponse({"success": False, "error": "Please provide your Name."}, status_code=400)

    try:
        content = await file.read()
        breaks = [(lunch_start, lunch_end)]
        has_break2 = (break2_enabled.lower() == "true")
        if has_break2:
            breaks.append((break2_start, break2_end))

        stats, out_bytes = distribute_excel_timestamps(
            file_bytes_or_path=content,
            target_date_str=target_date,
            shift_start_str=shift_start,
            shift_end_str=shift_end,
            breaks_list=breaks,
            sheet_name=sheet_name or None,
            timestamp_col=timestamp_col or None,
            mode=mode,
            start_buffer_minutes=start_buffer,
            end_buffer_minutes=end_buffer,
            apply_light_blue_theme=(apply_theme.lower() == "true")
        )

        req_data = create_approval_request(
            user_name=clean_user,
            original_filename=file.filename,
            target_date=target_date,
            shift_start=shift_start,
            shift_end=shift_end,
            lunch_start=lunch_start,
            lunch_end=lunch_end,
            break2_enabled=has_break2,
            break2_start=break2_start,
            break2_end=break2_end,
            stats=stats,
            excel_bytes=out_bytes
        )

        return JSONResponse({"success": True, "request": req_data})
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=400)


@app.get("/api/request-status/{request_id}")
async def check_request_status(request_id: str):
    """Returns the current approval status for a given Request ID."""
    req = get_request_by_id(request_id)
    if not req:
        return JSONResponse({"success": False, "error": "Request ID not found."}, status_code=404)
    return JSONResponse({
        "success": True,
        "id": req["id"],
        "status": req["status"],
        "user_name": req["user_name"],
        "approved_at": req.get("approved_at"),
        "rejection_reason": req.get("rejection_reason"),
        "can_download": (req["status"] == "APPROVED")
    })


@app.get("/api/download-approved/{request_id}")
async def download_approved_file(request_id: str):
    """
    Downloads the modified Excel file ONLY IF status is APPROVED.
    Strictly blocked if status is PENDING or REJECTED.
    """
    req = get_request_by_id(request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found.")

    if req["status"] != "APPROVED":
        raise HTTPException(
            status_code=403,
            detail="Download Locked! This request is not approved by Admin. Please contact Admin for approval."
        )

    file_path = get_request_excel_path(request_id)
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="Generated Excel file not found on server.")

    orig_stem = Path(req.get("filename", "log")).stem
    target_date = req.get("target_date", "divided")
    download_name = f"{orig_stem}_approved_{target_date}.xlsx"

    return FileResponse(
        path=str(file_path),
        filename=download_name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# =============================================================================
# ADMIN DASHBOARD API
# =============================================================================

@app.post("/api/admin/login")
async def admin_login(username: str = Form(...), password: str = Form(...)):
    """Verifies admin credentials and returns session token."""
    ok, token, adm_info = verify_admin_login(username.strip(), password.strip())
    if not ok:
        return JSONResponse({"success": False, "error": "Invalid Admin Username or Password."}, status_code=401)
    return JSONResponse({"success": True, "token": token, "admin": adm_info})


@app.get("/api/admin/requests")
async def admin_get_requests(
    date: str = None,
    authorization: str = Header(None),
    x_admin_token: str = Header(None)
):
    """Returns requests for Admin inspection, syncing with GitHub cloud first."""
    token = x_admin_token or authorization
    if not is_valid_admin_token(token):
        return JSONResponse({"success": False, "error": "Unauthorized. Please login as Admin."}, status_code=401)
    reqs = load_all_requests(date_filter=date, sync_cloud=True)
    return JSONResponse({"success": True, "requests": reqs})


@app.post("/api/admin/approve/{request_id}")
async def admin_approve_request(request_id: str, authorization: str = Header(None), x_admin_token: str = Header(None)):
    """Admin approves a request."""
    token = x_admin_token or authorization
    if not is_valid_admin_token(token):
        return JSONResponse({"success": False, "error": "Unauthorized."}, status_code=401)
    ok, updated = approve_request(request_id)
    if not ok:
        return JSONResponse({"success": False, "error": "Request not found."}, status_code=404)
    return JSONResponse({"success": True, "request": updated})


@app.post("/api/admin/reject/{request_id}")
async def admin_reject_request(
    request_id: str,
    reason: str = Form("Timing mismatch or excessive break taken"),
    authorization: str = Header(None),
    x_admin_token: str = Header(None)
):
    """Admin rejects a request."""
    token = x_admin_token or authorization
    if not is_valid_admin_token(token):
        return JSONResponse({"success": False, "error": "Unauthorized."}, status_code=401)
    ok, updated = reject_request(request_id, reason=reason)
    if not ok:
        return JSONResponse({"success": False, "error": "Request not found."}, status_code=404)
    return JSONResponse({"success": True, "request": updated})


@app.get("/api/admin/download/{request_id}")
async def admin_direct_download(request_id: str, token: str = None, authorization: str = Header(None), x_admin_token: str = Header(None)):
    """Admin can download any file directly."""
    auth_token = token or x_admin_token or authorization
    if not is_valid_admin_token(auth_token):
        raise HTTPException(status_code=401, detail="Unauthorized.")
    file_path = get_request_excel_path(request_id)
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    req = get_request_by_id(request_id)
    orig_stem = Path(req.get("filename", "log")).stem if req else "log"
    return FileResponse(
        path=str(file_path),
        filename=f"{orig_stem}_admin_{request_id}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# =============================================================================
# MASTER ADMIN API
# =============================================================================

@app.post("/api/master/login")
async def master_login(username: str = Form(...), password: str = Form(...)):
    """Verifies Master Admin credentials from .env."""
    ok, token = verify_master_login(username.strip(), password.strip())
    if not ok:
        return JSONResponse({"success": False, "error": "Invalid Master Username or Password."}, status_code=401)
    return JSONResponse({"success": True, "token": token})


@app.get("/api/master/admins")
async def master_get_admins(authorization: str = Header(None), x_master_token: str = Header(None)):
    """Master Admin views all configured admin accounts."""
    token = x_master_token or authorization
    if not is_valid_master_token(token):
        return JSONResponse({"success": False, "error": "Unauthorized. Master Admin access required."}, status_code=401)
    admins = list_all_admins()
    return JSONResponse({"success": True, "admins": admins})


@app.post("/api/master/admins/add")
async def master_add_admin(
    username: str = Form(...),
    password: str = Form(...),
    name: str = Form(""),
    authorization: str = Header(None),
    x_master_token: str = Header(None)
):
    """Master Admin adds a new admin user."""
    token = x_master_token or authorization
    if not is_valid_master_token(token):
        return JSONResponse({"success": False, "error": "Unauthorized. Master Admin access required."}, status_code=401)
    try:
        new_adm = add_admin_account(username, password, name)
        return JSONResponse({"success": True, "admin": new_adm})
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=400)


@app.post("/api/master/admins/update")
async def master_update_admin(
    admin_id: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    name: str = Form(""),
    authorization: str = Header(None),
    x_master_token: str = Header(None)
):
    """Master Admin updates an admin user."""
    token = x_master_token or authorization
    if not is_valid_master_token(token):
        return JSONResponse({"success": False, "error": "Unauthorized. Master Admin access required."}, status_code=401)
    try:
        upd = update_admin_account(admin_id, username, password, name)
        return JSONResponse({"success": True, "admin": upd})
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=400)


@app.post("/api/master/admins/delete")
async def master_delete_admin(
    admin_id: str = Form(...),
    authorization: str = Header(None),
    x_master_token: str = Header(None)
):
    """Master Admin deletes an admin user."""
    token = x_master_token or authorization
    if not is_valid_master_token(token):
        return JSONResponse({"success": False, "error": "Unauthorized. Master Admin access required."}, status_code=401)
    try:
        delete_admin_account(admin_id)
        return JSONResponse({"success": True})
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=400)


# =============================================================================
# ACTMASTER ZIP RELEASES & UPDATES API
# =============================================================================

@app.get("/api/releases")
async def get_public_releases():
    """Public endpoint to list all available ActMaster zip releases & updates (passwords hidden)."""
    releases = list_all_releases(public_view=True)
    return JSONResponse({"success": True, "releases": releases})


@app.get("/api/master/releases")
async def get_master_releases(authorization: str = Header(None), x_master_token: str = Header(None)):
    """Master Admin endpoint to list all releases with visible passwords for management."""
    token = x_master_token or authorization
    if not is_valid_master_token(token):
        return JSONResponse({"success": False, "error": "Unauthorized. Master Admin access required."}, status_code=401)
    releases = list_all_releases(public_view=False)
    return JSONResponse({"success": True, "releases": releases})


@app.post("/api/releases/verify-password")
async def verify_release_password(
    release_id: str = Form(...),
    password: str = Form("")
):
    """Verifies user-submitted security password before downloading a zip release."""
    rel = get_release_by_id(release_id)
    if not rel:
        return JSONResponse({"success": False, "error": "Release package not found."}, status_code=404)
    
    expected_pw = str(rel.get("download_password") or "").strip()
    if not expected_pw:
        # No password required
        return JSONResponse({
            "success": True, 
            "download_url": f"/api/releases/download/{release_id}"
        })
    
    if password.strip() != expected_pw:
        return JSONResponse({
            "success": False, 
            "error": "Incorrect security password! Please contact Master Admin for the download password."
        }, status_code=403)
    
    # Generate single-use secure download token (valid for 15 mins)
    dl_token = generate_download_token(release_id)
    return JSONResponse({
        "success": True, 
        "download_url": f"/api/releases/download/{release_id}?dl_token={dl_token}"
    })


@app.get("/api/releases/check-lock/{release_id}")
async def check_release_lock(release_id: str):
    """Checks whether a release package is password-protected before attempting download."""
    rel = get_release_by_id(release_id)
    if not rel:
        return JSONResponse({"success": False, "error": "Release not found"}, status_code=404)
    expected_pw = str(rel.get("download_password") or "").strip()
    return JSONResponse({
        "success": True,
        "release_id": release_id,
        "locked": bool(expected_pw),
        "title": rel.get("title") or rel.get("filename"),
        "filename": rel.get("filename")
    })


@app.get("/api/releases/download/{release_id}")
async def download_release_file(
    release_id: str,
    dl_token: str = None,
    password: str = None,
    master_token: str = None,
    authorization: str = Header(None),
    x_master_token: str = Header(None)
):
    """Public endpoint to download an ActMaster zip release package with security password verification."""
    rel = get_release_by_id(release_id)
    if not rel:
        raise HTTPException(status_code=404, detail="Release package not found.")
    
    expected_pw = str(rel.get("download_password") or "").strip()
    if expected_pw:
        authorized = False
        m_tok = master_token or x_master_token or authorization
        if m_tok and is_valid_master_token(m_tok):
            authorized = True
        elif dl_token and verify_download_token(release_id, dl_token):
            authorized = True
        elif password and password.strip() == expected_pw:
            authorized = True
        
        if not authorized:
            raise HTTPException(
                status_code=403, 
                detail="Download Locked! Security password required to download this ActMaster release."
            )

    # If GitHub Release CDN URL is present, redirect directly for fast cloud download with 0 server memory/disk load
    if rel.get("download_url"):
        return RedirectResponse(url=rel["download_url"], status_code=302)

    file_path = get_release_file_path(release_id)
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="Release file not found on disk.")
    
    orig_filename = rel.get("filename") or "ActMaster_Update.zip"
    return FileResponse(
        path=str(file_path),
        filename=orig_filename,
        media_type="application/octet-stream"
    )


@app.post("/api/master/releases/upload")
async def master_upload_release(
    file: UploadFile = File(...),
    title: str = Form(""),
    description: str = Form(""),
    download_password: str = Form(""),
    authorization: str = Header(None),
    x_master_token: str = Header(None)
):
    """Master Admin uploads a new ActMaster zip release or update with optional download password."""
    token = x_master_token or authorization
    if not is_valid_master_token(token):
        return JSONResponse({"success": False, "error": "Unauthorized. Master Admin access required."}, status_code=401)
    
    try:
        content = await file.read()
        if not content:
            return JSONResponse({"success": False, "error": "Cannot upload an empty file."}, status_code=400)
        
        rel_meta = save_release_file(
            original_filename=file.filename,
            file_bytes=content,
            title=title,
            description=description,
            download_password=download_password,
            uploaded_by=get_env_value("MASTER_DISPLAY_NAME", "Master Admin")
        )
        return JSONResponse({"success": True, "release": rel_meta})
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=400)


@app.post("/api/master/releases/update-password")
async def master_update_release_password(
    release_id: str = Form(...),
    password: str = Form(""),
    authorization: str = Header(None),
    x_master_token: str = Header(None)
):
    """Master Admin updates or sets a security password for an existing release."""
    token = x_master_token or authorization
    if not is_valid_master_token(token):
        return JSONResponse({"success": False, "error": "Unauthorized. Master Admin access required."}, status_code=401)
    
    ok = update_release_password(release_id, password.strip())
    if not ok:
        return JSONResponse({"success": False, "error": "Release package not found."}, status_code=404)
    return JSONResponse({"success": True, "password": password.strip()})


@app.post("/api/master/releases/delete")
async def master_delete_release(
    release_id: str = Form(...),
    authorization: str = Header(None),
    x_master_token: str = Header(None)
):
    """Master Admin deletes an outdated release package."""
    token = x_master_token or authorization
    if not is_valid_master_token(token):
        return JSONResponse({"success": False, "error": "Unauthorized. Master Admin access required."}, status_code=401)
    
    try:
        delete_release_file(release_id)
        return JSONResponse({"success": True})
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=400)


def open_browser_delayed(url, delay=1.2):
    def _open():
        import time
        time.sleep(delay)
        webbrowser.open(url)
    t = threading.Thread(target=_open, daemon=True)
    t.start()


# =============================================================================
# ENVIRONMENT CONFIGURATION API (.env Management — Master Admin Only)
# =============================================================================

# Core credential & configuration keys tracked in UI + any custom keys in .env
ENV_STANDARD_KEYS = [
    "MASTER_USERNAME", "MASTER_PASSWORD", "MASTER_DISPLAY_NAME",
    "ADMIN_USERNAME", "ADMIN_PASSWORD", "ADMIN_NAME",
    "GITHUB_TOKEN", "GITHUB_REPO", "GITHUB_DATA_BRANCH",
    "CDN_API_KEY", "CLOUD_API_KEY",
    "PORT", "HOST"
]

# Critical keys that cannot be empty or deleted (prevents accidental lockout)
ENV_REQUIRED_KEYS = {"MASTER_USERNAME", "MASTER_PASSWORD"}
ENV_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def _is_sensitive_key(key: str) -> bool:
    u = key.upper()
    return any(tok in u for tok in ("PASSWORD", "TOKEN", "SECRET", "KEY", "AUTH"))


def _build_env_response() -> dict:
    """Merges keys from .env file with OS environment values for standard keys."""
    env_data = read_env_file()
    ordered_keys = list(ENV_STANDARD_KEYS)
    for k in env_data.keys():
        uk = k.strip().upper()
        if uk and uk not in ordered_keys:
            ordered_keys.append(uk)

    result = {}
    for key in ordered_keys:
        val = env_data.get(key)
        if val is None or val == "":
            val = os.environ.get(key, "").strip()
        is_sens = _is_sensitive_key(key)
        if is_sens and val and len(val) > 4:
            masked = "●" * (len(val) - 4) + val[-4:]
        elif is_sens and val:
            masked = "●" * len(val)
        else:
            masked = val
        result[key] = {
            "value": val,
            "masked": masked,
            "is_sensitive": is_sens,
            "is_standard": key in ENV_STANDARD_KEYS,
            "is_required": key in ENV_REQUIRED_KEYS
        }
    return result


@app.get("/api/env")
@app.get("/api/master/env")
async def master_get_env(
    authorization: str = Header(None),
    x_master_token: str = Header(None)
):
    """Fetches all environment credentials and settings directly from .env (Master Admin only)."""
    token = x_master_token or authorization
    if not is_valid_master_token(token):
        return JSONResponse({"success": False, "error": "Unauthorized. Master Admin access required."}, status_code=401)

    return JSONResponse({"success": True, "env": _build_env_response()})


@app.post("/api/env")
async def post_env_values(
    request: Request,
    authorization: str = Header(None),
    x_master_token: str = Header(None)
):
    """
    Simple unified API to post data directly to .env file.
    Accepts JSON dict ({"KEY": "VALUE", ...} or {"key": "KEY", "value": "VAL"})
    or form-urlencoded / multipart form fields.
    """
    token = x_master_token or authorization
    if not is_valid_master_token(token):
        return JSONResponse({"success": False, "error": "Unauthorized. Master Admin access required."}, status_code=401)

    updates_raw = {}
    ctype = (request.headers.get("content-type") or "").lower()
    if "application/json" in ctype:
        try:
            body = await request.json()
            if isinstance(body, dict):
                if "key" in body and "value" in body and len(body) <= 2:
                    updates_raw[str(body["key"])] = str(body["value"])
                else:
                    updates_raw = body
        except Exception:
            return JSONResponse({"success": False, "error": "Invalid JSON payload."}, status_code=400)
    else:
        form = await request.form()
        if "request_body" in form:
            try:
                updates_raw = json.loads(str(form["request_body"]))
            except Exception:
                return JSONResponse({"success": False, "error": "Invalid JSON in request_body."}, status_code=400)
        elif "key" in form:
            updates_raw[str(form["key"])] = str(form.get("value", ""))
        else:
            updates_raw = dict(form)

    filtered = {}
    for k, v in updates_raw.items():
        clean_key = str(k or "").strip().upper()
        if not ENV_KEY_PATTERN.match(clean_key):
            return JSONResponse({"success": False, "error": f"Invalid key format '{clean_key}'. Use UPPERCASE letters, numbers, and underscores."}, status_code=400)
        clean_val = str(v if v is not None else "").strip()
        if clean_key in ENV_REQUIRED_KEYS and not clean_val:
            return JSONResponse({"success": False, "error": f"{clean_key} cannot be empty."}, status_code=400)
        filtered[clean_key] = clean_val

    if not filtered:
        return JSONResponse({"success": False, "error": "No valid environment keys provided."}, status_code=400)

    if not write_env_file(filtered):
        return JSONResponse({"success": False, "error": "Failed to write to .env file."}, status_code=500)

    return JSONResponse({
        "success": True,
        "updated_keys": list(filtered.keys()),
        "env": _build_env_response(),
        "message": f"Saved {len(filtered)} key(s) directly to .env!"
    })


@app.post("/api/master/env/update")
async def master_update_env(
    key: str = Form(...),
    value: str = Form(""),
    authorization: str = Header(None),
    x_master_token: str = Header(None)
):
    """Updates or adds a single key directly in .env file (Master Admin only)."""
    token = x_master_token or authorization
    if not is_valid_master_token(token):
        return JSONResponse({"success": False, "error": "Unauthorized. Master Admin access required."}, status_code=401)

    clean_key = key.strip().upper()
    if not ENV_KEY_PATTERN.match(clean_key):
        return JSONResponse({"success": False, "error": f"Invalid key format '{clean_key}'. Use UPPERCASE letters, digits, and '_'."}, status_code=400)

    clean_val = value.strip()
    if clean_key in ENV_REQUIRED_KEYS and not clean_val:
        return JSONResponse({"success": False, "error": f"{clean_key} cannot be empty."}, status_code=400)

    ok = write_env_file({clean_key: clean_val})
    if not ok:
        return JSONResponse({"success": False, "error": "Failed to write to .env file."}, status_code=500)

    return JSONResponse({"success": True, "key": clean_key, "env": _build_env_response(), "message": f"{clean_key} saved to .env!"})


@app.post("/api/master/env/bulk-update")
async def master_bulk_update_env(
    request_body: str = Form(...),
    authorization: str = Header(None),
    x_master_token: str = Header(None)
):
    """Updates multiple keys at once directly in .env file (Master Admin only)."""
    token = x_master_token or authorization
    if not is_valid_master_token(token):
        return JSONResponse({"success": False, "error": "Unauthorized. Master Admin access required."}, status_code=401)

    try:
        updates = json.loads(request_body)
    except Exception:
        return JSONResponse({"success": False, "error": "Invalid JSON data."}, status_code=400)

    filtered = {}
    for k, v in updates.items():
        clean_key = str(k or "").strip().upper()
        if not ENV_KEY_PATTERN.match(clean_key):
            continue
        clean_val = str(v if v is not None else "").strip()
        if clean_key in ENV_REQUIRED_KEYS and not clean_val:
            continue
        filtered[clean_key] = clean_val

    if not filtered:
        return JSONResponse({"success": False, "error": "No valid keys to update."}, status_code=400)

    ok = write_env_file(filtered)
    if not ok:
        return JSONResponse({"success": False, "error": "Failed to write to .env file."}, status_code=500)

    return JSONResponse({"success": True, "updated_keys": list(filtered.keys()), "env": _build_env_response(), "message": f"Saved {len(filtered)} key(s) to .env!"})


@app.delete("/api/env/{key}")
@app.post("/api/master/env/delete")
async def master_delete_env(
    key: str = None,
    request: Request = None,
    authorization: str = Header(None),
    x_master_token: str = Header(None)
):
    """Deletes a custom environment key from .env (Master Admin only)."""
    token = x_master_token or authorization
    if not is_valid_master_token(token):
        return JSONResponse({"success": False, "error": "Unauthorized. Master Admin access required."}, status_code=401)

    if not key and request is not None:
        form = await request.form()
        key = str(form.get("key", ""))

    clean_key = str(key or "").strip().upper()
    if clean_key in ENV_REQUIRED_KEYS:
        return JSONResponse({"success": False, "error": f"Cannot delete required login key '{clean_key}'."}, status_code=400)
    if not ENV_KEY_PATTERN.match(clean_key):
        return JSONResponse({"success": False, "error": "Invalid key name."}, status_code=400)

    delete_env_key(clean_key)
    return JSONResponse({"success": True, "deleted_key": clean_key, "env": _build_env_response(), "message": f"Removed {clean_key} from .env."})


if __name__ == "__main__":
    default_port = int(get_env_value("PORT", "8000") or 8000)
    default_host = get_env_value("HOST", "127.0.0.1") or "127.0.0.1"

    parser = argparse.ArgumentParser(description="Log Timestamp Divider Web Server with Admin Approval")
    parser.add_argument("--port", type=int, default=default_port, help="Port to listen on (from .env PORT)")
    parser.add_argument("--host", type=str, default=default_host, help="Host interface (from .env HOST)")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")
    args = parser.parse_args()

    cloud_env_port = os.environ.get("PORT")
    is_cloud = cloud_env_port is not None
    port = int(cloud_env_port) if is_cloud else args.port
    host = "0.0.0.0" if is_cloud else args.host

    url = f"http://{host}:{port}/"
    print(f"\n========================================================")
    print(f"  Log Timestamp Divider with Multi-Admin & Master Control")
    print(f"  Running at: {url} (Cloud Mode: {is_cloud})")
    print(f"  Credentials & API Keys: Loaded securely from .env")
    print(f"========================================================\n")

    if not args.no_browser and not is_cloud:
        open_browser_delayed(url)

    uvicorn.run(app, host=host, port=port, log_level="info" if is_cloud else "warning")
