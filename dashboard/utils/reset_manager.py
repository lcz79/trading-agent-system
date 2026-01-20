import os
import json
from datetime import datetime, timezone
from typing import Optional

from config import DATA_DIR, EQUITY_HISTORY_FILE, CLOSED_POSITIONS_FILE

RESET_STATE_FILE = os.path.join(DATA_DIR, "reset_state.json")


def _ensure_data_dir() -> None:
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_reset_date_iso() -> str:
    """
    Returns reset baseline timestamp as ISO string (UTC).
    If missing, initializes it to now (UTC).
    """
    _ensure_data_dir()
    if os.path.exists(RESET_STATE_FILE):
        try:
            with open(RESET_STATE_FILE, "r") as f:
                data = json.load(f) or {}
            iso = data.get("reset_date_iso")
            if iso:
                return str(iso)
        except Exception:
            pass

    iso = utc_now_iso()
    set_reset_date_iso(iso)
    return iso


def set_reset_date_iso(reset_date_iso: str) -> None:
    _ensure_data_dir()
    with open(RESET_STATE_FILE, "w") as f:
        json.dump({"reset_date_iso": reset_date_iso}, f, indent=2)


def _backup_file(path: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bak = f"{path}.bak_{ts}"
    try:
        with open(path, "rb") as src, open(bak, "wb") as dst:
            dst.write(src.read())
        return bak
    except Exception:
        return None


def reset_dashboard_local_data(reset_date_iso: Optional[str] = None) -> None:
    """
    Resets dashboard-local data and sets baseline timestamp.
    - Backs up existing JSON files
    - Clears equity_history.json & closed_positions.json
    - Stores reset_date_iso (UTC)
    """
    if reset_date_iso is None:
        reset_date_iso = utc_now_iso()

    _ensure_data_dir()

    _backup_file(EQUITY_HISTORY_FILE)
    _backup_file(CLOSED_POSITIONS_FILE)

    with open(EQUITY_HISTORY_FILE, "w") as f:
        json.dump([], f, indent=2)

    with open(CLOSED_POSITIONS_FILE, "w") as f:
        json.dump([], f, indent=2)

    set_reset_date_iso(reset_date_iso)
