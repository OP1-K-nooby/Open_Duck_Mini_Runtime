"""How the IMU is mounted on the robot, as a rotation matrix.

The orientation R is that of the IMU in the robot frame: it takes a vector
measured in the IMU's axes to the robot's, v_robot = R @ v_imu. The robot frame
is the one the policy was trained in: x forward, y left, z up.

duck_config.json gives it under "imu_orientation", in exactly one of these
forms:

    "imu_orientation": {"rotation_matrix": [[0, 1, 0], [-1, 0, 0], [0, 0, 1]]}
    "imu_orientation": {"euler_deg": {"roll": 0, "pitch": 0, "yaw": -90}}
    "imu_orientation": {"quaternion": {"w": 0.7071, "x": 0, "y": 0, "z": -0.7071}}

Euler angles are intrinsic Z-Y'-X'' (yaw, then pitch, then roll), i.e.
R = Rz(yaw) @ Ry(pitch) @ Rx(roll).
"""

from typing import Any

import numpy as np

# Older configs said "imu_upside_down" instead. These are the BNO055 axis
# remaps that flag used to select, as rotations.
UPRIGHT = np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 1]], dtype=float)  # yaw -90
UPSIDE_DOWN = np.array([[0, -1, 0], [-1, 0, 0], [0, 0, -1]], dtype=float)  # roll 180, yaw -90

# How far from orthonormal a configured matrix may be (rounded decimals).
MATRIX_TOLERANCE = 1e-3


def from_euler_deg(roll: float, pitch: float, yaw: float) -> np.ndarray:
    r, p, y = np.radians([roll, pitch, yaw])
    rx = np.array([[1, 0, 0], [0, np.cos(r), -np.sin(r)], [0, np.sin(r), np.cos(r)]])
    ry = np.array([[np.cos(p), 0, np.sin(p)], [0, 1, 0], [-np.sin(p), 0, np.cos(p)]])
    rz = np.array([[np.cos(y), -np.sin(y), 0], [np.sin(y), np.cos(y), 0], [0, 0, 1]])
    return rz @ ry @ rx


def from_quaternion(w: float, x: float, y: float, z: float) -> np.ndarray:
    q = np.array([w, x, y, z], dtype=float)
    norm = np.linalg.norm(q)
    if norm == 0:
        raise ValueError("imu_orientation: the quaternion is zero")
    w, x, y, z = q / norm
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


def from_matrix(rows: Any) -> np.ndarray:
    m = np.array(rows, dtype=float)
    if m.shape != (3, 3):
        raise ValueError(f"imu_orientation: rotation_matrix must be 3x3, got {m.shape}")
    if not np.allclose(m @ m.T, np.eye(3), atol=MATRIX_TOLERANCE) or np.linalg.det(m) < 0:
        raise ValueError(
            "imu_orientation: rotation_matrix is not a rotation "
            "(rows must be orthonormal, determinant +1)"
        )
    return m


def from_config(json_config: dict[str, Any]) -> np.ndarray:
    """The IMU orientation a duck_config.json describes."""
    orientation = json_config.get("imu_orientation")
    if orientation is None:
        # The Open Duck Mini v2 mounting, which configs without the key had.
        return UPSIDE_DOWN if json_config.get("imu_upside_down", False) else UPRIGHT

    if "imu_upside_down" in json_config:
        print("Warning : imu_upside_down is ignored, imu_orientation is set")
    if len(orientation) != 1:
        raise ValueError(
            "imu_orientation: give exactly one of rotation_matrix, euler_deg, quaternion"
        )
    (kind, value), = orientation.items()
    if kind == "rotation_matrix":
        return from_matrix(value)
    if kind == "euler_deg":
        return from_euler_deg(value["roll"], value["pitch"], value["yaw"])
    if kind == "quaternion":
        return from_quaternion(value["w"], value["x"], value["y"], value["z"])
    raise ValueError(f"imu_orientation: unknown form {kind!r}")
