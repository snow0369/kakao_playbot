import time

import pyautogui as pag

from .global_stop import StopFlag
from .response import select_all_copy_verified


def refresh_chat_window_safe(chat_text_xy_list, room_xy, input_xy,
                             bot_sender_name,
                             stop_flag: StopFlag,
                             settle_sec: float = 0.6, max_tries: int = 3):
    """
    리프레시 + 방 검증 통합 버전.
    max_tries만큼 재시도, 실패 시 RuntimeError.
    """
    chat_text_xy = chat_text_xy_list[0]
    for attempt in range(1, max_tries + 1):
        if stop_flag.is_stop_set():
            raise SystemExit("키보드 비상 종료")

        # 1) 대화 영역 포커스
        pag.click(*chat_text_xy)
        time.sleep(0.1)

        # 2) ESC (상태에 따라 한 번 더)
        pag.press("esc")
        time.sleep(settle_sec)

        # 3) 재오픈
        pag.doubleClick(*room_xy)
        time.sleep(settle_sec)

        # 4) 입력창 포커스
        pag.click(*input_xy)
        time.sleep(0.1)

        # 5) 검증
        if verify_room_opened(chat_text_xy_list, bot_sender_name, stop_flag):
            return  # 성공

        # 실패면 잠깐 쉬고 재시도
        time.sleep(0.4)

    raise RuntimeError("리프레시 후 방 검증 실패: 잘못된 대화방을 열었거나 좌표/포커스가 깨졌습니다.")


def verify_room_opened(chat_text_xy_list, bot_sender_name: str, stop_flag: StopFlag,
                       tail_lines: int = 80) -> bool:
    """
    리프레시 후 현재 열린 방이 맞는지 검증:
    - 채팅 전체 복사 후 마지막 tail_lines 라인에서 [플레이봇] 존재 여부 확인
    """
    if stop_flag.is_stop_set():
        raise SystemExit("키보드 비상 종료")

    full = select_all_copy_verified(chat_text_xy_list, stop_flag, retries=3)
    lines = (full or "").replace("\r\n", "\n").split("\n")
    tail = "\n".join(lines[-tail_lines:])

    return f"[{bot_sender_name}]" in tail
