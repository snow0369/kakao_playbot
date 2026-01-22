from collections import defaultdict
from typing import Dict, List

from playbot.types import ReplyType


def bin_enhance_counts_by_gold(
        enhance_events: Dict[str, Dict[ReplyType, List[int]]],
        thresholds: List[int],
) -> List[Dict[str, Dict[ReplyType, int]]]:
    """
    thresholds = [th0, th1, ...] defines bins:
      bin 0: 0 <= bg < th0
      bin 1: th0 <= bg < th1
      ...
      bin K: th_{K-1} <= bg   (open-ended top bin)

    Returns:
      counts_per_bin: List[dict]
        counts_per_bin[b][weapon_name][ReplyType] = count
    """
    # Ensure thresholds are strictly increasing
    if any(thresholds[i] >= thresholds[i + 1] for i in range(len(thresholds) - 1)):
        raise ValueError("thresholds must be strictly increasing")

    # number of bins = len(thresholds) + 1 (top open-ended bin)
    num_bins = len(thresholds) + 1

    # Prepare list of nested dicts: bin -> weapon -> ReplyType -> count
    counts_per_bin: List[Dict[str, Dict["ReplyType", int]]] = [
        defaultdict(lambda: defaultdict(int)) for _ in range(num_bins)
    ]

    def _bin_index(bg: int) -> int:
        # returns the first i where bg < thresholds[i], else top bin
        for i, th in enumerate(thresholds):
            if bg < th:
                return i
        return len(thresholds)

    for weapon_name, by_type in enhance_events.items():
        for rtype, bg_list in by_type.items():
            # only consider the three enhancement outcomes
            if rtype not in (ReplyType.ENHANCE_SUCCESS, ReplyType.ENHANCE_KEEP, ReplyType.ENHANCE_BREAK):
                continue
            for bg in bg_list:
                b = _bin_index(int(bg))
                counts_per_bin[b][weapon_name][rtype] += 1

    # Convert defaultdicts to plain dicts (optional, but usually nicer to serialize)
    out: List[Dict[str, Dict[ReplyType, int]]] = []
    for bdict in counts_per_bin:
        out.append({w: dict(rt_counts) for w, rt_counts in bdict.items()})

    return out


def counts_to_probabilities(
        counts_per_bin: List[Dict[str, Dict["ReplyType", int]]]
) -> List[Dict[str, Dict["ReplyType", float]]]:
    """
    For each bin and weapon, convert counts to probabilities over
    {SUCCESS, KEEP, BREAK}. Missing types treated as 0.
    """
    out = []
    for bdict in counts_per_bin:
        pb = {}
        for weapon_name, c in bdict.items():
            s = c.get(ReplyType.ENHANCE_SUCCESS, 0)
            k = c.get(ReplyType.ENHANCE_KEEP, 0)
            br = c.get(ReplyType.ENHANCE_BREAK, 0)
            tot = s + k + br
            if tot == 0:
                continue
            pb[weapon_name] = {
                ReplyType.ENHANCE_SUCCESS: s / tot,
                ReplyType.ENHANCE_KEEP: k / tot,
                ReplyType.ENHANCE_BREAK: br / tot,
            }
        out.append(pb)
    return out

