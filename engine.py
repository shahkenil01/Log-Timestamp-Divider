"""
Log Timestamp Divider - Core Engine (Action-Aware & Genuine Human Pacing)
Calculates highly realistic, non-predictable timestamps based on real-world action types:
1. 'Insert Provision' / 'Add': 5 to 22 seconds (rapid insertion flow).
2. 'Edit Provision' / 'Update': 20 to 52 seconds (text modification/correction).
3. 'Bulk Delete': 2.5 to 5.5 minutes (careful review & multi-entry verification).
4. 'Delete Provision': 35 to 85 seconds.
5. Cluster/Session Pauses: Real human reading, cross-referencing & gazette study pauses
   naturally distribute the workload across the entire shift from start to end.
6. Zero timestamps during Lunch or Evening breaks.
"""

import io
import re
import datetime
import random
from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

TIMESTAMP_CANDIDATES = [
    "timestamp", "time", "date_time", "datetime", "log_time", "time_stamp",
    "date", "created_at", "updated_at", "modified_at", "action_time", "entry_time"
]

ACTION_CANDIDATES = [
    "action", "action_type", "operation", "activity", "type", "action type", "event"
]

ACT_CANDIDATES = [
    "act_name", "act", "act_title", "title", "actname", "law", "statute"
]

DESC_CANDIDATES = [
    "basic_description", "description", "desc", "details", "remark", "notes", "what is changed"
]


def parse_time_str(val):
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
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", val_str)
    if m:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return datetime.date.today()


def classify_action(action_str, desc_str=""):
    """
    Classifies a log row action into specific categories based on action type
    and description text.
    """
    t = (str(action_str or "") + " " + str(desc_str or "")).lower().strip()
    if "bulk delete" in t or "bulk clear" in t:
        return "bulk_delete"
    elif "delete" in t or "remove" in t:
        return "delete"
    elif "insert" in t or "add" in t or "new" in t:
        return "insert_provision"
    elif "edit" in t or "update" in t or "modify" in t or "merge" in t:
        return "edit_provision"
    elif "review" in t or "format" in t or "check" in t:
        return "review"
    return "default"


def detect_excel_info(file_bytes_or_path, sheet_name=None):
    if isinstance(file_bytes_or_path, (str, Path)):
        wb = openpyxl.load_workbook(file_bytes_or_path, read_only=True, data_only=True)
    else:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes_or_path), read_only=True, data_only=True)

    sheet_names = wb.sheetnames
    target_sheet = sheet_name if sheet_name in sheet_names else wb.active.title
    ws = wb[target_sheet]

    row_count = 0
    headers = []
    sample_rows = []
    detected_date = None

    for r_idx, row_values in enumerate(ws.iter_rows(values_only=True), start=1):
        if r_idx == 1:
            headers = [str(c).strip() if c is not None else f"Column_{i+1}" for i, c in enumerate(row_values)]
            continue

        if any(c is not None and str(c).strip() != "" for c in row_values):
            row_count += 1
            if len(sample_rows) < 10:
                sample_rows.append([str(c) if c is not None else "" for c in row_values])

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


def generate_action_realistic_timeline(
    target_date,
    shift_start,
    shift_end,
    breaks,
    row_actions,
    row_acts=None,
    mode="natural",
    start_buffer_minutes=8,
    end_buffer_minutes=8,
    random_seed=None
):
    """
    Action-aware human pace distribution:
    - Insert Provision: 5 to 22 seconds (rapid insertion)
    - Edit Provision: 20 to 52 seconds
    - Bulk Delete: 2.5 to 5.5 minutes (careful review)
    - Delete: 35 to 80 seconds
    - Natural reading / cross-reference pauses between clusters and act switches
      distribute the work authentically across the entire shift.
    """
    num_rows = len(row_actions)
    if num_rows <= 0:
        return []

    if random_seed is not None:
        rng = random.Random(random_seed)
    else:
        rng = random.Random()

    d_start = datetime.datetime.combine(target_date, shift_start) + datetime.timedelta(minutes=start_buffer_minutes)
    d_end = datetime.datetime.combine(target_date, shift_end) - datetime.timedelta(minutes=end_buffer_minutes)

    if d_start >= d_end:
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
        b_clip_s = max(d_start, b_dt_start)
        b_clip_e = min(d_end, b_dt_end)
        if b_clip_s < b_clip_e:
            clean_breaks.append((b_clip_s, b_clip_e))

    clean_breaks.sort(key=lambda x: x[0])

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

    # Active working segments
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
        return [segments[0][0] + datetime.timedelta(minutes=rng.randint(3, 8))]

    if mode == "uniform":
        # Strict uniform spacing
        step = total_working_sec / (num_rows + 1)
        offsets = [step * (i + 1) for i in range(num_rows)]
    else:
        # Natural Action-Aware Human Distribution
        types = [classify_action(a) for a in row_actions]

        intrinsic_gaps = []
        is_session_break = []

        rows_since_break = 0
        target_cluster_size = rng.randint(4, 8)

        for i in range(1, num_rows):
            cur_type = types[i]
            prev_act = str(row_acts[i - 1] or "").strip() if row_acts else ""
            cur_act = str(row_acts[i] or "").strip() if row_acts else ""
            act_changed = bool(prev_act and cur_act and prev_act.lower() != cur_act.lower())

            # 1. Realistic Action-based delay
            if cur_type == "bulk_delete":
                # Bulk delete: 2.5 to 5.5 minutes (150s to 330s)
                gap = rng.uniform(160.0, 330.0)
            elif cur_type == "delete":
                # Single delete: 35 to 80 seconds
                gap = rng.uniform(35.0, 80.0)
            elif cur_type == "insert_provision":
                # Rapid insertion: 5 to 22 seconds (5, 10, 15, 20s as requested)
                gap = rng.uniform(6.0, 22.0)
            elif cur_type == "edit_provision":
                # Edit: 20 to 52 seconds (20, 30-40, 50s as requested)
                gap = rng.uniform(20.0, 52.0)
            elif cur_type == "review":
                # Review / Format: 35 to 75 seconds
                gap = rng.uniform(35.0, 75.0)
            else:
                gap = rng.uniform(22.0, 48.0)

            # Add natural jitter
            gap += rng.uniform(-2.0, 3.5)
            gap = max(4.0, gap)

            intrinsic_gaps.append(gap)

        sum_intrinsic = sum(intrinsic_gaps)
        target_span = total_working_sec * 0.94
        extra_time = max(0.0, target_span - sum_intrinsic)

        # Distribute working sessions naturally across the day
        if num_rows <= 3:
            num_pauses = num_rows - 1
        else:
            num_pauses = max(2, min(num_rows - 1, int(num_rows / 3) + 1))

        is_session_break = [False] * (num_rows - 1)
        candidate_indices = []
        for i in range(1, num_rows):
            prev_act = str(row_acts[i - 1] or "").strip() if row_acts else ""
            cur_act = str(row_acts[i] or "").strip() if row_acts else ""
            if prev_act and cur_act and prev_act.lower() != cur_act.lower():
                is_session_break[i - 1] = True
            else:
                candidate_indices.append(i - 1)

        current_pauses = sum(1 for p in is_session_break if p)
        needed = max(0, num_pauses - current_pauses)
        if needed > 0 and candidate_indices:
            step = max(1, len(candidate_indices) // (needed + 1))
            for k in range(needed):
                idx = candidate_indices[min(len(candidate_indices) - 1, (k + 1) * step)]
                is_session_break[idx] = True

        actual_pauses = sum(1 for p in is_session_break if p)

        final_gaps = []
        if actual_pauses > 0 and extra_time > 0:
            break_weights = [rng.uniform(0.7, 1.3) for _ in range(actual_pauses)]
            sum_bw = sum(break_weights)
            break_additions = [(w / sum_bw) * extra_time for w in break_weights]
            b_idx = 0
            for i, g in enumerate(intrinsic_gaps):
                if is_session_break[i]:
                    final_gaps.append(g + break_additions[b_idx])
                    b_idx += 1
                else:
                    final_gaps.append(g)
        else:
            final_gaps = list(intrinsic_gaps)

        # Convert to cumulative offsets
        start_offset = min(180.0, total_working_sec * 0.02)
        offsets = [start_offset]
        cur_off = start_offset
        for g in final_gaps:
            cur_off += g
            offsets.append(cur_off)

    # Map each offset to actual datetime
    results = []
    for off in offsets:
        rem = off
        placed = False
        for (s_start, s_end), dur in zip(segments, durations):
            if rem <= dur:
                dt = s_start + datetime.timedelta(seconds=round(rem))
                results.append(dt)
                placed = True
                break
            else:
                rem -= dur
        if not placed:
            results.append(segments[-1][1] - datetime.timedelta(seconds=rng.randint(3, 10)))

    # Strictly guarantee ascending timestamps & zero timestamps during breaks
    clean_results = []
    prev_dt = None
    for dt in results:
        cur_dt = dt.replace(microsecond=0)
        if prev_dt is not None and cur_dt <= prev_dt:
            cur_dt = prev_dt + datetime.timedelta(seconds=rng.randint(5, 12))
        for bs, be in merged_breaks:
            if bs <= cur_dt <= be:
                cur_dt = be + datetime.timedelta(seconds=rng.randint(25, 75))
        clean_results.append(cur_dt)
        prev_dt = cur_dt

    return clean_results


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
    if isinstance(file_bytes_or_path, (str, Path)):
        wb = openpyxl.load_workbook(file_bytes_or_path)
    else:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes_or_path))

    target_sheet = sheet_name if sheet_name and sheet_name in wb.sheetnames else wb.active.title
    ws = wb[target_sheet]

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

    first_row = [cell.value for cell in ws[1]]
    total_cols = len(first_row)

    # Detect Columns
    ts_col_idx = 1
    action_col_idx = None
    act_col_idx = None
    desc_col_idx = None

    for idx, h in enumerate(first_row, start=1):
        if not h:
            continue
        clean_h = re.sub(r"[^a-zA-Z0-9]", "", str(h).lower())

        # Timestamp column
        if timestamp_col is not None:
            if isinstance(timestamp_col, int) and idx == timestamp_col:
                ts_col_idx = idx
            elif str(h).strip().lower() == str(timestamp_col).strip().lower():
                ts_col_idx = idx
        else:
            for cand in TIMESTAMP_CANDIDATES:
                if cand in clean_h:
                    ts_col_idx = idx
                    break

        # Action column
        if not action_col_idx:
            for cand in ACTION_CANDIDATES:
                if cand in clean_h:
                    action_col_idx = idx
                    break

        # Act Name column
        if not act_col_idx:
            for cand in ACT_CANDIDATES:
                if cand in clean_h:
                    act_col_idx = idx
                    break

        # Description column
        if not desc_col_idx:
            for cand in DESC_CANDIDATES:
                if cand in clean_h:
                    desc_col_idx = idx
                    break

    if ts_col_idx == 1 and total_cols >= 2 and timestamp_col is None:
        ts_col_idx = 2

    # Collect data rows and action details
    data_row_indices = []
    original_timestamps = []
    row_actions = []
    row_acts = []

    for r_idx in range(2, ws.max_row + 1):
        row_vals = [ws.cell(row=r_idx, column=c).value for c in range(1, total_cols + 1)]
        if any(v is not None and str(v).strip() != "" for v in row_vals):
            data_row_indices.append(r_idx)
            orig_ts = ws.cell(row=r_idx, column=ts_col_idx).value
            original_timestamps.append(str(orig_ts or "").strip())

            act_val = ws.cell(row=r_idx, column=action_col_idx).value if action_col_idx else ""
            desc_val = ws.cell(row=r_idx, column=desc_col_idx).value if desc_col_idx else ""
            act_name_val = ws.cell(row=r_idx, column=act_col_idx).value if act_col_idx else ""

            combined_action = f"{act_val or ''} {desc_val or ''}".strip()
            row_actions.append(combined_action or "default")
            row_acts.append(str(act_name_val or ""))

    num_rows = len(data_row_indices)
    if num_rows == 0:
        raise ValueError("No data rows found in the selected sheet to update.")

    # Generate action-realistic timestamps
    new_timestamps = generate_action_realistic_timeline(
        target_date=target_date,
        shift_start=shift_start,
        shift_end=shift_end,
        breaks=clean_breaks,
        row_actions=row_actions,
        row_acts=row_acts,
        mode=mode,
        start_buffer_minutes=start_buffer_minutes,
        end_buffer_minutes=end_buffer_minutes
    )

    # Strictly preserve the user's original Excel formatting, headers, styles, and column widths.
    # ONLY update the timestamp column value for data rows.
    for pos, r_idx in enumerate(data_row_indices):
        dt_val = new_timestamps[pos]
        dt_str = dt_val.strftime("%Y-%m-%d %H:%M:%S")
        ws.cell(row=r_idx, column=ts_col_idx).value = dt_str

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
