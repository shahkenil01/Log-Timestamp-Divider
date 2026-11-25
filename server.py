#!/usr/bin/env python3
"""
Log Timestamp Divider - Web Server with Approval Workflow & Admin Dashboard
Provides:
1. Public preview (strictly limited to 50 rows).
2. Intern / User approval submission with Requester Name.
3. Locked download (users CANNOT download until Admin approves).
4. Protected Admin Dashboard to view, validate breaks/timings, and approve/reject requests.
"""

import os
import sys
import json
import base64
import argparse
import webbrowser
import threading
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, Form, Header, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse
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
    is_valid_admin_token,
    create_approval_request,
    get_request_by_id,
    load_all_requests,
    approve_request,
    reject_request,
    get_request_excel_path
)

TEMPLATES_DIR = BASE_DIR / "templates"
INDEX_HTML = TEMPLATES_DIR / "index.html"

# Initialize data store
init_storage()

app = FastAPI(title="Log Timestamp Divider with Admin Approval", version="2.0.0")

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
        return JSONResponse({"success": False, "error": "Please provide your Name / Intern Name."}, status_code=400)

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
    ok, token = verify_admin_login(username.strip(), password.strip())
    if not ok:
        return JSONResponse({"success": False, "error": "Invalid Admin Username or Password."}, status_code=401)
    return JSONResponse({"success": True, "token": token})


@app.get("/api/admin/requests")
async def admin_get_requests(authorization: str = Header(None), x_admin_token: str = Header(None)):
    """Returns all requests for Admin inspection."""
    token = x_admin_token or authorization
    if not is_valid_admin_token(token):
        return JSONResponse({"success": False, "error": "Unauthorized. Please login as Admin."}, status_code=401)
    reqs = load_all_requests()
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


def open_browser_delayed(url, delay=1.2):
    def _open():
        import time
        time.sleep(delay)
        webbrowser.open(url)
    t = threading.Thread(target=_open, daemon=True)
    t.start()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Log Timestamp Divider Web Server with Admin Approval")
    parser.add_argument("--port", type=int, default=8899, help="Port to listen on (default: 8899)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")
    args = parser.parse_args()

    env_port = os.environ.get("PORT")
    is_cloud = env_port is not None
    port = int(env_port) if is_cloud else args.port
    host = "0.0.0.0" if is_cloud else args.host

    url = f"http://{host}:{port}/"
    print(f"\n========================================================")
    print(f"  Log Timestamp Divider with Admin Approval Workflow")
    print(f"  Running at: {url} (Cloud Mode: {is_cloud})")
    print(f"  Default Admin Credentials: admin / admin")
    print(f"========================================================\n")

    if not args.no_browser and not is_cloud:
        open_browser_delayed(url)

    uvicorn.run(app, host=host, port=port, log_level="info" if is_cloud else "warning")
