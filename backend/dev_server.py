"""Local dev launcher: runs the app on SQLite without needing SQL Server.

Used by .claude/launch.json (preview) and handy for manual local demos:
    python evavo-quotation/backend/dev_server.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

os.environ.setdefault("EVAVO_DATABASE_URL", "sqlite:///./evavo_dev.db")
os.environ.setdefault(
    "EVAVO_SHEETS_DIR",
    os.path.abspath(os.path.join(HERE, "..", "..", "working excel sheet from clients")),
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8013, log_level="warning")
