import threading

from pynput import keyboard


class StopFlag:
    def __init__(self, exit_key, pause_key):
        self._stop = False
        self._pause = False
        self._lock = threading.Lock()
        self.exit_key = exit_key
        self.pause_key = pause_key

    def set_stop(self):
        with self._lock:
            self._stop = True

    def is_stop_set(self) -> bool:
        with self._lock:
            return self._stop

    def set_pause(self):
        with self._lock:
            self._pause = True

    def unset_pause(self):
        with self._lock:
            self._pause = False

    def toggle_pause(self):
        with self._lock:
            self._pause = not self._pause

    def is_pause_set(self) -> bool:
        with self._lock:
            return self._pause


def start_emergency_listener(stop_flag: StopFlag):
    def on_press(key):
        if key == stop_flag.exit_key:
            stop_flag.set_stop()
            return False  # 리스너 종료
        if key == stop_flag.pause_key:
            stop_flag.toggle_pause()
            return True  # 리스너 종료 x

    listener = keyboard.Listener(on_press=on_press)
    listener.daemon = True
    listener.start()
    return listener
