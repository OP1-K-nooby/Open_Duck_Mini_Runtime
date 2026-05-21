import adafruit_bno055
import board
import busio
import numpy as np
import os
import pickle

from queue import Queue
from threading import Thread
import time


from dataclasses import dataclass

@dataclass(frozen=True)
class ImuCalibration:
    accelerometer: tuple[int, int, int]
    gyroscope: tuple[int, int, int]
    magnetometer: tuple[int, int, int]


class ImuCalibrator:
    def __init__(self, upside_down=True):

        i2c = busio.I2C(board.SCL, board.SDA)
        self.imu = adafruit_bno055.BNO055_I2C(i2c)

        self.imu.mode = adafruit_bno055.NDOF_MODE

        if upside_down:
            self.imu.axis_remap = (
                adafruit_bno055.AXIS_REMAP_Y,
                adafruit_bno055.AXIS_REMAP_X,
                adafruit_bno055.AXIS_REMAP_Z,
                adafruit_bno055.AXIS_REMAP_NEGATIVE,
                adafruit_bno055.AXIS_REMAP_NEGATIVE,
                adafruit_bno055.AXIS_REMAP_NEGATIVE,
            )

        else:
            self.imu.axis_remap = (
                adafruit_bno055.AXIS_REMAP_Y,
                adafruit_bno055.AXIS_REMAP_X,
                adafruit_bno055.AXIS_REMAP_Z,
                adafruit_bno055.AXIS_REMAP_POSITIVE,
                adafruit_bno055.AXIS_REMAP_NEGATIVE,
                adafruit_bno055.AXIS_REMAP_POSITIVE,
            )
    
    def calibrate(self):
        calibrated = self.imu.calibrated
        while not calibrated:
            print("Calibration status: ", self.imu.calibration_status)
            print("Calibrated : ", self.imu.calibrated)
            calibrated = self.imu.calibrated
            time.sleep(0.1)
        print("CALIBRATION DONE")
        offsets_accelerometer = self.imu.offsets_accelerometer
        offsets_gyroscope = self.imu.offsets_gyroscope
        offsets_magnetometer = self.imu.offsets_magnetometer

        imu_calib = ImuCalib(self.imu.offsets_accelerometer, self.imu.offsets_gyroscope, self.imu.offsets_magnetometer)

        print(f"calibration: {imu_calib}")

        return imu_calib



# TODO filter spikes
class Imu:
    def __init__(
        self, sampling_freq, calibration=None, upside_down=True
    ):
        self.sampling_freq = sampling_freq

        i2c = busio.I2C(board.SCL, board.SDA)
        self.imu = adafruit_bno055.BNO055_I2C(i2c)

        self.imu.mode = adafruit_bno055.NDOF_MODE

        if upside_down:
            self.imu.axis_remap = (
                adafruit_bno055.AXIS_REMAP_Y,
                adafruit_bno055.AXIS_REMAP_X,
                adafruit_bno055.AXIS_REMAP_Z,
                adafruit_bno055.AXIS_REMAP_NEGATIVE,
                adafruit_bno055.AXIS_REMAP_NEGATIVE,
                adafruit_bno055.AXIS_REMAP_NEGATIVE,
            )

        else:
            self.imu.axis_remap = (
                adafruit_bno055.AXIS_REMAP_Y,
                adafruit_bno055.AXIS_REMAP_X,
                adafruit_bno055.AXIS_REMAP_Z,
                adafruit_bno055.AXIS_REMAP_POSITIVE,
                adafruit_bno055.AXIS_REMAP_NEGATIVE,
                adafruit_bno055.AXIS_REMAP_POSITIVE,
            )

        if calibration is not None:
            print("Using calibration data")
            self.imu.mode = adafruit_bno055.CONFIG_MODE
            time.sleep(0.1)
            print(f"accelerometer calibration: {calibration.accelerometer}")
            self.imu.offsets_accelerometer = calibration.accelerometer
            print(f"gyroscope calibration: {calibration.gyroscope}")
            self.imu.offsets_gyroscope = calibration.gyroscope
            print(f"magnetometer calibration: {calibration.magnetometer}")
            self.imu.offsets_magnetometer = calibration.magnetometer
            self.imu.mode = adafruit_bno055.NDOF_MODE
            time.sleep(0.1)
        else:
            print("Imu is running uncalibrated")

        self.x_offset = 0

        # self.tare_x()

        self.last_imu_data = [0, 0, 0, 0]
        self.last_imu_data = {
            "gyro": [0, 0, 0],
            "accelero": [0, 0, 0],
        }
        self.imu_queue = Queue(maxsize=1)
        Thread(target=self.imu_worker, daemon=True).start()

    def tare_x(self):
        print("Taring x ...")
        x_values = []
        num_values = 100
        ok = False
        while not ok:
            x_values.append(np.array(self.imu.acceleration)[0])

            x_values = x_values[-num_values:]

            if len(x_values) == num_values:
                mean = np.mean(x_values)
                std = np.std(x_values)
                if std < 0.05:
                    ok = True
                    self.x_offset = mean
                    print("Tare x done")
                else:
                    print(std)

            time.sleep(0.01)

    def imu_worker(self):
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

            accelero[0] -= self.x_offset

            data = {
                "gyro": gyro,
                "accelero": accelero,
            }
            self.imu_queue.put(data)
            took = time.time() - s
            time.sleep(max(0, 1 / self.sampling_freq - took))

    def get_data(self):
        try:
            self.last_imu_data = self.imu_queue.get(False)  # non blocking
        except Exception:
            pass

        return self.last_imu_data


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--upside_down", action="store_true")
    parser.add_argument("-a", "--accelerometer_offset", type=int, nargs=3, default=[0, 0, 0])
    parser.add_argument("-g", "--gyroscope_offset", type=int, nargs=3, default=[0, 0, 0])
    parser.add_argument("-m", "--magnetometer_offset", type=int, nargs=3, default=[0, 0, 0])

    args = parser.parse_args()

    imu_calib = ImuCalibration(
        tuple(args.accelerometer_offset),
        tuple(args.gyroscope_offset),
        tuple(args.magnetometer_offset),
    )

    if args.calibrate:
        calibrator = ImuCalibrator(upside_down=args.upside_down)
        imu_calib = calibrator.calibrate()

    imu = Imu(50, upside_down=False, calibration=imu_calib)
    while True:
        data = imu.get_data()
        # print(data)
        print("gyro", np.around(data["gyro"], 3))
        print("accelero", np.around(data["accelero"], 3))
        print("---")
        time.sleep(1 / 25)
