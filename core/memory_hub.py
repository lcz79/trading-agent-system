import json, os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

MEM_PATH = "data/memory_hub.json"

def _load() -> Dict[str, Any]:
    try:
        with open(MEM_PATH, "r") as f: return json.load(f)
    except Exception: return {}

def _save(obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(MEM_PATH), exist_ok=True)
    with open(MEM_PATH, "w") as f: json.dump(obj, f, indent=2)

def publish(agent: str, key: str, data: Dict[str, Any]) -> None:
    mem = _load()
    mem.setdefault(agent, {})
    mem[agent][key] = {"data": data, "ts": datetime.now(timezone.utc).isoformat()}
    _save(mem)

def read_latest(agent: str, key: str) -> Optional[Dict[str, Any]]:
    mem = _load()
    try: return mem[agent][key]["data"]
    except Exception: return None

def read_agent(agent: str) -> Dict[str, Any]:
    mem = _load()
    return mem.get(agent, {})