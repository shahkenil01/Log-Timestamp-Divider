#!/usr/bin/env python3
"""
Log Timestamp Divider - Desktop GUI Edition (Tkinter)
Allows selecting an Excel log file, configuring shift start/end and break timings,
previewing the timestamps, and generating a newly styled & distributed Excel file.
"""

import os
import sys
import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Ensure current dir is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from engine import detect_excel_info, distribute_excel_timestamps


class LogTimestampDividerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Log Timestamp Divider - Shift Work Time Distributor")
        self.root.geometry("820x720")
        self.root.minsize(750, 650)

        # Apply modern style theme
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        self.selected_file_path = None
        self.file_metadata = None

        self._build_ui()

    def _build_ui(self):
        # Header banner
        header_frame = tk.Frame(self.root, bg="#1155cc", height=70)
        header_frame.pack(fill=tk.X, side=tk.TOP)

        title_lbl = tk.Label(
            header_frame,
            text="⏱️ Log Timestamp Divider",
            font=("Segoe UI", 16, "bold"),
            bg="#1155cc",
            fg="#ffffff"
        )
        title_lbl.pack(anchor="w", padx=20, pady=(12, 2))

        sub_lbl = tk.Label(
            header_frame,
            text="Distribute daily log timestamps across shift hours with zero timestamps during breaks",
            font=("Segoe UI", 9),
            bg="#1155cc",
            fg="#dbeafe"
        )
        sub_lbl.pack(anchor="w", padx=20, pady=(0, 10))

        # Main scrollable or tabbed body
        main_frame = ttk.Frame(self.root, padding="16")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. File Selection Frame
        file_box = ttk.LabelFrame(main_frame, text=" 1. Excel File Selection ", padding="10")
        file_box.pack(fill=tk.X, pady=(0, 12))

        f_row = ttk.Frame(file_box)
        f_row.pack(fill=tk.X)

        self.file_path_var = tk.StringVar(value="No file selected")
        file_entry = ttk.Entry(f_row, textvariable=self.file_path_var, state="readonly")
        file_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        browse_btn = ttk.Button(f_row, text="Browse Excel...", command=self._browse_file)
        browse_btn.pack(side=tk.RIGHT)

        self.file_info_lbl = ttk.Label(file_box, text="Please select an Excel (.xlsx / .xls) file to begin.", foreground="#64748b")
        self.file_info_lbl.pack(anchor="w", pady=(6, 0))

        # 2. Timing Configuration Frame
        timing_box = ttk.LabelFrame(main_frame, text=" 2. Shift & Break Configuration ", padding="10")
        timing_box.pack(fill=tk.X, pady=(0, 12))

        # Date & Shift Start/End
        r1 = ttk.Frame(timing_box)
        r1.pack(fill=tk.X, pady=4)

        ttk.Label(r1, text="Work Date (YYYY-MM-DD):", width=22).pack(side=tk.LEFT)
        self.date_var = tk.StringVar(value=datetime.date.today().strftime("%Y-%m-%d"))
        ttk.Entry(r1, textvariable=self.date_var, width=15).pack(side=tk.LEFT, padx=(0, 20))

        ttk.Label(r1, text="Shift Start:", width=11).pack(side=tk.LEFT)
        self.shift_start_var = tk.StringVar(value="09:30")
        ttk.Entry(r1, textvariable=self.shift_start_var, width=10).pack(side=tk.LEFT, padx=(0, 15))

        ttk.Label(r1, text="Shift End:", width=10).pack(side=tk.LEFT)
        self.shift_end_var = tk.StringVar(value="18:30")
        ttk.Entry(r1, textvariable=self.shift_end_var, width=10).pack(side=tk.LEFT)

        # Lunch Break
        r2 = ttk.Frame(timing_box)
        r2.pack(fill=tk.X, pady=4)

        ttk.Label(r2, text="Lunch Break Start:", width=22).pack(side=tk.LEFT)
        self.lunch_start_var = tk.StringVar(value="13:00")
        ttk.Entry(r2, textvariable=self.lunch_start_var, width=15).pack(side=tk.LEFT, padx=(0, 20))

        ttk.Label(r2, text="Lunch End:", width=11).pack(side=tk.LEFT)
        self.lunch_end_var = tk.StringVar(value="14:00")
        ttk.Entry(r2, textvariable=self.lunch_end_var, width=10).pack(side=tk.LEFT)

        # Secondary Break (Tea Break)
        r3 = ttk.Frame(timing_box)
        r3.pack(fill=tk.X, pady=4)

        self.break2_enabled_var = tk.BooleanVar(value=False)
        b2_check = ttk.Checkbutton(r3, text="Enable Evening / Tea Break:", variable=self.break2_enabled_var, width=24)
        b2_check.pack(side=tk.LEFT)

        ttk.Label(r3, text="Start:").pack(side=tk.LEFT)
        self.break2_start_var = tk.StringVar(value="16:30")
        ttk.Entry(r3, textvariable=self.break2_start_var, width=10).pack(side=tk.LEFT, padx=(4, 15))

        ttk.Label(r3, text="End:").pack(side=tk.LEFT)
        self.break2_end_var = tk.StringVar(value="16:45")
        ttk.Entry(r3, textvariable=self.break2_end_var, width=10).pack(side=tk.LEFT)

        # Advanced options
        r4 = ttk.Frame(timing_box)
        r4.pack(fill=tk.X, pady=4)

        ttk.Label(r4, text="Timestamp Column:", width=22).pack(side=tk.LEFT)
        self.col_combo = ttk.Combobox(r4, state="readonly", width=18)
        self.col_combo.pack(side=tk.LEFT, padx=(0, 20))

        ttk.Label(r4, text="Pacing Mode:", width=12).pack(side=tk.LEFT)
        self.pacing_combo = ttk.Combobox(r4, state="readonly", values=["Realistic Human Pace", "Strict Equal Spacing"], width=18)
        self.pacing_combo.current(0)
        self.pacing_combo.pack(side=tk.LEFT)

        # Light Blue Theme Checkbox
        r5 = ttk.Frame(timing_box)
        r5.pack(fill=tk.X, pady=4)

        self.theme_var = tk.BooleanVar(value=True)
        theme_check = ttk.Checkbutton(
            r5,
            text="Apply Light Blue Theme (Dark Blue #1155CC header, alternate #E8F0FE rows & borders)",
            variable=self.theme_var
        )
        theme_check.pack(side=tk.LEFT)

        # 3. Preview & Action Frame
        action_frame = ttk.Frame(main_frame)
        action_frame.pack(fill=tk.X, pady=(0, 10))

        self.preview_btn = ttk.Button(action_frame, text="🔍 Preview Distribution", command=self._preview_distribution, state="disabled")
        self.preview_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.process_btn = ttk.Button(action_frame, text="⚡ Distribute & Save Excel...", command=self._process_and_save, state="disabled")
        self.process_btn.pack(side=tk.LEFT)

        self.stats_lbl = ttk.Label(action_frame, text="", font=("Segoe UI", 9, "bold"), foreground="#2563eb")
        self.stats_lbl.pack(side=tk.RIGHT)

        # 4. Preview Table
        preview_box = ttk.LabelFrame(main_frame, text=" 3. Timestamp Comparison Preview ", padding="8")
        preview_box.pack(fill=tk.BOTH, expand=True)

        columns = ("row", "original", "new")
        self.tree = ttk.Treeview(preview_box, columns=columns, show="headings", height=8)
        self.tree.heading("row", text="Row #")
        self.tree.heading("original", text="Original Timestamp")
        self.tree.heading("new", text="Distributed New Timestamp")

        self.tree.column("row", width=70, anchor="center")
        self.tree.column("original", width=260, anchor="w")
        self.tree.column("new", width=260, anchor="w")

        scrollbar = ttk.Scrollbar(preview_box, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _browse_file(self):
        f = filedialog.askopenfilename(
            title="Select Excel Log File",
            filetypes=[("Excel Files", "*.xlsx *.xls")]
        )
        if not f:
            return

        self.selected_file_path = f
        self.file_path_var.set(f)

        try:
            info = detect_excel_info(f)
            self.file_metadata = info
            self.file_info_lbl.config(
                text=f"Total Data Rows: {info['total_rows']} | Sheet: '{info['active_sheet']}' | Detected Date: {info['detected_date']}",
                foreground="#0f172a"
            )
            self.date_var.set(info['detected_date'])

            # Set column choices
            self.col_combo["values"] = info["headers"]
            if info["timestamp_col_name"] in info["headers"]:
                self.col_combo.set(info["timestamp_col_name"])
            elif info["headers"]:
                self.col_combo.current(min(1, len(info["headers"]) - 1))

            self.preview_btn.config(state="normal")
            self.process_btn.config(state="normal")
            self._preview_distribution()
        except Exception as exc:
            messagebox.showerror("Error Reading Excel", str(exc))

    def _get_breaks(self):
        breaks = [(self.lunch_start_var.get().strip(), self.lunch_end_var.get().strip())]
        if self.break2_enabled_var.get():
            breaks.append((self.break2_start_var.get().strip(), self.break2_end_var.get().strip()))
        return breaks

    def _preview_distribution(self):
        if not self.selected_file_path:
            return

        mode = "natural" if self.pacing_combo.current() == 0 else "uniform"
        try:
            stats, _ = distribute_excel_timestamps(
                file_bytes_or_path=self.selected_file_path,
                target_date_str=self.date_var.get().strip(),
                shift_start_str=self.shift_start_var.get().strip(),
                shift_end_str=self.shift_end_var.get().strip(),
                breaks_list=self._get_breaks(),
                timestamp_col=self.col_combo.get().strip() or None,
                mode=mode,
                apply_light_blue_theme=self.theme_var.get()
            )

            self.stats_lbl.config(
                text=f"Rows: {stats['num_rows']} | Work: {stats['working_hours']}h | Avg: {stats['avg_minutes_per_log']}m/log"
            )

            # Clear tree
            for item in self.tree.get_children():
                self.tree.delete(item)

            for comp in stats["preview_comparisons"]:
                self.tree.insert("", tk.END, values=(comp["row_num"], comp["original"] or "—", comp["new"]))

        except Exception as exc:
            messagebox.showerror("Preview Error", str(exc))

    def _process_and_save(self):
        if not self.selected_file_path:
            return

        default_out = Path(self.selected_file_path).stem + f"_divided_{self.date_var.get().strip()}.xlsx"
        save_path = filedialog.asksaveasfilename(
            title="Save Distributed Excel File",
            initialfile=default_out,
            defaultextension=".xlsx",
            filetypes=[("Excel Workbook", "*.xlsx")]
        )
        if not save_path:
            return

        mode = "natural" if self.pacing_combo.current() == 0 else "uniform"
        try:
            stats, out_p = distribute_excel_timestamps(
                file_bytes_or_path=self.selected_file_path,
                target_date_str=self.date_var.get().strip(),
                shift_start_str=self.shift_start_var.get().strip(),
                shift_end_str=self.shift_end_var.get().strip(),
                breaks_list=self._get_breaks(),
                timestamp_col=self.col_combo.get().strip() or None,
                mode=mode,
                apply_light_blue_theme=self.theme_var.get(),
                output_path=save_path
            )

            messagebox.showinfo(
                "Success!",
                f"Successfully divided {stats['num_rows']} timestamps!\n\n"
                f"• Target Date: {stats['target_date']}\n"
                f"• First Log: {stats['first_timestamp']}\n"
                f"• Last Log: {stats['last_timestamp']}\n"
                f"• Net Work Hours: {stats['working_hours']} hours\n"
                f"• Output File: {Path(save_path).name}"
            )
        except Exception as exc:
            messagebox.showerror("Processing Failed", str(exc))


if __name__ == "__main__":
    root = tk.Tk()
    app = LogTimestampDividerGUI(root)
    root.mainloop()
