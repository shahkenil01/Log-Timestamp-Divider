"""
Log Timestamp Divider - Core Engine
Processes Excel log sheets and distributes timestamps across shift hours,
strictly excluding break intervals (e.g., lunch, tea break).
Supports both realistic human pace and strictly uniform intervals,
as well as optional Light Blue Theme styling.
"""

import io
import re
import datetime
import random
from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# Common column name patterns for timestamps
TIMESTAMP_CANDIDATES = [
    "timestamp", "time", "date_time", "datetime", "log_time", "time_stamp",
    "date", "created_at", "updated_at", "modified_at", "action_time", "entry_time"
]


def parse_time_str(val):
    """Parse time string like '09:30', '9:30 AM', '18:30:00' into datetime.time."""
    if isinstance(val, datetime.time):
        return val
    if isinstance(val, datetime.datetime):
        return val.time()
    val_str = str(val or "").strip()
    if not val_str:
        return None
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M:%S %p", "%I:%M%p"):
        try:
            return datetime.datetime.strptime(val_str, fmt).time()
        except ValueError:
            pass
    # Try regex fallback for e.g. "9:30am" or "13:45"
    m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(am|pm)?$", val_str, re.IGNORECASE)
    if m:
        hr = int(m.group(1))
        mn = int(m.group(2))
        sc = int(m.group(3) or 0)
        ampm = (m.group(4) or "").lower()
        if ampm == "pm" and hr < 12:
            hr += 12
        elif ampm == "am" and hr == 12:
            hr = 0
        return datetime.time(hr, mn, sc)
    return None


def parse_date_str(val):
    """Parse date string into datetime.date."""
    if isinstance(val, datetime.date):
        return val
    if isinstance(val, datetime.datetime):
        return val.date()
    val_str = str(val or "").strip()
    if not val_str:
        return datetime.date.today()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d.%m.%Y", "%m/%d/%Y"):
        try:
            return datetime.datetime.strptime(val_str, fmt).date()
        except ValueError:
            pass
    # Fallback to regex extracting YYYY-MM-DD
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", val_str)
    if m:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return datetime.date.today()


def detect_excel_info(file_bytes_or_path, sheet_name=None):
    """
    Inspects an Excel file and extracts sheet names, headers, candidate timestamp
    columns, total row count, sample data, and auto-detected date.
    """
    if isinstance(file_bytes_or_path, (str, Path)):
        wb = openpyxl.load_workbook(file_bytes_or_path, read_only=True, data_only=True)
    else:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes_or_path), read_only=True, data_only=True)

    sheet_names = wb.sheetnames
    target_sheet = sheet_name if sheet_name in sheet_names else wb.active.title
    ws = wb[target_sheet]

    rows = []
    # Read rows up to a safe sample limit
    row_count = 0
    headers = []
    sample_rows = []
    detected_date = None

    for r_idx, row_values in enumerate(ws.iter_rows(values_only=True), start=1):
        if r_idx == 1:
            headers = [str(c).strip() if c is not None else f"Column_{i+1}" for i, c in enumerate(row_values)]
            continue

        # Check if row is non-empty
        if any(c is not None and str(c).strip() != "" for c in row_values):
            row_count += 1
            if len(sample_rows) < 10:
                sample_rows.append([str(c) if c is not None else "" for c in row_values])
            
            # Try to detect date from row values
            if not detected_date:
                for c in row_values:
                    if isinstance(c, datetime.datetime) or isinstance(c, datetime.date):
                        detected_date = c.strftime("%Y-%m-%d")
                        break
                    elif isinstance(c, str):
                        m = re.search(r"\b(\d{4}[-/.]\d{2}[-/.]\d{2})\b", c)
                        if m:
                            detected_date = m.group(1).replace("/", "-").replace(".", "-")
                            break

    wb.close()

    if not detected_date:
        detected_date = datetime.date.today().strftime("%Y-%m-%d")

    # Determine candidate timestamp column index (1-based)
    timestamp_col_idx = 1
    timestamp_col_name = ""
    for idx, h in enumerate(headers, start=1):
        clean_h = re.sub(r"[^a-zA-Z0-9]", "", h.lower())
        for cand in TIMESTAMP_CANDIDATES:
            if cand in clean_h:
                timestamp_col_idx = idx
                timestamp_col_name = h
                break
        if timestamp_col_name:
            break

    # If header match not found, check column 2 (frequently used as Timestamp) or default to 1
    if not timestamp_col_name:
        if len(headers) >= 2:
            timestamp_col_idx = 2
            timestamp_col_name = headers[1]
        elif headers:
            timestamp_col_idx = 1
            timestamp_col_name = headers[0]

    return {
        "sheet_names": sheet_names,
        "active_sheet": target_sheet,
        "headers": headers,
        "timestamp_col_idx": timestamp_col_idx,
        "timestamp_col_name": timestamp_col_name,
        "total_rows": row_count,
        "detected_date": detected_date,
        "sample_rows": sample_rows
    }


def generate_timestamps(
    target_date,
    shift_start,
    shift_end,
    breaks,
    num_rows,
    mode="natural",
    start_buffer_minutes=8,
    end_buffer_minutes=8,
    random_seed=None
):
    """
    Generates `num_rows` strictly ascending timestamps within the shift window,
    completely bypassing break windows.

    - target_date: datetime.date
    - shift_start: datetime.time
    - shift_end: datetime.time
    - breaks: list of (datetime.time, datetime.time)
    - num_rows: int
    - mode: 'natural' (realistic human task duration variance) or 'uniform'
    - start_buffer_minutes: delay after shift start before 1st task
    - end_buffer_minutes: gap before shift end after last task
    """
    if num_rows <= 0:
        return []

    if random_seed is not None:
        rng = random.Random(random_seed)
    else:
        rng = random.Random()

    d_start = datetime.datetime.combine(target_date, shift_start) + datetime.timedelta(minutes=start_buffer_minutes)
    d_end = datetime.datetime.combine(target_date, shift_end) - datetime.timedelta(minutes=end_buffer_minutes)

    if d_start >= d_end:
        # Fallback if buffers too large
        d_start = datetime.datetime.combine(target_date, shift_start) + datetime.timedelta(minutes=1)
        d_end = datetime.datetime.combine(target_date, shift_end) - datetime.timedelta(minutes=1)

    if d_start >= d_end:
        raise ValueError("Shift start time must be earlier than shift end time.")

    # Process and clip break windows
    clean_breaks = []
    for bs, be in breaks:
        b_dt_start = datetime.datetime.combine(target_date, bs)
        b_dt_end = datetime.datetime.combine(target_date, be)
        if b_dt_start >= b_dt_end:
            continue
        # Clip to shift boundaries
        b_clip_s = max(d_start, b_dt_start)
        b_clip_e = min(d_end, b_dt_end)
        if b_clip_s < b_clip_e:
            clean_breaks.append((b_clip_s, b_clip_e))

    clean_breaks.sort(key=lambda x: x[0])

    # Merge overlapping or touching breaks
    merged_breaks = []
    for b in clean_breaks:
        if not merged_breaks:
            merged_breaks.append(b)
        else:
            prev_s, prev_e = merged_breaks[-1]
            if b[0] <= prev_e:
                merged_breaks[-1] = (prev_s, max(prev_e, b[1]))
            else:
                merged_breaks.append(b)

    # Build active working segments
    segments = []
    cur = d_start
    for bs, be in merged_breaks:
        if bs > cur:
            segments.append((cur, bs))
        cur = max(cur, be)
    if cur < d_end:
        segments.append((cur, d_end))

    durations = [(s[1] - s[0]).total_seconds() for s in segments]
    total_working_sec = sum(durations)

    if total_working_sec <= 0:
        raise ValueError("No working time available in the shift after subtracting breaks.")

    if num_rows == 1:
        offsets = [total_working_sec * 0.15]
    elif mode == "uniform":
        # Strictly uniform spacing across the working seconds
        step = total_working_sec / (num_rows + 1)
        offsets = [step * (i + 1) for i in range(num_rows)]
    else:
        # Natural human pace distribution
        # Tasks have natural variation (e.g., between 2 min and 8 min depending on total rows)
        weights = [rng.uniform(0.65, 1.45) for _ in range(num_rows - 1)]
        sum_w = sum(weights)
        norm_weights = [w / sum_w for w in weights]

        # Margin at start and end
        margin = min(180.0, total_working_sec * 0.03)
        usable_sec = max(10.0, total_working_sec - 2 * margin)

        raw_offsets = [0.0]
        cur_offset = 0.0
        for w in norm_weights:
            cur_offset += w * usable_sec
            raw_offsets.append(cur_offset)

        # Add small random jitter (±3 to ±10 sec) while strictly preserving monotonicity
        offsets = []
        last_val = 0.0
        min_step = max(5.0, usable_sec / (num_rows * 3.5))

        for idx, ro in enumerate(raw_offsets):
            val = margin + ro
            if idx > 0:
                jitter = rng.uniform(-4.0, 4.0)
                val = max(last_val + min_step, val + jitter)
            offsets.append(val)
            last_val = val

        # If last offset went past usable bounds, normalize back
        if offsets[-1] > total_working_sec:
            scale = (total_working_sec - margin) / offsets[-1]
            offsets = [off * scale for off in offsets]

    # Map each virtual offset in [0, total_working_sec] into actual datetime
    result_timestamps = []
    for off in offsets:
        rem = off
        placed = False
        for (s_start, s_end), dur in zip(segments, durations):
            if rem <= dur:
                dt = s_start + datetime.timedelta(seconds=rem)
                result_timestamps.append(dt)
                placed = True
                break
            else:
                rem -= dur
        if not placed:
            result_timestamps.append(segments[-1][1] - datetime.timedelta(seconds=1))

    # Ensure strictly non-decreasing and no microsecond artifacts
    result_clean = []
    prev_dt = None
    for dt in result_timestamps:
        dt_sec = dt.replace(microsecond=0)
        if prev_dt is not None and dt_sec <= prev_dt:
            dt_sec = prev_dt + datetime.timedelta(seconds=1)
        # Double check it does not sit inside a break
        for bs, be in merged_breaks:
            if bs <= dt_sec <= be:
                dt_sec = be + datetime.timedelta(seconds=rng.randint(30, 90))
        result_clean.append(dt_sec)
        prev_dt = dt_sec

    return result_clean


def distribute_excel_timestamps(
    file_bytes_or_path,
    target_date_str,
    shift_start_str,
    shift_end_str,
    breaks_list,
    sheet_name=None,
    timestamp_col=None,
    mode="natural",
    start_buffer_minutes=8,
    end_buffer_minutes=8,
    apply_light_blue_theme=False,
    output_path=None
):
    """
    Loads Excel, computes distributed timestamps, writes them back, applies styling
    if requested, and saves either to disk or returns bytes.
    """
    if isinstance(file_bytes_or_path, (str, Path)):
        wb = openpyxl.load_workbook(file_bytes_or_path)
    else:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes_or_path))

    target_sheet = sheet_name if sheet_name and sheet_name in wb.sheetnames else wb.active.title
    ws = wb[target_sheet]

    # Parse parameters
    target_date = parse_date_str(target_date_str)
    shift_start = parse_time_str(shift_start_str) or datetime.time(9, 30)
    shift_end = parse_time_str(shift_end_str) or datetime.time(18, 30)

    clean_breaks = []
    for b in breaks_list:
        if isinstance(b, (tuple, list)) and len(b) >= 2:
            bs = parse_time_str(b[0])
            be = parse_time_str(b[1])
            if bs and be and bs < be:
                clean_breaks.append((bs, be))

    # Find headers and timestamp column
    first_row = [cell.value for cell in ws[1]]
    total_cols = len(first_row)

    ts_col_idx = 1
    if timestamp_col is not None:
        if isinstance(timestamp_col, int):
            ts_col_idx = timestamp_col
        else:
            col_str = str(timestamp_col).strip().lower()
            for idx, h in enumerate(first_row, start=1):
                if h and str(h).strip().lower() == col_str:
                    ts_col_idx = idx
                    break
    else:
        # Auto detect
        for idx, h in enumerate(first_row, start=1):
            clean_h = re.sub(r"[^a-zA-Z0-9]", "", str(h or "").lower())
            for cand in TIMESTAMP_CANDIDATES:
                if cand in clean_h:
                    ts_col_idx = idx
                    break
            if ts_col_idx > 1:
                break
        if ts_col_idx == 1 and total_cols >= 2:
            ts_col_idx = 2

    # Find all non-empty rows
    data_row_indices = []
    original_timestamps = []
    for r_idx in range(2, ws.max_row + 1):
        row_vals = [ws.cell(row=r_idx, column=c).value for c in range(1, total_cols + 1)]
        if any(v is not None and str(v).strip() != "" for v in row_vals):
            data_row_indices.append(r_idx)
            orig_ts = ws.cell(row=r_idx, column=ts_col_idx).value
            original_timestamps.append(str(orig_ts or "").strip())

    num_rows = len(data_row_indices)
    if num_rows == 0:
        raise ValueError("No data rows found in the selected sheet to update.")

    # Generate new timestamps
    new_timestamps = generate_timestamps(
        target_date=target_date,
        shift_start=shift_start,
        shift_end=shift_end,
        breaks=clean_breaks,
        num_rows=num_rows,
        mode=mode,
        start_buffer_minutes=start_buffer_minutes,
        end_buffer_minutes=end_buffer_minutes
    )

    # Theme styles
    header_fill = PatternFill(start_color="1155CC", end_color="1155CC", fill_type="solid")
    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    even_row_fill = PatternFill(start_color="E8F0FE", end_color="E8F0FE", fill_type="solid")
    odd_row_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1")
    )
    center_align = Alignment(horizontal="center", vertical="center")
    left_align = Alignment(horizontal="left", vertical="center")

    # Update cells
    for pos, r_idx in enumerate(data_row_indices):
        dt_val = new_timestamps[pos]
        dt_str = dt_val.strftime("%Y-%m-%d %H:%M:%S")
        cell = ws.cell(row=r_idx, column=ts_col_idx)
        cell.value = dt_str

        if apply_light_blue_theme:
            # Row index 2 is first data row -> Even row in 1-based indexing
            row_fill = even_row_fill if (r_idx % 2 == 0) else odd_row_fill
            for c_idx in range(1, total_cols + 1):
                c_cell = ws.cell(row=r_idx, column=c_idx)
                c_cell.fill = row_fill
                c_cell.border = thin_border
                c_cell.font = Font(name="Segoe UI", size=10, color="0F172A")
                if c_idx in (1, ts_col_idx):
                    c_cell.alignment = center_align
                else:
                    c_cell.alignment = left_align

    if apply_light_blue_theme:
        # Style Header Row
        ws.row_dimensions[1].height = 28
        ws.freeze_panes = "A2"
        for c_idx in range(1, total_cols + 1):
            h_cell = ws.cell(row=1, column=c_idx)
            h_cell.fill = header_fill
            h_cell.font = header_font
            h_cell.border = thin_border
            h_cell.alignment = center_align

    # Calculate statistics
    shift_duration_sec = (datetime.datetime.combine(target_date, shift_end) - datetime.datetime.combine(target_date, shift_start)).total_seconds()
    break_total_sec = sum(
        (datetime.datetime.combine(target_date, be) - datetime.datetime.combine(target_date, bs)).total_seconds()
        for bs, be in clean_breaks
    )
    work_total_sec = max(0, shift_duration_sec - break_total_sec)
    avg_sec_per_log = (work_total_sec / num_rows) if num_rows else 0

    stats = {
        "num_rows": num_rows,
        "target_date": target_date.strftime("%Y-%m-%d"),
        "shift_start": shift_start.strftime("%H:%M:%S"),
        "shift_end": shift_end.strftime("%H:%M:%S"),
        "total_breaks": len(clean_breaks),
        "break_minutes": int(break_total_sec // 60),
        "working_hours": round(work_total_sec / 3600.0, 2),
        "avg_minutes_per_log": round(avg_sec_per_log / 60.0, 2),
        "first_timestamp": new_timestamps[0].strftime("%Y-%m-%d %H:%M:%S") if new_timestamps else None,
        "last_timestamp": new_timestamps[-1].strftime("%Y-%m-%d %H:%M:%S") if new_timestamps else None,
        "preview_comparisons": [
            {
                "row_num": data_row_indices[i],
                "original": original_timestamps[i] if i < len(original_timestamps) else "",
                "new": new_timestamps[i].strftime("%Y-%m-%d %H:%M:%S")
            }
            for i in range(min(num_rows, 50))
        ]
    }

    # Save output
    if output_path:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        wb.save(out_p)
        wb.close()
        return stats, str(out_p)
    else:
        out_stream = io.BytesIO()
        wb.save(out_stream)
        wb.close()
        out_stream.seek(0)
        return stats, out_stream.getvalue()
