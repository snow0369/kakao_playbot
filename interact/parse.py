import re
from dataclasses import dataclass
from typing import Optional, Literal

from utils import _norm


# =========================
# 파싱: 전체 텍스트에서 마지막 "결과성" 블록 추출
# =========================
ReplyType = Literal[
    "enhance_success", "enhance_keep", "enhance_break",
    "sell", "busy", "other_bot", "unknown"
]


@dataclass
class ReplyInfo:
    rtype: ReplyType
    gold: Optional[int] = None
    level: Optional[int] = None
    raw_block: str = ""


_busy_re = re.compile(r"강화\s*중이니\s*잠깐\s*기다리도록")

_gold_re = re.compile(r"(남은 골드|현재 보유 골드)\s*:\s*([\d,]+)G")
_success_arrow_re = re.compile(r"\+(\d+)\s*→\s*\+(\d+)")
_success_gain_re = re.compile(r"획득\s*검\s*:\s*\[\+(\d+)\]")
_keep_level_re = re.compile(r"\[\+(\d+)\].*레벨이 유지")
_sell_new_level_re = re.compile(r"새로운\s*검\s*획득\s*:\s*\[\+(\d+)\]")

# "결과 헤더"는 대체로 "@사용자 〖...〗" 형태
_result_header_re = re.compile(r"@\S+\s+〖[^〗]+〗", re.MULTILINE)


def _parse_gold(text: str) -> Optional[int]:
    m = _gold_re.search(text)
    if not m:
        return None
    return int(m.group(2).replace(",", ""))


def extract_last_result_block(full_text: str) -> str:
    """
    전체 텍스트에서 마지막 결과성 블록을 뽑는다.
    - 우선 busy 문구가 마지막에 있으면 그 주변 반환
    - 아니면 마지막 "@... 〖...〗" 이후 텍스트 전체 반환(파싱은 이 범위에서 수행)
    """
    t = _norm(full_text)
    if not t:
        return ""

    last_busy = None
    for m in _busy_re.finditer(t):
        last_busy = m

    headers = list(_result_header_re.finditer(t))
    last_header = headers[-1] if headers else None

    if last_busy and (last_header is None or last_busy.start() > last_header.start()):
        s = max(0, last_busy.start() - 120)
        e = min(len(t), last_busy.end() + 120)
        return t[s:e].strip()

    if not last_header:
        return ""

    return t[last_header.start():].strip()


def parse_result_block(block: str) -> ReplyInfo:
    b = _norm(block)
    info = ReplyInfo(rtype="unknown", raw_block=b)
    if not b:
        return info

    if _busy_re.search(b):
        info.rtype = "busy"
        return info

    info.gold = _parse_gold(b)

    # 판매
    if "검 판매" in b:
        info.rtype = "sell"
        m = _sell_new_level_re.search(b)
        if m:
            info.level = int(m.group(1))
        return info

    # 강화
    if "강화 성공" in b:
        info.rtype = "enhance_success"
        m = _success_arrow_re.search(b)
        if m:
            info.level = int(m.group(2))
            return info
        m2 = _success_gain_re.search(b)
        if m2:
            info.level = int(m2.group(1))
        return info

    if "강화 유지" in b:
        info.rtype = "enhance_keep"
        m = _keep_level_re.search(b)
        if m:
            info.level = int(m.group(1))
        else:
            m2 = re.search(r"\[\+(\d+)\]", b)
            if m2:
                info.level = int(m2.group(1))
        return info

    if "강화 파괴" in b:
        info.rtype = "enhance_break"
        info.level = 0
        return info

    # 봇의 기타 응답(예: "무슨 말을 하는겐가? ...")
    if "대장장이" in b or "감정사" in b:
        info.rtype = "other_bot"
        return info

    return info
