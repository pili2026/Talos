import os
import re


def extract_retry_count(file_name: str) -> int:
    match = re.search(r"\.retry(\d+)\.json$", file_name)
    return int(match.group(1)) if match else 0


def increment_retry_name(file_name: str) -> str:
    retry_count = extract_retry_count(file_name)
    new_retry = retry_count + 1
    base_name = re.sub(r"\.retry\d+\.json$", "", file_name) if ".retry" in file_name else file_name.replace(".json", "")
    return f"{base_name}.retry{new_retry}.json"


def mark_as_fail(file_path: str) -> None:
    fail_path = re.sub(r"\.retry\d+\.json$|\.json$", ".fail", file_path)
    os.rename(file_path, fail_path)
