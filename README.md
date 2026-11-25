# ⏱️ Log Timestamp Divider & ActMaster Release Hub

A high-performance web platform designed for team shift workload distribution, strict approval workflows, and ActMaster software release distribution.

---

## 🌟 Key Features

1. **Smart & Realistic Timestamp Division (`engine.py`)**:
   - **Action-Aware Pacing**: Dynamically adjusts intervals based on operation type:
     - *Insert Provision / Add*: Rapid 5 to 22 seconds pace.
     - *Edit Provision / Update*: Realistic 20 to 52 seconds modification pace.
     - *Bulk Delete / Clear*: Deliberate 2.5 to 5.5 minutes verification pace.
     - *Delete Provision*: 35 to 80 seconds.
   - **Zero Modification Guarantee**: 100% preservation of original Excel headers, cell styles, fonts, fills, borders, and column widths. Only the timestamp column in data rows is updated.
   - **Break Window Enforcement**: Zero timestamps are generated during Lunch or Tea breaks.
   - **Anti-Pattern Randomization**: Natural human cluster pauses prevent robotic or predictable time gaps.

2. **Strict Approval & Verification Workflow (`storage.py`)**:
   - **Preview Locked**: Interns/users can preview up to 50 sample rows.
   - **Download Protection**: Full Excel download is strictly locked until verified and approved by an Admin.
   - **Multi-Admin Dashboard**: Date-filtered approval queue for shift in-charges.
   - **Master Admin Portal (`kenil` / `canon`)**: Super-admin controls to add, update, or remove Admin accounts.

3. **ActMaster Software Zip Release Center**:
   - **Public 1-Click Downloads**: Team members can download the latest ActMaster software zip packages directly from the main navigation.
   - **Master Release Management**: Master Admin can upload new `.zip` updates with version notes and clean up obsolete releases.
   - **Live Upload Percentage**: Real-time progress bar shows upload percentage (`0%` to `100%`) with byte counter.

---

## 📁 Repository Structure

```text
Log_Timestamp_Divider/
├── data/                       # Local data store (requests, releases, config)
│   ├── admin_config.json       # Admin credentials store
│   ├── releases.json           # ActMaster zip release metadata
│   ├── requests.json           # User approval requests queue
│   ├── files/                  # Server-side generated Excel files (pending/approved)
│   └── releases/               # Uploaded ActMaster software zip archives
├── templates/
│   └── index.html              # Responsive single-page web interface
├── engine.py                   # Action-aware timeline calculation & Excel engine
├── server.py                   # FastAPI web server and REST API
├── storage.py                  # Storage & session authentication manager
├── requirements.txt            # Python dependencies
├── Procfile                    # Render.com deployment process file
├── render.yaml                 # Render infrastructure configuration
├── Dockerfile                  # Container deployment specification
└── README.md                   # Project documentation
```

---

## 🚀 Deployment & Local Running

### Local Run:
```bash
pip install -r requirements.txt
python server.py
```
Open `http://localhost:8899/` in your browser.

### Cloud Deployment:
Pre-configured for 1-click continuous deployment on **Render.com** linked to the GitHub repository:
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `python server.py --host 0.0.0.0 --port $PORT --no-browser`
