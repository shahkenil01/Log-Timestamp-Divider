#!/usr/bin/env python3
"""
Log Timestamp Divider - Local Web Server
Provides a modern Web UI for uploading Excel log sheets, configuring shift
and break intervals, previewing distributed timestamps, and downloading
the updated Excel file.
"""

import os
import sys
import json
import base64
import argparse
import webbrowser
import threading
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import io

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Import core engine
from engine import detect_excel_info, distribute_excel_timestamps

TEMPLATES_DIR = BASE_DIR / "templates"
INDEX_HTML = TEMPLATES_DIR / "index.html"

app = FastAPI(title="Log Timestamp Divider", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serve the primary HTML application page."""
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
    """Calculates timestamps and returns preview comparisons without saving to disk."""
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

        return JSONResponse({"success": True, "stats": stats})
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=400)


@app.post("/api/divide")
async def divide_and_download(
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
    """Processes the Excel file, replaces timestamps, applies optional theme, and returns the modified Excel file."""
    try:
        content = await file.read()
        breaks = [(lunch_start, lunch_end)]
        if break2_enabled.lower() == "true":
            breaks.append((break2_start, break2_end))

        is_theme_applied = (apply_theme.lower() == "true")

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
            apply_light_blue_theme=is_theme_applied
        )

        orig_filename = Path(file.filename).stem or "log_file"
        out_filename = f"{orig_filename}_divided_{target_date}.xlsx"

        # Return streaming file response
        return StreamingResponse(
            io.BytesIO(out_bytes),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{out_filename}"',
                "X-Stats-Rows": str(stats["num_rows"]),
                "X-Stats-WorkHours": str(stats["working_hours"]),
                "Access-Control-Expose-Headers": "Content-Disposition, X-Stats-Rows, X-Stats-WorkHours"
            }
        )
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=400)


def open_browser_delayed(url, delay=1.2):
    def _open():
        import time
        time.sleep(delay)
        webbrowser.open(url)
    t = threading.Thread(target=_open, daemon=True)
    t.start()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Log Timestamp Divider Web Server")
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
    print(f"  Log Timestamp Divider - Shift Work Time Distributor")
    print(f"  Running at: {url} (Cloud Mode: {is_cloud})")
    print(f"========================================================\n")

    if not args.no_browser and not is_cloud:
        open_browser_delayed(url)

    uvicorn.run(app, host=host, port=port, log_level="info" if is_cloud else "warning")
