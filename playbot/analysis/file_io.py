import datetime as dt
import os
import pickle
from typing import Any, Tuple

from playbot.types import TimestampT

DATA_DIR = "data"


def _ts_to_disk(ts: Any) -> Any:
    """Convert datetime to ISO string for storage."""
    if isinstance(ts, dt.datetime):
        return ts.isoformat()
    return ts


def _ts_from_disk(ts: Any) -> Any:
    """Convert ISO string back to datetime if applicable."""
    if isinstance(ts, str):
        try:
            return dt.datetime.fromisoformat(ts)
        except ValueError:
            pass
    return ts


def load_dictionary(dict_name: str) -> Tuple[dict, TimestampT, TimestampT]:
    fname = os.path.join(DATA_DIR, f"{dict_name}.pkl")
    with open(fname, "rb") as f:
        payload = pickle.load(f)

    if not isinstance(payload, dict):
        raise ValueError(f"{dict_name}.pkl is not a dict")

    for k in ("data", "start_ts", "end_ts"):
        if k not in payload:
            raise ValueError(f"{dict_name}.pkl missing key '{k}'")

    return (
        payload["data"],
        _ts_from_disk(payload["start_ts"]),
        _ts_from_disk(payload["end_ts"]),
    )


def save_dictionary(
        dict_name: str,
        data: Any,
        start_ts: dt.datetime,
        end_ts: dt.datetime,
) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)

    payload = {
        "data": data,
        "start_ts": _ts_to_disk(start_ts),
        "end_ts": _ts_to_disk(end_ts),
    }

    fname = os.path.join(DATA_DIR, f"{dict_name}.pkl")
    tmp = fname + ".tmp"

    with open(tmp, "wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)

    os.replace(tmp, fname)


def merge_time_range(old_start, old_end, new_start, new_end):
    start = min(x for x in (old_start, new_start) if x is not None)
    end = max(x for x in (old_end, new_end) if x is not None)
    return start, end
