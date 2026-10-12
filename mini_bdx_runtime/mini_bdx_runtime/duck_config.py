import json
import os
import sys

from mini_bdx_runtime import imu_orientation
from mini_bdx_runtime.raw_imu import ImuCalibration

HOME_DIR = os.path.expanduser("~")

# Zero offset for every joint, used when the config file has none.
DEFAULT_JOINTS_OFFSET = {
    "left_hip_yaw": 0.0,
    "left_hip_roll": 0.0,
    "left_hip_pitch": 0.0,
    "left_knee": 0.0,
    "left_ankle": 0.0,
    "neck_pitch": 0.0,
    "head_pitch": 0.0,
    "head_yaw": 0.0,
    "head_roll": 0.00,
    "right_hip_yaw": 0.0,
    "right_hip_roll": 0.0,
    "right_hip_pitch": 0.0,
    "right_knee": 0.0,
    "right_ankle": 0.0,
}


class DuckConfig:
    def __init__(
        self,
        config_json_path: str | None = f"{HOME_DIR}/duck_config.json",
        ignore_default: bool = False,
    ) -> None:
        """
        Looks for duck_config.json in the home directory by default.
        If not found, uses default values.
        """
        self.default = False
        try:
            if config_json_path:
                with open(config_json_path) as f:
                    self.json_config = json.load(f)
            else:
                self.json_config = {}
        except FileNotFoundError:
            print(
                f"Warning : didn't find the config json file at {config_json_path}, "
                "using default values"
            )
            self.json_config = {}
            self.default = True

        if config_json_path is None:
            print("Warning : didn't provide a config json path, using default values")
            self.default = True

        if self.default and not ignore_default:
            print("")
            print("")
            print("")
            print("")
            print("======")
            print(
                "WARNING : Running with default values probably won't work well. "
                "Please make a duck_config.json file and set the parameters."
            )
            res = input("Do you still want to run ? (y/N)")
            if res.lower() != "y":
                print("Exiting...")
                sys.exit(1)

        self.start_paused = self.json_config.get("start_paused", False)
        # The IMU in the robot frame, a rotation matrix (see imu_orientation.py).
        self.imu_orientation = imu_orientation.from_config(self.json_config)
        imu_calib_raw = self.json_config.get("imu_calib", {})
        accelerometer_calib = tuple(imu_calib_raw.get("accelerometer", [0, 0, 0]))
        gyroscope_calib = tuple(imu_calib_raw.get("gyroscope", [0, 0, 0]))
        magnetometer_calib = tuple(imu_calib_raw.get("magnetometer", [0, 0, 0]))
        self.imu_calib = ImuCalibration(accelerometer_calib, gyroscope_calib, magnetometer_calib)
        self.phase_frequency_factor_offset = self.json_config.get(
            "phase_frequency_factor_offset", 0.0
        )

        expression_features = self.json_config.get("expression_features", {})

        self.eyes = expression_features.get("eyes", False)
        self.projector = expression_features.get("projector", False)
        self.antennas = expression_features.get("antennas", False)
        self.speaker = expression_features.get("speaker", False)
        self.microphone = expression_features.get("microphone", False)
        self.camera = expression_features.get("camera", False)

        self.joints_offset = self.json_config.get("joints_offsets", dict(DEFAULT_JOINTS_OFFSET))
