from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


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
class WeaponInfo:  # TODO: Add hidden flag.
    level: int
    name: str  # 이름만(앞의 [+L] 제외)


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

    # 파괴 시: 파괴된 무기와 지급된 무기 (weapon_before/after로도 동일 정보가 들어가지만 명시 필드로도 제공)
    broken_weapon: Optional[WeaponInfo] = None
    granted_weapon: Optional[WeaponInfo] = None

    raw_main: Optional[str] = None  # 이벤트를 만든 "메인" 메시지
    raw_aux: Optional[str] = None  # 결합에 사용한 보조 메시지(파괴 공지 등)


class UserCommandTarget(str, Enum):
    BOT = "bot"
    MACRO = "macro"


class MacroAction(str, Enum):
    PAUSE = "중지"
    RESUME = "재개"


@dataclass(frozen=True)
class UserCommand:
    target: UserCommandTarget
    raw: str
    # BOT
    bot_command: Optional[str] = None
    # MACRO
    macro_action: Optional[MacroAction] = None
