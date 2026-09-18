import contextlib
import time
from dataclasses import dataclass
from queue import Queue
from threading import Thread
from typing import Any

import adafruit_bno055
import board
import busio
import numpy as np

# BNO055 axis remaps (x_axis, y_axis, z_axis, x_sign, y_sign, z_sign) matching
# how the sensor is physically mounted on the robot.
AXIS_REMAP_UPSIDE_DOWN = (
    adafruit_bno055.AXIS_REMAP_Y,
    adafruit_bno055.AXIS_REMAP_X,
    adafruit_bno055.AXIS_REMAP_Z,
    adafruit_bno055.AXIS_REMAP_NEGATIVE,
    adafruit_bno055.AXIS_REMAP_NEGATIVE,
    adafruit_bno055.AXIS_REMAP_NEGATIVE,
)
AXIS_REMAP_UPRIGHT = (
    adafruit_bno055.AXIS_REMAP_Y,
    adafruit_bno055.AXIS_REMAP_X,
    adafruit_bno055.AXIS_REMAP_Z,
    adafruit_bno055.AXIS_REMAP_POSITIVE,
    adafruit_bno055.AXIS_REMAP_NEGATIVE,
    adafruit_bno055.AXIS_REMAP_POSITIVE,
)

# Delay to let the sensor settle after a mode switch, seconds.
MODE_SETTLE_S = 0.1
# Interval between calibration-status polls, seconds.
CALIBRATION_POLL_S = 0.1
# The worker only keeps the most recent sample.
SAMPLE_QUEUE_SIZE = 1


@dataclass(frozen=True)
class ImuCalibration:
    accelerometer: tuple[int, int, int]
    gyroscope: tuple[int, int, int]
    magnetometer: tuple[int, int, int]


def _init_bno055(upside_down: bool) -> adafruit_bno055.BNO055_I2C:
    """Create the BNO055 over I2C in NDOF mode with the mounting axis remap."""
    i2c = busio.I2C(board.SCL, board.SDA)
    imu = adafruit_bno055.BNO055_I2C(i2c)
    imu.mode = adafruit_bno055.NDOF_MODE
    imu.axis_remap = AXIS_REMAP_UPSIDE_DOWN if upside_down else AXIS_REMAP_UPRIGHT
    return imu


class ImuCalibrator:
    def __init__(self, upside_down: bool = True) -> None:
        self.imu = _init_bno055(upside_down)

    def calibrate(self) -> ImuCalibration:
        while not self.imu.calibrated:
            print("Calibration status: ", self.imu.calibration_status)
            print("Calibrated : ", self.imu.calibrated)
            time.sleep(CALIBRATION_POLL_S)
        print("CALIBRATION DONE")

        imu_calib = ImuCalibration(
            self.imu.offsets_accelerometer,
            self.imu.offsets_gyroscope,
            self.imu.offsets_magnetometer,
        )
        print(f"calibration: {imu_calib}")
        return imu_calib


# TODO filter spikes
class Imu:
    def __init__(
        self,
        sampling_freq: int,
        calibration: ImuCalibration | None = None,
        upside_down: bool = True,
    ) -> None:
        self.sampling_freq = sampling_freq
        self.imu = _init_bno055(upside_down)

        if calibration is not None:
            print("Using calibration data")
            self.imu.mode = adafruit_bno055.CONFIG_MODE
            time.sleep(MODE_SETTLE_S)
            print(f"accelerometer calibration: {calibration.accelerometer}")
            self.imu.offsets_accelerometer = calibration.accelerometer
            print(f"gyroscope calibration: {calibration.gyroscope}")
            self.imu.offsets_gyroscope = calibration.gyroscope
            print(f"magnetometer calibration: {calibration.magnetometer}")
            self.imu.offsets_magnetometer = calibration.magnetometer
            self.imu.mode = adafruit_bno055.NDOF_MODE
            time.sleep(MODE_SETTLE_S)
        else:
            print("Imu is running uncalibrated")

        self.last_imu_data: dict[str, Any] = {
            "gyro": [0, 0, 0],
            "accelero": [0, 0, 0],
        }
        self.imu_queue: Queue = Queue(maxsize=SAMPLE_QUEUE_SIZE)
        Thread(target=self.imu_worker, daemon=True).start()

    def imu_worker(self) -> None:
        while True:
            s = time.time()
            try:
                gyro = np.array(self.imu.gyro).copy()
                accelero = np.array(self.imu.acceleration).copy()
            except Exception as e:
                print("[IMU]:", e)
                continue

            if gyro is None or accelero is None:
                continue

            if gyro.any() is None or accelero.any() is None:
                continue

            data = {
                "gyro": gyro,
                "accelero": accelero,
            }
            self.imu_queue.put(data)
            took = time.time() - s
            time.sleep(max(0, 1 / self.sampling_freq - took))

    def get_data(self) -> dict[str, Any]:
        with contextlib.suppress(Exception):
            self.last_imu_data = self.imu_queue.get(False)  # non blocking

        return self.last_imu_data


if __name__ == "__main__":
    import argparse

    PRINT_PERIOD_S = 1 / 25

    parser = argparse.ArgumentParser()
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--upside_down", action="store_true")
    parser.add_argument("-a", "--accelerometer_offset", type=int, nargs=3)
    parser.add_argument("-g", "--gyroscope_offset", type=int, nargs=3)
    parser.add_argument("-m", "--magnetometer_offset", type=int, nargs=3)

    args = parser.parse_args()

    offsets = (args.accelerometer_offset, args.gyroscope_offset, args.magnetometer_offset)
    imu_calib: ImuCalibration | None = None
    if args.calibrate:
        calibrator = ImuCalibrator(upside_down=args.upside_down)
        imu_calib = calibrator.calibrate()
    elif any(o is not None for o in offsets):
        # Offsets not given default to zero; with none given, run uncalibrated.
        acc, gyro, mag = (tuple(o) if o is not None else (0, 0, 0) for o in offsets)
        imu_calib = ImuCalibration(acc, gyro, mag)

    imu = Imu(50, upside_down=args.upside_down, calibration=imu_calib)
    while True:
        data = imu.get_data()
        print("gyro", np.around(data["gyro"], 3))
        print("accelero", np.around(data["accelero"], 3))
        print("---")
        time.sleep(PRINT_PERIOD_S)
