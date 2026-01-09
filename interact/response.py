import re
import time
from typing import Optional

import pyperclip
import pyautogui as pag

from .global_stop import StopFlag
from utils import _norm


# =========================
# Ctrl+A / Ctrl+C 복사 (검증 + 재시도)
# =========================
def select_all_copy_verified(chat_text_xy,
                             stop_flag: StopFlag,
                             retries: int = 3) -> str:
    """
    채팅 로그의 '텍스트 위'를 클릭 -> Ctrl+A/Ctrl+C -> 클립보드 변화 검증.
    실패하면 재시도.
    """
    if stop_flag.is_set():
        raise SystemExit("키보드 비상 종료")

    sentinel = f"__SENTINEL_{time.time()}__"
    pyperclip.copy(sentinel)
    time.sleep(0.10)

    for _ in range(retries):
        if stop_flag.is_set():
            raise SystemExit("키보드 비상 종료")

        pag.click(*chat_text_xy)
        time.sleep(0.10)
        pag.hotkey("ctrl", "a")
        time.sleep(0.10)
        pag.hotkey("ctrl", "c")
        time.sleep(0.10)

        after = _norm(pyperclip.paste())
        if after and after != _norm(sentinel) and len(after) > 20:
            return after

        time.sleep(0.25)

    raise RuntimeError(
        "복사 실패: chat_text_xy가 채팅 '텍스트 위'가 아니거나, "
        "현재 카카오톡 상태에서 텍스트 선택/복사가 안 되는 상태입니다."
    )


# =========================
# 명령 전송 (멘션 더블클릭 + 한글 붙여넣기)
# =========================
def copy_input_text(input_xy, stop_flag: StopFlag, retries: int = 2) -> str:
    """
    입력창에 포커스를 주고 Ctrl+A/Ctrl+C로 '현재 작성 중인 문장'을 클립보드로 읽는다.
    """
    sentinel = f"__SENTINEL_{time.time()}__"
    pyperclip.copy(sentinel)
    time.sleep(0.02)

    for _ in range(retries):
        if stop_flag.is_set():
            raise SystemExit("키보드 비상 종료")

        pag.click(*input_xy)
        time.sleep(0.05)

        # Ctrl+A
        pag.keyDown("ctrl")
        time.sleep(0.02)
        pag.press("a")
        time.sleep(0.02)
        pag.keyUp("ctrl")
        time.sleep(0.05)

        # Ctrl+C
        pag.keyDown("ctrl")
        time.sleep(0.02)
        pag.press("c")
        time.sleep(0.02)
        pag.keyUp("ctrl")
        time.sleep(0.10)

        txt = (pyperclip.paste() or "").strip()
        if txt and txt != sentinel:
            return txt

        time.sleep(0.10)

    return (pyperclip.paste() or "").strip()


def send_command(input_xy,
                 mention_xy,
                 command: str,
                 bot_name: str,
                 stop_flag: StopFlag, ):
    """
    1) 입력창 클릭
    2) '@' 입력
    3) 멘션 더블클릭 시도
    4) 입력창 텍스트를 복사해 '@플레이봇' 포함 여부로 검증
    5) 성공 시 ' command' 붙여넣기 후 Enter
    6) 실패 시 backoff로 재시도
    """
    if stop_flag.is_set():
        raise SystemExit("키보드 비상 종료")

    target_token = f"@{bot_name}"

    # 멘션 후보가 늦게 뜨는 상황 대응: 대기 시간을 점증(backoff)
    delays = [0.25, 0.45, 0.70, 1.00, 1.40]  # 필요 시 늘려도 됨
    max_attempts = len(delays)

    for attempt in range(max_attempts):
        if stop_flag.is_set():
            raise SystemExit("F12 비상 종료")

        # 입력창 포커스 + 기존 입력 지우기(잔여 입력 방지)
        pag.click(*input_xy)
        time.sleep(0.05)
        pag.hotkey("ctrl", "a")
        time.sleep(0.02)
        pag.press("backspace")
        time.sleep(0.03)

        # '@' 입력 (ASCII)
        pag.typewrite("@", interval=0.01)
        time.sleep(delays[attempt])  # 후보 리스트 뜨는 대기

        # 멘션 더블클릭 (후보가 아직 안 떴어도 일단 시도)
        pag.doubleClick(*mention_xy)
        time.sleep(0.10)

        # 멘션이 실제로 입력됐는지 검증
        draft = copy_input_text(input_xy, stop_flag)
        if target_token in draft:
            # 멘션 확정 성공 -> 명령어 붙여넣기
            pag.click(*input_xy)
            time.sleep(0.02)
            pyperclip.copy(" " + command)
            pag.hotkey("ctrl", "v")
            time.sleep(0.03)
            pag.press("enter")
            return  # 성공 종료

        # 1차 보강: 후보가 이제 떴을 수 있으니 더블클릭 한 번 더
        pag.doubleClick(*mention_xy)
        time.sleep(0.10)
        draft = copy_input_text(input_xy, stop_flag)
        if target_token in draft:
            pag.click(*input_xy)
            time.sleep(0.02)
            pyperclip.copy(" " + command)
            pag.hotkey("ctrl", "v")
            time.sleep(0.03)
            pag.press("enter")
            return

        # 그래도 실패면 다음 attempt로 (대기시간 증가)
        # (선택) 후보 리스트가 떠있는 상태라면 ESC로 닫고 다음 루프
        pag.press("esc")
        time.sleep(0.05)

    # 여기까지 오면 멘션 자동완성이 안정적으로 안 잡힌 것
    raise RuntimeError(
        f"멘션 확정 실패: 입력창에서 '{target_token}'를 만들지 못했습니다. "
        "멘션 목록 위치(mention_xy) 또는 후보 표시 지연(delays)을 조정하세요."
    )


# =========================
# 마지막 발화자 판별 로직
# =========================
_sender_line_re = re.compile(r"^\[([^\]]+)\]\s*\[[^\]]+\]", re.MULTILINE)


def get_last_sender(full_text: str) -> Optional[str]:
    """
    Ctrl+A 복사 텍스트에서 마지막으로 등장하는 "[발화자] [오후 ...]" 라인의 발화자 반환
    """
    t = _norm(full_text)
    if not t:
        return None
    matches = list(_sender_line_re.finditer(t))
    if not matches:
        return None
    return matches[-1].group(1).strip()


# =========================
# 핵심 대기 로직: "마지막 발화자가 USER면 계속 대기"
# =========================
def wait_for_bot_turn(
        chat_text_xy,
        user_name,
        bot_sender_name,
        stop_flag: StopFlag,
        timeout_sec: float = 8.0,
        poll_interval: float = 0.35
) -> str:
    """
    Ctrl+A 복사 텍스트의 마지막 발화자가 USER_NAME이면 '아직 응답 미도착'으로 간주하고 계속 대기.
    마지막 발화자가 BOT_SENDER_NAME이면 반환.
    timeout이면 마지막으로 본 텍스트를 반환(상위에서 처리).
    """
    t0 = time.time()
    last_seen = ""

    while time.time() - t0 < timeout_sec:
        if stop_flag.is_set():
            raise SystemExit("키보드 비상 종료")

        full = select_all_copy_verified(chat_text_xy, stop_flag, retries=2)
        last_seen = full

        sender = get_last_sender(full)

        # 마지막이 사용자면 아직 응답이 완결되지 않았다고 보고 계속 기다림
        if sender == user_name:
            time.sleep(poll_interval)
            continue

        # 마지막이 봇이면 일단 봇 턴 도착
        if sender == bot_sender_name:
            return full

        # 그 외(예: 시스템 라인만 있거나 포맷 불일치) -> 조금 더 기다림
        time.sleep(poll_interval)

    return last_seen
