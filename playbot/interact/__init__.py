import pyautogui as pag

from .calibrate import calibrate_click
from .global_stop import start_emergency_listener, StopFlag
from .response import select_all_copy_verified, send_command, send_log, get_last_sender,\
    wait_for_bot_turn
from .refresh import refresh_chat_window_safe

__all__ = [
    "calibrate_click",
    "start_emergency_listener", "StopFlag",
    "select_all_copy_verified", "send_command", "send_log", "get_last_sender", "wait_for_bot_turn",
    "refresh_chat_window_safe"
]

pag.FAILSAFE = True
pag.PAUSE = 0.05
