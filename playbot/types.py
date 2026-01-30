from __future__ import annotations

import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, List, Tuple

TimestampT = datetime.datetime


# =========================
# Data models
# =========================

class ReplyType(str, Enum):
    ENHANCE_SUCCESS = "enhance_success"
    ENHANCE_KEEP = "enhance_keep"
    ENHANCE_BREAK = "enhance_break"
    SELL = "sell"
    BUSY = "busy"
    INSUFFICIENT_GOLD = "insufficient_gold"


@dataclass(frozen=True)
class WeaponInfo:
    level: int
    name: str  # 이름만(앞의 [+L] 제외)
    id: Optional[int] = None


@dataclass(frozen=True)
class ReplyInfo:
    type: ReplyType

    # 공통
    gold_after: Optional[int] = None
    cost: Optional[int] = None  # 강화/파괴에서 사용 골드(-)
    reward: Optional[int] = None  # 판매 획득 골드(+)

    # 강화/판매 전후 무기 상태
    weapon_before: Optional[WeaponInfo] = None
    weapon_after: Optional[WeaponInfo] = None

    raw_main: Optional[str] = None  # 이벤트를 만든 "메인" 메시지
    raw_aux: Optional[str] = None  # 결합에 사용한 보조 메시지(파괴 공지 등)

    timestamp: Optional[TimestampT] = None


class UserCommandTarget(str, Enum):
    BOT = "bot"
    MACRO = "macro"


class MacroAction(str, Enum):
    PAUSE = "중지"
    RESUME = "재개"
    EXIT = "종료"


@dataclass(frozen=True)
class UserCommand:
    target: UserCommandTarget
    raw: str
    # BOT
    bot_command: Optional[str] = None
    # MACRO
    macro_action: Optional[MacroAction] = None

    timestamp: Optional[TimestampT] = None


# Raw data dictionaries
class RawData(str, Enum):
    UPGRADE_COST = "upgrade_cost"
    ENHANCE_EVENTS = "enhance_events"
    SELL_EVENTS = "sell_events"

# before weapon name -> ReplyType -> list[before_gold, timestamp]
EnhanceEvents = Dict[WeaponInfo, Dict[ReplyType, List[Tuple[int, TimestampT]]]]
# before weapon name -> list[sold_gold]
SellEvents = Dict[WeaponInfo, List[Tuple[int, TimestampT]]]


@dataclass(frozen=True)
class EnhanceCounts:
    n: int
    k_success: int
    k_keep: int
    k_break: int


@dataclass(frozen=True)
class EnhanceProbs:
    ps: float
    pk: float
    pb: float
    n: int


@dataclass(frozen=True)
class SellStats:
    mean: float
    std: float
    n: int
