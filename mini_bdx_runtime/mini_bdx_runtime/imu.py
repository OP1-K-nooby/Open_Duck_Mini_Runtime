import contextlib
import os
import pickle
import sys
import time
from queue import Queue
from threading import Thread
from typing import Any

import adafruit_bno055
import board
import busio
import numpy as np
from scipy.spatial.transform import Rotation as R

# BNO055 axis remaps (x_axis, y_axis, z_axis, x_sign, y_sign, z_sign) for how the
# sensor is mounted. These differ from raw_imu's because this driver runs the
# sensor in IMUPLUS mode and consumes fused quaternions.
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
    adafruit_bno055.AXIS_REMAP_NEGATIVE,
    adafruit_bno055.AXIS_REMAP_POSITIVE,
    adafruit_bno055.AXIS_REMAP_POSITIVE,
)

# Delay to let the sensor settle after a mode switch, seconds.
MODE_SETTLE_S = 0.1
# Interval between calibration-status polls, seconds.
CALIBRATION_POLL_S = 0.1
# Persisted calibration offsets.
CALIB_FILE = "imu_calib_data.pkl"
# The worker only keeps the most recent sample.
SAMPLE_QUEUE_SIZE = 1
# Constant pitch offset applied on top of the user-supplied bias, degrees.
NOMINAL_PITCH_BIAS = 0


# TODO filter spikes
class Imu:
    def __init__(
        self,
        sampling_freq: int,
        user_pitch_bias: float = 0,
        calibrate: bool = False,
        upside_down: bool = True,
    ) -> None:
        self.sampling_freq = sampling_freq
        self.user_pitch_bias = user_pitch_bias
        self.calibrate = calibrate

        i2c = busio.I2C(board.SCL, board.SDA)
        self.imu = adafruit_bno055.BNO055_I2C(i2c)

        self.imu.mode = adafruit_bno055.IMUPLUS_MODE
        self.imu.axis_remap = AXIS_REMAP_UPSIDE_DOWN if upside_down else AXIS_REMAP_UPRIGHT

        self.pitch_bias = NOMINAL_PITCH_BIAS + self.user_pitch_bias

        if self.calibrate:
            self._run_calibration()

        if os.path.exists(CALIB_FILE):
            with open(CALIB_FILE, "rb") as f:
                imu_calib_data = pickle.load(f)
            self.imu.mode = adafruit_bno055.CONFIG_MODE
            time.sleep(MODE_SETTLE_S)
            self.imu.offsets_accelerometer = imu_calib_data["offsets_accelerometer"]
            self.imu.offsets_gyroscope = imu_calib_data["offsets_gyroscope"]
            self.imu.offsets_magnetometer = imu_calib_data["offsets_magnetometer"]
            self.imu.mode = adafruit_bno055.IMUPLUS_MODE
            time.sleep(MODE_SETTLE_S)
        else:
            print(f"{CALIB_FILE} not found")
            print("Imu is running uncalibrated")

        self.last_imu_data: Any = [0, 0, 0, 0]
        self.imu_queue: Queue = Queue(maxsize=SAMPLE_QUEUE_SIZE)
        Thread(target=self.imu_worker, daemon=True).start()

    def _run_calibration(self) -> None:
        """Poll until the sensor self-reports calibrated, persist offsets, exit."""
        self.imu.mode = adafruit_bno055.NDOF_MODE
        while not self.imu.calibrated:
            print("Calibration status: ", self.imu.calibration_status)
            print("Calibrated : ", self.imu.calibrated)
            time.sleep(CALIBRATION_POLL_S)
        print("CALIBRATION DONE")

        imu_calib_data = {
            "offsets_accelerometer": self.imu.offsets_accelerometer,
            "offsets_gyroscope": self.imu.offsets_gyroscope,
            "offsets_magnetometer": self.imu.offsets_magnetometer,
        }
        for k, v in imu_calib_data.items():
            print(k, v)

        with open(CALIB_FILE, "wb") as f:
            pickle.dump(imu_calib_data, f)
        print("Saved", CALIB_FILE)
        sys.exit()

    def imu_worker(self) -> None:
        while True:
            s = time.time()
            try:
                # imu returns scalar first
                raw_orientation = np.array(self.imu.quaternion).copy()  # quat
                euler = R.from_quat(raw_orientation, scalar_first=True).as_euler("xyz").copy()
            except Exception as e:
                print("[IMU]:", e)
                continue

            euler[1] -= np.deg2rad(self.pitch_bias)

            # gives scalar last, which is what isaac wants
            final_orientation_quat = R.from_euler("xyz", euler).as_quat()

            self.imu_queue.put(final_orientation_quat.copy())
            took = time.time() - s
            time.sleep(max(0, 1 / self.sampling_freq - took))

    def get_data(self, euler: bool = False, mat: bool = False) -> Any:
        with contextlib.suppress(Exception):
            self.last_imu_data = self.imu_queue.get(False)  # non blocking

        try:
            if not euler and not mat:
                return self.last_imu_data
            elif euler:
                return R.from_quat(self.last_imu_data).as_euler("xyz")
            elif mat:
                return R.from_quat(self.last_imu_data).as_matrix()

        except Exception as e:
            print("[IMU]: ", e)
            return None


if __name__ == "__main__":
    imu = Imu(50, calibrate=True, upside_down=False)
