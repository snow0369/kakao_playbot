import time
from typing import Tuple

from pynput import mouse

from interact.global_stop import StopFlag


def calibrate_click(name: str,
                    stop_flag: StopFlag,
                    timeout_sec: float = 120.0) -> Tuple[int, int]:
    print(f"\n[캘리브레이션] '{name}' 위치를 한 번 클릭하세요. ({str(stop_flag.exit_key)}: 종료)")
    pos_holder = {"pos": None}

    def on_click(x, y, button, pressed):
        if stop_flag.is_set():
            return False
        if pressed:
            pos_holder["pos"] = (int(x), int(y))
            return False

    t0 = time.time()
    with mouse.Listener(on_click=on_click) as mlistener:
        while mlistener.running:
            if stop_flag.is_set():
                break
            if time.time() - t0 > timeout_sec:
                break
            time.sleep(0.01)

    if stop_flag.is_set():
        raise SystemExit("키보드 비상 종료")

    if pos_holder["pos"] is None:
        raise TimeoutError(f"캘리브레이션 타임아웃: {name}")

    print(f"  -> {name} = {pos_holder['pos']}")
    return pos_holder["pos"]
