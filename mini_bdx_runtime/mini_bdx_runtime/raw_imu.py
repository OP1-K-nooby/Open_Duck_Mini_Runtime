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
# Consecutive sensor-less samples (0.2 s at 50 Hz) before reconfiguring it.
RECOVER_AFTER_BAD_SAMPLES = 10

# Readings no walking duck produces, i.e. corrupted I2C transfers: the walk
# saw spikes of ~320 m/s^2 and ~35.5 rad/s (the gyro's 2000 dps full scale)
# where it otherwise stays under ~20 m/s^2 and ~3 rad/s.
ACCELERO_MAX_NORM = 6 * 9.81  # m/s^2; NDOF mode measures +/-4 g per axis
GYRO_MAX_NORM = 20.0  # rad/s, ~1150 deg/s
# How many rejected samples to print in full, to see what they look like.
PRINTED_SPIKES = 5


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


class Imu:
    def __init__(
        self,
        sampling_freq: int,
        calibration: ImuCalibration | None = None,
        upside_down: bool = True,
    ) -> None:
        self.sampling_freq = sampling_freq
        self.upside_down = upside_down
        self.calibration = calibration
        self.imu = _init_bno055(upside_down)
        self.apply_calibration()

        # Spikes dropped since the walk last looked; it resets the count.
        self.rejected_samples = 0
        self.printed_spikes = 0

        self.last_imu_data: dict[str, Any] = {
            "gyro": [0, 0, 0],
            "accelero": [0, 0, 0],
        }
        self.imu_queue: Queue = Queue(maxsize=SAMPLE_QUEUE_SIZE)
        Thread(target=self.imu_worker, daemon=True).start()

    def apply_calibration(self) -> None:
        if self.calibration is not None:
            print("Using calibration data")
            self.imu.mode = adafruit_bno055.CONFIG_MODE
            time.sleep(MODE_SETTLE_S)
            print(f"accelerometer calibration: {self.calibration.accelerometer}")
            self.imu.offsets_accelerometer = self.calibration.accelerometer
            print(f"gyroscope calibration: {self.calibration.gyroscope}")
            self.imu.offsets_gyroscope = self.calibration.gyroscope
            print(f"magnetometer calibration: {self.calibration.magnetometer}")
            self.imu.offsets_magnetometer = self.calibration.magnetometer
            self.imu.mode = adafruit_bno055.NDOF_MODE
            time.sleep(MODE_SETTLE_S)
        else:
            print("Imu is running uncalibrated")

    def recover(self) -> None:
        """Put a BNO055 that has fallen out of NDOF mode back to work.

        After a reset (e.g. a supply dip) the sensor boots in CONFIG mode,
        has lost its offsets and the driver reads (None, None, None).
        """
        try:
            print(f"[IMU]: sensor in mode {self.imu.mode:#x}, reconfiguring")
            self.imu.mode = adafruit_bno055.CONFIG_MODE
            time.sleep(MODE_SETTLE_S)
            self.imu.axis_remap = (
                AXIS_REMAP_UPSIDE_DOWN if self.upside_down else AXIS_REMAP_UPRIGHT
            )
            self.apply_calibration()
            self.imu.mode = adafruit_bno055.NDOF_MODE
            time.sleep(MODE_SETTLE_S)
        except Exception as e:
            print("[IMU]: reconfiguration failed:", e)

    def imu_worker(self) -> None:
        bad_samples = 0
        while True:
            s = time.time()
            try:
                gyro = self.imu.gyro
                accelero = self.imu.acceleration
            except Exception as e:
                print("[IMU]:", e)
                continue

            # The driver returns None components when the sensor is not in a
            # mode that measures them; never let those reach the policy.
            if None in gyro or None in accelero:
                bad_samples += 1
                if bad_samples == 1:
                    print("[IMU]: no data from the sensor")
                if bad_samples % RECOVER_AFTER_BAD_SAMPLES == 0:
                    self.recover()
                time.sleep(1 / self.sampling_freq)
                continue
            if bad_samples:
                print(f"[IMU]: data back after {bad_samples} bad samples")
                bad_samples = 0

            gyro = np.array(gyro)
            accelero = np.array(accelero)

            # Drop spikes; get_data() then keeps returning the last good
            # sample.
            if (
                np.linalg.norm(gyro) > GYRO_MAX_NORM
                or np.linalg.norm(accelero) > ACCELERO_MAX_NORM
            ):
                self.rejected_samples += 1
                if self.printed_spikes < PRINTED_SPIKES:
                    self.printed_spikes += 1
                    print(f"[IMU]: rejected spike gyro={gyro} accelero={accelero}")
                time.sleep(1 / self.sampling_freq)
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
