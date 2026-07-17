import argparse

from mini_bdx_runtime.raw_imu import ImuCalibrator

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Calibrate the BNO055 IMU and print offsets for duck_config.json"
    )
    parser.add_argument("--upside_down", action="store_true")
    args = parser.parse_args()

    calibrator = ImuCalibrator(upside_down=args.upside_down)
    print("Move the robot around until the sensor reports it is calibrated ...")
    calib = calibrator.calibrate()

    print("")
    print('Add this to the "imu_calib" section of duck_config.json:')
    print(f'  "accelerometer": {list(calib.accelerometer)},')
    print(f'  "gyroscope": {list(calib.gyroscope)},')
    print(f'  "magnetometer": {list(calib.magnetometer)}')
