import re
from pathlib import Path
from typing import List

PATH_EXPORTED_CHAT = "chat_log/"

FILENAME_RE = re.compile(
    r"^Talk_(\d{4}\.\d{1,2}\.\d{1,2}\s+\d{1,2}:\d{2})-(\d+)\.txt$"
)


def collect_and_validate_files() -> List[str]:
    """
    Returns a list of filenames sorted by trailing number.
    Raises ValueError if datetime part differs.
    """
    folder = Path(PATH_EXPORTED_CHAT)
    records = []

    for p in folder.iterdir():
        if not p.is_file():
            continue

        m = FILENAME_RE.match(p.name)
        if not m:
            continue  # ignore unrelated files

        datetime_part = m.group(1)
        seq = int(m.group(2))
        records.append((datetime_part, seq, p.name))

    if not records:
        return []

    # Validate all datetime parts are identical
    datetime_set = {dt for dt, _, _ in records}
    if len(datetime_set) != 1:
        raise ValueError(
            f"Inconsistent datetime in filenames: {sorted(datetime_set)}"
        )

    # Sort by sequence number
    records.sort(key=lambda x: x[1])

    return [name for _, _, name in records]


def main():
    chat_files = collect_and_validate_files()

    for file_idx, fname in enumerate(chat_files):
        pass
