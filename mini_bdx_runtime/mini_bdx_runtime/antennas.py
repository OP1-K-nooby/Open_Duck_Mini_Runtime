import math
import time

import board
import pwmio

LEFT_ANTENNA_PIN = board.D13
RIGHT_ANTENNA_PIN = board.D12
LEFT_SIGN = 1
RIGHT_SIGN = -1
MIN_UPDATE_INTERVAL = 1 / 50  # 20ms

# Servo PWM parameters.
SERVO_FREQUENCY_HZ = 50
PWM_PERIOD_MS = 20  # 1 / SERVO_FREQUENCY_HZ, in ms
PWM_MAX_DUTY = 65535  # full 16-bit duty cycle
# A value in [-1, 1] maps linearly to a 1ms..2ms servo pulse.
NEUTRAL_PULSE_MS = 1.5
PULSE_HALF_RANGE_MS = 0.5
# Duty-cycle clamp corresponding to the safe pulse range for these servos.
MIN_DUTY_CYCLE = 3277
MAX_DUTY_CYCLE = 6553


def value_to_duty_cycle(v: float) -> int:
    pulse_width_ms = NEUTRAL_PULSE_MS + (v * PULSE_HALF_RANGE_MS)  # 1ms to 2ms
    duty_cycle = int((pulse_width_ms / PWM_PERIOD_MS) * PWM_MAX_DUTY)
    return min(max(duty_cycle, MIN_DUTY_CYCLE), MAX_DUTY_CYCLE)


class Antennas:
    def __init__(self) -> None:
        neutral_duty = value_to_duty_cycle(0)
        self.pwm_left = pwmio.PWMOut(
            LEFT_ANTENNA_PIN, frequency=SERVO_FREQUENCY_HZ, duty_cycle=neutral_duty
        )
        self.pwm_right = pwmio.PWMOut(
            RIGHT_ANTENNA_PIN, frequency=SERVO_FREQUENCY_HZ, duty_cycle=neutral_duty
        )

    def set_position_left(self, position: float) -> None:
        self.set_position(self.pwm_left, position, LEFT_SIGN)

    def set_position_right(self, position: float) -> None:
        self.set_position(self.pwm_right, position, RIGHT_SIGN)

    def set_position(self, pwm, value: float, sign: int = 1) -> None:
        if -1 <= value <= 1:
            # Convert value to duty cycle (1ms-2ms)
            duty_cycle = value_to_duty_cycle(value * sign)
            pwm.duty_cycle = duty_cycle
        else:
            print("Invalid input! Enter a value between -1 and 1.")

    def stop(self) -> None:
        time.sleep(MIN_UPDATE_INTERVAL)
        self.set_position_left(0)
        self.set_position_right(0)
        time.sleep(MIN_UPDATE_INTERVAL)
        self.pwm_left.deinit()
        self.pwm_right.deinit()


if __name__ == "__main__":
    antennas = Antennas()

    try:
        start_time = time.monotonic()
        current_time = start_time

        while current_time - start_time < 5:
            value = math.sin(2 * math.pi * 1 * current_time)
            antennas.set_position_left(value)
            antennas.set_position_right(value)
            time.sleep(MIN_UPDATE_INTERVAL)
            current_time = time.monotonic()

    finally:
        antennas.stop()
