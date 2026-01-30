import math
from typing import Tuple

from playbot.types import EnhanceCounts, EnhanceProbs


def wilson_ci(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """
    Wilson score interval for binomial proportion.
    Returns (low, high). If n==0, returns (0.0, 0.0).
    """
    if n <= 0:
        return 0.0, 0.0
    phat = k / n
    denom = 1.0 + (z * z) / n
    center = (phat + (z * z) / (2 * n)) / denom
    half = (z / denom) * math.sqrt((phat * (1 - phat) / n) + (z * z) / (4 * n * n))
    low = max(0.0, center - half)
    high = min(1.0, center + half)
    return low, high


def wilson_halfwidth(k: int, n: int, z: float = 1.96) -> float:
    low, high = wilson_ci(k, n, z=z)
    return 0.5 * (high - low)


def counts_break_halfwidth(cnt: EnhanceCounts, z: float = 1.96) -> float:
    return wilson_halfwidth(cnt.k_break, cnt.n, z=z)


def counts_to_probs(cnt: EnhanceCounts) -> EnhanceProbs:
    if cnt.n <= 0:
        return EnhanceProbs(ps=1.0, pk=0.0, pb=0.0, n=0)  # fallback
    return EnhanceProbs(
        ps=cnt.k_success / cnt.n,
        pk=cnt.k_keep / cnt.n,
        pb=cnt.k_break / cnt.n,
        n=cnt.n,
    )
