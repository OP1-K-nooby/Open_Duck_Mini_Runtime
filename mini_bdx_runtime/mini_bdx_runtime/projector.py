import time

import board
import digitalio

PROJECTOR_GPIO = board.D25


class Projector:
    def __init__(self) -> None:
        self.project = digitalio.DigitalInOut(PROJECTOR_GPIO)
        self.project.direction = digitalio.Direction.OUTPUT
        self.on = False

    def switch(self) -> None:
        self.on = not self.on

        self.project.value = self.on

    def stop(self) -> None:
        self.project.value = False
        self.project.deinit()


if __name__ == "__main__":
    p = Projector()
    try:
        while True:
            p.switch()
            time.sleep(1)
    finally:
        p.stop()
