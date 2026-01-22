import threading

from pynput import keyboard


class StopFlag:
    def __init__(self, exit_key):
        self._stop = False
        self._lock = threading.Lock()
        self.exit_key = exit_key

    def set(self):
        with self._lock:
            self._stop = True

    def is_set(self) -> bool:
        with self._lock:
            return self._stop


def start_emergency_listener(stop_flag: StopFlag):
    def on_press(key):
        if key == stop_flag.exit_key:
            stop_flag.set()
            return False  # 리스너 종료

    listener = keyboard.Listener(on_press=on_press)
    listener.daemon = True
    listener.start()
    return listener
