from __future__ import annotations

import os
from datetime import datetime
from typing import List, Optional, Sequence, Union

import matplotlib

from playbot.types import ReplyType, ReplyInfo

matplotlib.use("Agg")  # headless 안전 (원치 않으면 주석)
import matplotlib.pyplot as plt


TimestampLike = Union[datetime, str]


def _to_datetime(ts: Optional[TimestampLike]) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def filter_replies_by_time(
    replies: Sequence[ReplyInfo],
    *,
    start: Optional[TimestampLike] = None,
    end: Optional[TimestampLike] = None,
) -> List[ReplyInfo]:
    dt_start = _to_datetime(start)
    dt_end = _to_datetime(end)

    if dt_start is None and dt_end is None:
        return list(replies)

    out: List["ReplyInfo"] = []
    for r in replies:
        ts = getattr(r, "timestamp", None)
        if ts is None:
            continue
        if not isinstance(ts, datetime):
            try:
                ts = _to_datetime(str(ts))
            except Exception:
                continue

        if dt_start is not None and ts < dt_start:
            continue
        if dt_end is not None and ts > dt_end:
            continue
        out.append(r)
    return out


def _forward_fill(values: List[Optional[int]], *, initial: Optional[int] = None) -> List[Optional[int]]:
    out: List[Optional[int]] = []
    cur = initial
    for v in values:
        if v is not None:
            cur = v
            out.append(v)
        else:
            out.append(cur)
    return out


def _decimate_indices(n: int, max_points: int) -> List[int]:
    if n <= max_points:
        return list(range(n))
    step = n / max_points
    idx = [int(i * step) for i in range(max_points)]
    if idx[-1] != n - 1:
        idx.append(n - 1)
    out = []
    prev = None
    for i in idx:
        if i != prev:
            out.append(i)
            prev = i
    return out


def plot_gold_and_level_by_reply_index(
    replies: Sequence[ReplyInfo],
    save_path: str,
    *,
    start: Optional[TimestampLike] = None,
    end: Optional[TimestampLike] = None,
    initial_gold: Optional[int] = None,
    max_points: int = 100_000,
) -> None:
    """
    x축: reply index (필터 후 0..N-1)
    y축(왼쪽): gold_after (forward-fill)
    y축(오른쪽): SELL/BREAK 발생 시의 weapon level (line/scatter)

    - 레벨은 모든 reply에 대해 존재하지 않으므로:
      * base line은 NaN을 포함한 'sparse' level series로 그리고,
      * SELL/BREAK 지점은 따로 scatter로 강조
    - N이 커도 max_points로 다운샘플해서 라인 렌더링 부담을 줄임
    """
    data = filter_replies_by_time(replies, start=start, end=end)
    n = len(data)
    if n == 0:
        print("No replies to plot (after time filter).")
        return

    start = replies[0].timestamp
    end = replies[-1].timestamp

    # gold series
    gold_raw: List[Optional[int]] = []
    for r in data:
        ga = getattr(r, "gold_after", None)
        gold_raw.append(int(ga) if ga is not None else None)
    gold_ff = _forward_fill(gold_raw, initial=initial_gold)
    if all(v is None for v in gold_ff):
        print("All gold_after values are None; provide initial_gold or ensure gold_after exists.")
        return
    gold_y = [float(v) if v is not None else float("nan") for v in gold_ff]

    # level series: only defined at SELL/BREAK; elsewhere NaN
    lvl_y: List[float] = [float("nan")] * n
    sell_idx: List[int] = []
    sell_lvl: List[float] = []
    break_idx: List[int] = []
    break_lvl: List[float] = []

    for i, r in enumerate(data):
        rt = getattr(r, "type", None)

        if rt not in (ReplyType.SELL, ReplyType.ENHANCE_BREAK):
            continue

        wb = getattr(r, "weapon_before", None)
        wa = getattr(r, "weapon_after", None)

        lvl = None
        if wb is not None and getattr(wb, "level", None) is not None:
            lvl = int(wb.level)
        elif wa is not None and getattr(wa, "level", None) is not None:
            lvl = int(wa.level)

        if lvl is None:
            continue

        lvl_y[i] = float(lvl)

        if rt == ReplyType.SELL:
            sell_idx.append(i)
            sell_lvl.append(float(lvl))
        else:
            break_idx.append(i)
            break_lvl.append(float(lvl))

    # decimate indices for line plots
    line_idx = _decimate_indices(n, max_points)
    x_line = line_idx
    gold_line = [gold_y[i] for i in line_idx]
    lvl_line = [lvl_y[i] for i in line_idx]

    # plot with twin y-axis
    fig, ax_gold = plt.subplots(figsize=(14, 6))
    ax_lvl = ax_gold.twinx()

    ax_gold.plot(x_line, gold_line, linewidth=1.0, label="gold")

    # level series (sparse): line will be mostly broken; still conveys continuity of event levels
    ax_lvl.plot(x_line, lvl_line, linewidth=1.0, linestyle="--", label="level (SELL/BREAK)")

    # highlight events
    def _y_at(idxs: List[int], arr: List[float]) -> List[float]:
        return [arr[i] for i in idxs]

    if sell_idx:
        ax_lvl.scatter(sell_idx, sell_lvl, marker="o", s=18, label="SELL level")
    if break_idx:
        ax_lvl.scatter(break_idx, break_lvl, marker="x", s=28, label="BREAK level")

    def _fmt_for_filename(ts):
        if ts is None:
            return "NA"
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return ts.strftime("%Y%m%d_%H%M%S")

    start_str = _fmt_for_filename(start)
    end_str = _fmt_for_filename(end)

    # titles/labels
    title = "Gold (left) and Weapon Level at SELL/BREAK (right) vs Reply Index"
    if start is not None or end is not None:
        title += f" | {start or '-'} ~ {end or '-'}"
    ax_gold.set_title(title)
    ax_gold.set_xlabel("reply index")
    ax_gold.set_ylabel("gold")
    ax_lvl.set_ylabel("weapon level")

    # merge legends from both axes
    h1, l1 = ax_gold.get_legend_handles_labels()
    h2, l2 = ax_lvl.get_legend_handles_labels()
    ax_gold.legend(h1 + h2, l1 + l2, loc="best")

    fig.tight_layout()

    filename = f"history_{start_str}_{end_str}.png"
    plt.savefig(os.path.join(save_path, filename), dpi=300)
