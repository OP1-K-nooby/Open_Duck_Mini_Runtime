"""Excite each servo of a suspended duck and record how it follows.

For actuator identification: one joint at a time, around the standing pose,
this sends steps (large ones for the dynamics, small ones for friction and
backlash) then a sine sweep, while the other joints hold. It reads that one
servo back as fast as the bus allows and records goal, present position and
present velocity per read (see mini_bdx_runtime.telemetry), along with the
latest IMU sample, to tell how still the torso was held.

The duck must hang with its feet free, and the walk must be stopped (it
owns the servo bus): sudo systemctl stop open-duck-walk.
"""

import argparse
import os
import shlex
import subprocess
import sys
import time

import numpy as np

from mini_bdx_runtime.duck_config import DuckConfig
from mini_bdx_runtime.raw_imu import Imu
from mini_bdx_runtime.rustypot_position_hwi import HWI
from mini_bdx_runtime.telemetry import TelemetryWriter

WALK_SERVICE = "open-duck-walk"

# Gains the walk uses (v2_rl_walk_mujoco.py: -p, HEAD_KP), so what is
# identified is the servo as it walks.
LEG_KP = 30
HEAD_KP = 8
HEAD_JOINTS = ("neck_pitch", "head_pitch", "head_yaw", "head_roll")

SETTLE_S = 1.0
# Offsets from init_pos, rad, each held STEP_HOLD_S.
STEPS = [0.2, 0.0, -0.2, 0.0, 0.04, 0.0, -0.04, 0.0]
STEP_HOLD_S = 0.8
# Logarithmic sine sweep.
CHIRP_AMPLITUDE = 0.08  # rad; 3 rad/s peak at the top frequency
CHIRP_F0, CHIRP_F1 = 0.3, 6.0  # Hz
CHIRP_S = 15.0
RETURN_S = 0.5

# Record segments.
SETTLE, STEP, CHIRP, RETURN = range(4)

# The BNO055 outputs gyro and accelerometer at 100 Hz in NDOF mode.
IMU_HZ = 100


def walk_service_args() -> dict[str, str]:
    """The walk service's --duck_config_path / --serial_port, if it has one."""
    try:
        out = subprocess.run(
            ["systemctl", "show", WALK_SERVICE, "-p", "ExecStart", "--value"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return {}
    # "{ path=... ; argv[]=/nix/store/.../open-duck-v2-rl-walk --x y ... ; ... }"
    argv = out.split("argv[]=", 1)[-1].split(" ;", 1)[0]
    words = shlex.split(argv)
    return {
        w[2:]: words[k + 1]
        for k, w in enumerate(words[:-1])
        if w in ("--duck_config_path", "--serial_port")
    }


def walk_is_running() -> bool:
    return (
        subprocess.run(
            ["systemctl", "is-active", "--quiet", WALK_SERVICE], check=False
        ).returncode
        == 0
    )


def signal(t: float) -> tuple[int, float]:
    """(segment, offset from init_pos) at t seconds into a joint's run."""
    if t < SETTLE_S:
        return SETTLE, 0.0
    t -= SETTLE_S
    if t < len(STEPS) * STEP_HOLD_S:
        return STEP, STEPS[int(t // STEP_HOLD_S)]
    t -= len(STEPS) * STEP_HOLD_S
    if t < CHIRP_S:
        k = np.log(CHIRP_F1 / CHIRP_F0) / CHIRP_S
        phase = 2 * np.pi * CHIRP_F0 * (np.exp(k * t) - 1) / k
        return CHIRP, CHIRP_AMPLITUDE * np.sin(phase)
    return RETURN, 0.0


JOINT_RUN_S = SETTLE_S + len(STEPS) * STEP_HOLD_S + CHIRP_S + RETURN_S


def main() -> None:
    service = walk_service_args()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--duck_config_path", default=service.get("duck_config_path"))
    parser.add_argument("--serial_port", default=service.get("serial_port", "/dev/ttyACM0"))
    parser.add_argument("--joints", nargs="+", help="joints to excite (default: all)")
    parser.add_argument(
        "--output_dir", default=os.path.expanduser("~/telemetry"), help="where to record"
    )
    parser.add_argument("--yes", action="store_true", help="don't ask whether it hangs free")
    # Another kp than the walk's tells the servo's gain apart from its
    # damping and inertia, which don't change with it.
    parser.add_argument("--kp", type=int, default=LEG_KP, help="firmware kp of the leg servos")
    parser.add_argument("--head_kp", type=int, default=HEAD_KP, help="firmware kp of the head")
    parser.add_argument("--kd", type=int, default=0, help="firmware kd of every servo")
    args = parser.parse_args()

    if walk_is_running():
        sys.exit(f"The walk is running; stop it first: sudo systemctl stop {WALK_SERVICE}")

    duck_config = (
        DuckConfig(config_json_path=args.duck_config_path)
        if args.duck_config_path
        else DuckConfig()
    )
    hwi = HWI(duck_config, args.serial_port)
    joints = list(hwi.joints.keys())
    selected = args.joints or joints
    unknown = sorted(set(selected) - set(joints))
    if unknown:
        sys.exit(f"Unknown joints {unknown}; known: {joints}")

    print(f"Exciting {len(selected)} joints, ~{len(selected) * JOINT_RUN_S / 60:.1f} min.")
    if not args.yes and input("Is the duck hanging with its feet free? [y/N] ").lower() != "y":
        sys.exit("Aborted.")

    kps = [args.head_kp if j in HEAD_JOINTS else args.kp for j in joints]
    kds = [args.kd] * len(joints)
    hwi.set_kps(kps)
    hwi.set_kds(kds)
    hwi.turn_on()

    imu = Imu(
        sampling_freq=IMU_HZ,
        orientation=duck_config.imu_orientation,
        calibration=duck_config.imu_calib,
    )

    base = os.path.join(args.output_dir, f"excite_{time.strftime('%Y%m%d_%H%M%S')}")
    rec = TelemetryWriter(
        base,
        [
            ("t", "f8", ()),
            ("joint", "u1", ()),  # index into meta.joints
            ("segment", "u1", ()),  # 0 settle, 1 step, 2 chirp, 3 return
            ("goal", "f4", ()),  # rad, without the joint's offset
            ("pos", "f4", ()),  # rad, present position, without the offset
            ("vel", "f4", ()),  # rad/s, present velocity
            ("ok", "u1", ()),  # 0: the read failed, pos/vel are NaN
            ("gyro", "f4", (3,)),  # rad/s, latest IMU sample, walk's axes
            ("accelero", "f4", (3,)),  # m/s^2
            ("imu_t", "f8", ()),  # when that IMU sample was read
        ],
        {
            "kind": "excitation",
            "joints": joints,
            "ids": [hwi.joints[j] for j in joints],
            "kps": kps,
            "kds": kds,
            "init_pos": [hwi.init_pos[j] for j in joints],
            "joints_offsets": hwi.joints_offsets,
            "steps": STEPS,
            "step_hold_s": STEP_HOLD_S,
            "chirp": {"amplitude": CHIRP_AMPLITUDE, "f0": CHIRP_F0, "f1": CHIRP_F1, "s": CHIRP_S},
            "settle_s": SETTLE_S,
            "return_s": RETURN_S,
            "imu_hz": IMU_HZ,
            "imu_orientation": duck_config.imu_orientation,
        },
    )
    print(f"Recording to {base}.bin")

    try:
        for name in selected:
            index = joints.index(name)
            motor_id = hwi.joints[name]
            offset = hwi.joints_offsets[name]
            init = hwi.init_pos[name]
            reads = failures = 0
            start = time.time()
            while (now := time.time()) - start < JOINT_RUN_S:
                segment, delta = signal(now - start)
                goal = init + delta
                try:
                    hwi.io.write_goal_position([motor_id], [goal + offset])
                    pos = hwi.io.read_present_position([motor_id])[0] - offset
                    vel = hwi.io.read_present_velocity([motor_id])[0]
                    ok = True
                except Exception:
                    pos = vel = float("nan")
                    ok = False
                    failures += 1
                reads += 1
                sample = imu.get_data()
                rec.write(
                    t=now,
                    joint=index,
                    segment=segment,
                    goal=goal,
                    pos=pos,
                    vel=vel,
                    ok=ok,
                    gyro=sample["gyro"],
                    accelero=sample["accelero"],
                    imu_t=sample["t"],
                )
            hwi.set_position(name, init)
            print(f"{name}: {reads / JOINT_RUN_S:.0f} reads/s, {failures} failed")
    except KeyboardInterrupt:
        print("Interrupted, back to the standing pose.")
    finally:
        hwi.set_position_all(dict(hwi.init_pos))
        rec.close()
    print(f"Done: {base}.bin. The servos hold the standing pose; restart the walk with")
    print(f"  sudo systemctl start {WALK_SERVICE}")


if __name__ == "__main__":
    main()
