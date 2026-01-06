import json
import platform
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request

from core.util.time_util import TIMEZONE_INFO

router = APIRouter()


def _read_heartbeat(path: Path) -> dict:
    if not path.exists():
        return {
            "exists": False,
            "path": str(path),
            "age_sec": None,
            "loop_lag_sec": None,
            "loop_lag_max_sec": None,
            "ts": None,
        }

    stat = path.stat()
    age_sec: float = max(0.0, datetime.now(tz=TIMEZONE_INFO).timestamp() - stat.st_mtime)

    info = {
        "exists": True,
        "path": str(path),
        "age_sec": round(age_sec, 3),
        "loop_lag_sec": None,
        "loop_lag_max_sec": None,
        "ts": None,
    }

    try:
        raw = path.read_text(encoding="utf-8").strip()
        obj = json.loads(raw)
        if isinstance(obj, dict):
            info["ts"] = obj.get("ts")
            info["loop_lag_sec"] = obj.get("loop_lag_sec")
            info["loop_lag_max_sec"] = obj.get("loop_lag_max_sec")
    except Exception:
        pass

    return info


@router.get("/health", summary="Health Check", description="Check if the API service is running normally")
async def health_check(request: Request):
    talos = request.app.state.talos
    hb_path_str = talos.heartbeat_path
    hb_max_age = float(talos.heartbeat_max_age_sec)

    heartbeat_info: dict
    unhealthy = False

    if not hb_path_str:
        heartbeat_info = {"enabled": False}
    else:
        hb_path = Path(hb_path_str)
        heartbeat_info: dict = _read_heartbeat(hb_path)
        unhealthy = (
            (heartbeat_info["exists"] is False)
            or (heartbeat_info["age_sec"] is None)
            or (heartbeat_info["age_sec"] > hb_max_age)
        )

    return {
        "status": "unhealthy" if unhealthy else "healthy",
        "timestamp": datetime.now(tz=TIMEZONE_INFO).isoformat(),
        "service": "Talos Device Management API",
        "version": "1.0.0",
        "python_version": platform.python_version(),
        "platform": platform.system(),
        "heartbeat": heartbeat_info,
        "thresholds": {"heartbeat_max_age_sec": hb_max_age},
    }


@router.get("/ping", summary="Ping", description="Simple connectivity test")
async def ping():
    return {"message": "pong"}
