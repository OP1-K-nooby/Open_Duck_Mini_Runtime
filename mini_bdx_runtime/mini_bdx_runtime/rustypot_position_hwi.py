import time
from collections.abc import Sequence

import numpy as np
import rustypot

from mini_bdx_runtime.duck_config import DuckConfig

# Feetech STS3215 serial bus baud rate.
FEETECH_BAUDRATE = 1_000_000
# Default position-control gains applied to every joint.
DEFAULT_KP = 32
DEFAULT_KD = 0
# Reduced stiffness used while powering on, so the robot eases into its pose.
LOW_TORQUE_KP = 2
# Delay between the power-on stiffness steps, seconds.
TURN_ON_STEP_S = 1
# Decimal places the present position/velocity readings are rounded to.
ROUND_DECIMALS = 3


class HWI:
    def __init__(self, duck_config: DuckConfig, usb_port: str = "/dev/ttyACM0") -> None:
        self.duck_config = duck_config

        # Order matters here
        self.joints = {
            "left_hip_yaw": 20,
            "left_hip_roll": 21,
            "left_hip_pitch": 22,
            "left_knee": 23,
            "left_ankle": 24,
            "neck_pitch": 30,
            "head_pitch": 31,
            "head_yaw": 32,
            "head_roll": 33,
            # "left_antenna": None,
            # "right_antenna": None,
            "right_hip_yaw": 10,
            "right_hip_roll": 11,
            "right_hip_pitch": 12,
            "right_knee": 13,
            "right_ankle": 14,
        }

        self.zero_pos = {
            "left_hip_yaw": 0,
            "left_hip_roll": 0,
            "left_hip_pitch": 0,
            "left_knee": 0,
            "left_ankle": 0,
            "neck_pitch": 0,
            "head_pitch": 0,
            "head_yaw": 0,
            "head_roll": 0,
            # "left_antenna":0,
            # "right_antenna":0,
            "right_hip_yaw": 0,
            "right_hip_roll": 0,
            "right_hip_pitch": 0,
            "right_knee": 0,
            "right_ankle": 0,
        }

        self.init_pos = {
            "left_hip_yaw": 0.002,
            "left_hip_roll": 0.053,
            "left_hip_pitch": -0.63,
            "left_knee": 1.368,
            "left_ankle": -0.784,
            "neck_pitch": 0.0,
            "head_pitch": 0.0,
            "head_yaw": 0,
            "head_roll": 0,
            # "left_antenna": 0,
            # "right_antenna": 0,
            "right_hip_yaw": -0.003,
            "right_hip_roll": -0.065,
            "right_hip_pitch": 0.635,
            "right_knee": 1.379,
            "right_ankle": -0.796,
        }

        self.joints_offsets = self.duck_config.joints_offset

        self.kps = np.ones(len(self.joints)) * DEFAULT_KP
        self.kds = np.ones(len(self.joints)) * DEFAULT_KD
        self.low_torque_kps = np.ones(len(self.joints)) * LOW_TORQUE_KP

        self.io = rustypot.feetech(usb_port, FEETECH_BAUDRATE)

    def set_kps(self, kps) -> None:
        self.kps = kps
        self.io.set_kps(list(self.joints.values()), self.kps)

    def set_kds(self, kds) -> None:
        self.kds = kds
        self.io.set_kds(list(self.joints.values()), self.kds)

    def turn_on(self) -> None:
        self.io.set_kps(list(self.joints.values()), self.low_torque_kps)
        print("turn on : low KPS set")
        time.sleep(TURN_ON_STEP_S)

        self.set_position_all(self.init_pos)
        print("turn on : init pos set")

        time.sleep(TURN_ON_STEP_S)

        self.io.set_kps(list(self.joints.values()), self.kps)
        print("turn on : high kps")

    def turn_off(self) -> None:
        self.io.disable_torque(list(self.joints.values()))

    def set_position(self, joint_name: str, pos: float) -> None:
        """
        pos is in radians
        """
        motor_id = self.joints[joint_name]
        pos = pos + self.joints_offsets[joint_name]
        self.io.write_goal_position([motor_id], [pos])

    def set_position_all(self, joints_positions: dict[str, float]) -> None:
        """
        joints_positions is a dictionary with joint names as keys and joint positions as values
        Warning: expects radians
        """
        ids_positions = {
            self.joints[joint]: position + self.joints_offsets[joint]
            for joint, position in joints_positions.items()
        }

        self.io.write_goal_position(
            list(self.joints.values()), list(ids_positions.values())
        )

    def get_present_positions(self, ignore: Sequence[str] = ()) -> np.ndarray | None:
        """
        Returns the present positions in radians
        """
        try:
            present_positions = self.io.read_present_position(list(self.joints.values()))
        except Exception as e:
            print(e)
            return None

        present_positions = [
            pos - self.joints_offsets[joint]
            for joint, pos in zip(self.joints.keys(), present_positions, strict=True)
            if joint not in ignore
        ]
        return np.array(np.around(present_positions, ROUND_DECIMALS))

    def get_present_velocities(
        self, rad_s: bool = True, ignore: Sequence[str] = ()
    ) -> np.ndarray | None:
        """
        Returns the present velocities in rad/s (default) or rev/min
        """
        try:
            present_velocities = self.io.read_present_velocity(list(self.joints.values()))
        except Exception as e:
            print(e)
            return None

        present_velocities = [
            vel
            for joint, vel in zip(self.joints.keys(), present_velocities, strict=True)
            if joint not in ignore
        ]

        return np.array(np.around(present_velocities, ROUND_DECIMALS))
