import logging

logger = logging.getLogger("Legacy_Util")


def extract_model_and_slave_id(snapshot_id: str) -> tuple[str, int]:
    parts = snapshot_id.rsplit("_", 1)
    if len(parts) != 2:
        return ("UNKNOWN", -1)
    return parts[0], int(parts[1])
