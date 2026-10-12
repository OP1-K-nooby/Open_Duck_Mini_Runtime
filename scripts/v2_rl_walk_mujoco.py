import os
import pickle
import sys
import time

# pygame imports pkg_resources only to find its own data files, and does
# without it when the import fails. On a Pi Zero that import alone costs
# seconds of every start, and of every restart after a servo drop-out.
sys.modules["pkg_resources"] = None

import numpy as np
from mini_bdx_runtime.antennas import Antennas
from mini_bdx_runtime.duck_config import DuckConfig
from mini_bdx_runtime.eyes import Eyes
from mini_bdx_runtime.feet_contacts import FeetContacts
from mini_bdx_runtime.onnx_infer import OnnxInfer
from mini_bdx_runtime.poly_reference_motion import PolyReferenceMotion
from mini_bdx_runtime.projector import Projector
from mini_bdx_runtime.raw_imu import Imu
from mini_bdx_runtime.rl_utils import LowPassActionFilter, make_action_dict
from mini_bdx_runtime.rustypot_position_hwi import HWI
from mini_bdx_runtime.sounds import Sounds
from mini_bdx_runtime.xbox_controller import XBoxController

HOME_DIR = os.path.expanduser("~")
# Resolve bundled data next to this file, not the working directory.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(SCRIPT_DIR, "..", "mini_bdx_runtime", "assets")

# Number of actuated leg/head DOFs the policy controls (antennas excluded).
NUM_DOFS = 14
# Scale applied to joint velocities in the observation vector.
DOF_VEL_OBS_SCALE = 0.05

# Control defaults.
DEFAULT_PID = (30, 0, 0)
DEFAULT_ACTION_SCALE = 0.25
DEFAULT_CONTROL_FREQ = 50
COMMAND_FREQ = 20  # hz

# The head joints (obs indices 5:9) run at a softer proportional gain.
HEAD_KP = 8
HEAD_JOINT_SLICE = slice(5, 9)

# Timing.
STARTUP_SETTLE_S = 0.5  # the power-on ramp already ends in the standing pose
PAUSE_POLL_S = 0.1
FILTER_WARMUP_S = 1  # let the low-pass filter stabilize before trusting it
STATS_PERIOD_S = 1  # how often the walk logs a summary of what it commands
# Give up when the servos have not answered for this long: the board has
# dropped off USB or stopped talking, and only reopening the port brings it
# back. Exiting lets systemd restart the walk; looping on would leave the
# servos frozen on their last target.
SERVO_LOSS_S = 0.5

# Safety bounds on the motor targets sent to the servos.
# Twice the 5.24 rad/s upstream once used: at 5.24 a normal walk had up to 120
# targets a second clipped. The policy's actions are bounded, so the targets
# jump at most 2 * action_scale (0.5 rad) in a step; this only trims the
# largest jumps, which the servos could not follow anyway.
DEFAULT_MAX_MOTOR_VELOCITY = 10.5  # rad/s, how fast a target may move
DEFAULT_MAX_TARGET_OFFSET = 1.0  # rad, how far a target may stray from init_pos

# Gamepad-driven phase-frequency tuning.
PHASE_FREQ_OFFSET_STEP = 0.05
PHASE_FREQ_FACTOR_RUN = 1.3  # while LB is held
PHASE_FREQ_FACTOR_IDLE = 1.0


class RLWalk:
    def __init__(
        self,
        onnx_model_path: str,
        duck_config_path: str = f"{HOME_DIR}/duck_config.json",
        serial_port: str = "/dev/ttyACM0",
        control_freq: float = DEFAULT_CONTROL_FREQ,
        pid: tuple | list = DEFAULT_PID,
        action_scale: float = DEFAULT_ACTION_SCALE,
        commands: bool = False,
        pitch_bias: float = 0,
        save_obs: bool = False,
        replay_obs: str | None = None,
        cutoff_frequency: float | None = None,
        max_target_offset: float = DEFAULT_MAX_TARGET_OFFSET,
        max_motor_velocity: float = DEFAULT_MAX_MOTOR_VELOCITY,
    ) -> None:
        self.duck_config = DuckConfig(config_json_path=duck_config_path)

        self.commands = commands
        self.pitch_bias = pitch_bias

        self.onnx_model_path = onnx_model_path
        self.policy = OnnxInfer(self.onnx_model_path, awd=True)

        self.num_dofs = NUM_DOFS
        self.max_motor_velocity = max_motor_velocity
        self.max_target_offset = max_target_offset

        # Control
        self.control_freq = control_freq
        self.pid = pid

        self.save_obs = save_obs
        if self.save_obs:
            self.saved_obs: list = []

        self.replay_obs = replay_obs
        if self.replay_obs is not None:
            with open(self.replay_obs, "rb") as f:
                self.replay_obs = pickle.load(f)

        self.action_filter = None
        if cutoff_frequency is not None:
            self.action_filter = LowPassActionFilter(
                self.control_freq, cutoff_frequency
            )

        self.hwi = HWI(self.duck_config, serial_port)

        self.start()

        self.imu = Imu(
            sampling_freq=int(self.control_freq),
            orientation=self.duck_config.imu_orientation,
            calibration = self.duck_config.imu_calib,
        )

        self.feet_contacts = FeetContacts()

        # Scales
        self.action_scale = action_scale

        self.last_action = np.zeros(self.num_dofs)
        self.last_last_action = np.zeros(self.num_dofs)
        self.last_last_last_action = np.zeros(self.num_dofs)

        self.init_pos = list(self.hwi.init_pos.values())
        self.target_low = np.array(self.init_pos) - self.max_target_offset
        self.target_high = np.array(self.init_pos) + self.max_target_offset

        self.motor_targets = np.array(self.init_pos.copy())
        self.prev_motor_targets = np.array(self.init_pos.copy())

        self.last_commands = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        self.paused = self.duck_config.start_paused

        self.reset_stats()

        self.command_freq = COMMAND_FREQ
        if self.commands:
            self.xbox_controller = XBoxController(self.command_freq)

        # Reference motion, but we only really need the length of one phase
        # TODO
        self.PRM = PolyReferenceMotion(os.path.join(SCRIPT_DIR, "polynomial_coefficients.pkl"))
        self.imitation_i = 0
        self.imitation_phase = np.array([0, 0])
        self.phase_frequency_factor = 1.0
        self.phase_frequency_factor_offset = (
            self.duck_config.phase_frequency_factor_offset
        )

        # Optional expression features
        if self.duck_config.eyes:
            self.eyes = Eyes()
        if self.duck_config.projector:
            self.projector = Projector()
        if self.duck_config.speaker:
            self.sounds = Sounds(volume=1.0, sound_directory=ASSETS_DIR)
        if self.duck_config.antennas:
            self.antennas = Antennas()

    def get_obs(self) -> np.ndarray | None:
        imu_data = self.imu.get_data()

        dof_pos = self.hwi.get_present_positions(
            ignore=[
                "left_antenna",
                "right_antenna",
            ]
        )  # rad

        dof_vel = self.hwi.get_present_velocities(
            ignore=[
                "left_antenna",
                "right_antenna",
            ]
        )  # rad/s

        if dof_pos is None or dof_vel is None:
            return None
        self.last_servo_read_t = time.time()

        if len(dof_pos) != self.num_dofs:
            print(f"ERROR len(dof_pos) != {self.num_dofs}")
            return None

        if len(dof_vel) != self.num_dofs:
            print(f"ERROR len(dof_vel) != {self.num_dofs}")
            return None

        cmds = self.last_commands

        feet_contacts = self.feet_contacts.get()

        obs = np.concatenate(
            [
                imu_data["gyro"],
                imu_data["accelero"],
                cmds,
                dof_pos - self.init_pos,
                dof_vel * DOF_VEL_OBS_SCALE,
                self.last_action,
                self.last_last_action,
                self.last_last_last_action,
                self.motor_targets,
                feet_contacts,
                self.imitation_phase,
            ]
        ).astype(np.float64)  # a None reading becomes NaN

        # A NaN in the observation makes the policy output NaN, which the
        # servos turn into an extreme position.
        if not np.all(np.isfinite(obs)):
            return None

        return obs

    def reset_stats(self) -> None:
        self.stats_start_t = time.time()
        self.stats_steps = 0
        self.stats_obs_failures = 0
        self.stats_overruns = 0
        self.stats_bad_actions = 0
        self.stats_offset_clips = 0
        self.stats_velocity_clips = 0
        self.stats_max_action = np.zeros(self.num_dofs)
        self.stats_max_offset = np.zeros(self.num_dofs)
        self.stats_max_gyro = 0.0
        self.stats_max_accelero = 0.0

    def log_stats(self) -> None:
        """Print what the walk commanded over the last STATS_PERIOD_S.

        A crash cuts the power without warning, so this summary is the only
        trace of what the policy was asking just before.
        """
        joints = list(self.hwi.joints.keys())
        a = int(np.argmax(self.stats_max_action))
        o = int(np.argmax(self.stats_max_offset))
        print(
            f"STATS steps={self.stats_steps}"
            f" obs_failures={self.stats_obs_failures}"
            f" overruns={self.stats_overruns}"
            f" bad_actions={self.stats_bad_actions}"
            f" max|action|={self.stats_max_action[a]:.2f} ({joints[a]})"
            f" max|target-init|={self.stats_max_offset[o]:.2f} ({joints[o]})"
            f" offset_clips={self.stats_offset_clips}"
            f" velocity_clips={self.stats_velocity_clips}"
            f" max|gyro|={self.stats_max_gyro:.2f}"
            f" max|accelero|={self.stats_max_accelero:.2f}"
            f" imu_spikes={self.imu.rejected_samples}"
        )
        self.imu.rejected_samples = 0
        self.reset_stats()

    def start(self) -> None:
        kps = [self.pid[0]] * self.num_dofs
        kds = [self.pid[2]] * self.num_dofs

        # lower head kps
        kps[HEAD_JOINT_SLICE] = [HEAD_KP] * 4

        self.hwi.set_kps(kps)
        self.hwi.set_kds(kds)
        self.hwi.turn_on()

        time.sleep(STARTUP_SETTLE_S)

    def run(self) -> None:
        i = 0
        try:
            print("Starting")
            start_t = time.time()
            self.last_servo_read_t = start_t
            while True:
                left_trigger = 0
                right_trigger = 0
                t = time.time()

                if self.commands and not self.xbox_controller.is_connected():
                    if not self.paused:
                        print("PAUSE (controller disconnected)")
                    self.paused = True

                if self.commands:
                    self.last_commands, self.buttons, left_trigger, right_trigger = (
                        self.xbox_controller.get_last_command()
                    )
                    if self.buttons.dpad_up.triggered:
                        self.phase_frequency_factor_offset += PHASE_FREQ_OFFSET_STEP
                        offset = round(self.phase_frequency_factor_offset, 3)
                        print(f"Phase frequency factor offset {offset}")

                    if self.buttons.dpad_down.triggered:
                        self.phase_frequency_factor_offset -= PHASE_FREQ_OFFSET_STEP
                        offset = round(self.phase_frequency_factor_offset, 3)
                        print(f"Phase frequency factor offset {offset}")

                    if self.buttons.LB.is_pressed:
                        self.phase_frequency_factor = PHASE_FREQ_FACTOR_RUN
                    else:
                        self.phase_frequency_factor = PHASE_FREQ_FACTOR_IDLE

                    if self.buttons.X.triggered and self.duck_config.projector:
                        self.projector.switch()

                    if self.buttons.B.triggered and self.duck_config.speaker:
                        self.sounds.play_random_sound()

                    if self.duck_config.antennas:
                        self.antennas.set_position_left(right_trigger)
                        self.antennas.set_position_right(left_trigger)

                    if self.buttons.A.triggered:
                        self.paused = not self.paused
                        if self.paused:
                            print("PAUSE")
                        else:
                            print("UNPAUSE")

                if self.paused:
                    time.sleep(PAUSE_POLL_S)
                    self.reset_stats()
                    # Nothing reads the servos while paused.
                    self.last_servo_read_t = time.time()
                    continue

                if t - self.last_servo_read_t > SERVO_LOSS_S:
                    print(f"Servos silent for {SERVO_LOSS_S}s, exiting so the walk restarts")
                    sys.exit(1)

                if t - self.stats_start_t >= STATS_PERIOD_S:
                    self.log_stats()

                obs = self.get_obs()
                if obs is None:
                    self.stats_obs_failures += 1
                    continue

                self.stats_max_gyro = max(self.stats_max_gyro, float(np.linalg.norm(obs[0:3])))
                self.stats_max_accelero = max(
                    self.stats_max_accelero, float(np.linalg.norm(obs[3:6]))
                )

                self.imitation_i += 1 * (
                    self.phase_frequency_factor + self.phase_frequency_factor_offset
                )
                self.imitation_i = self.imitation_i % self.PRM.nb_steps_in_period
                self.imitation_phase = np.array(
                    [
                        np.cos(
                            self.imitation_i / self.PRM.nb_steps_in_period * 2 * np.pi
                        ),
                        np.sin(
                            self.imitation_i / self.PRM.nb_steps_in_period * 2 * np.pi
                        ),
                    ]
                )

                if self.save_obs:
                    self.saved_obs.append(obs)

                if self.replay_obs is not None:
                    if i < len(self.replay_obs):
                        obs = self.replay_obs[i]
                    else:
                        print("BREAKING ")
                        break

                action = self.policy.infer(obs)
                if not np.all(np.isfinite(action)):
                    self.stats_bad_actions += 1
                    continue

                self.last_last_last_action = self.last_last_action.copy()
                self.last_last_action = self.last_action.copy()
                self.last_action = action.copy()

                self.motor_targets = self.init_pos + action * self.action_scale

                if self.action_filter is not None:
                    self.action_filter.push(self.motor_targets)
                    filtered_motor_targets = self.action_filter.get_filtered_action()
                    if time.time() - start_t > FILTER_WARMUP_S:
                        self.motor_targets = filtered_motor_targets

                self.stats_max_action = np.maximum(self.stats_max_action, np.abs(action))
                self.stats_max_offset = np.maximum(
                    self.stats_max_offset, np.abs(self.motor_targets - self.init_pos)
                )

                # Keep the targets near the standing pose, and moving no
                # faster than the servos can follow.
                bounded = np.clip(self.motor_targets, self.target_low, self.target_high)
                self.stats_offset_clips += int(np.count_nonzero(bounded != self.motor_targets))
                max_step = self.max_motor_velocity / self.control_freq
                limited = np.clip(
                    bounded,
                    self.prev_motor_targets - max_step,
                    self.prev_motor_targets + max_step,
                )
                self.stats_velocity_clips += int(np.count_nonzero(limited != bounded))
                self.motor_targets = limited

                self.prev_motor_targets = self.motor_targets.copy()

                head_motor_targets = self.last_commands[3:] + self.motor_targets[HEAD_JOINT_SLICE]
                self.motor_targets[HEAD_JOINT_SLICE] = head_motor_targets

                action_dict = make_action_dict(
                    self.motor_targets, list(self.hwi.joints.keys())
                )

                self.hwi.set_position_all(action_dict)

                i += 1
                self.stats_steps += 1

                took = time.time() - t
                if (1 / self.control_freq - took) < 0:
                    self.stats_overruns += 1
                    print(
                        "Policy control budget exceeded by",
                        np.around(took - 1 / self.control_freq, 3),
                    )
                time.sleep(max(0, 1 / self.control_freq - took))

        except KeyboardInterrupt:
            if self.duck_config.antennas:
                self.antennas.stop()
            if self.duck_config.eyes:
                self.eyes.stop()
            if self.duck_config.projector:
                self.projector.stop()
            self.feet_contacts.stop()

        if self.save_obs:
            with open("robot_saved_obs.pkl", "wb") as f:
                pickle.dump(self.saved_obs, f)
        print("TURNING OFF")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--onnx_model_path", type=str, required=True)
    parser.add_argument(
        "--duck_config_path",
        type=str,
        required=False,
        default=f"{HOME_DIR}/duck_config.json",
    )
    parser.add_argument(
        "--serial_port",
        type=str,
        default="/dev/ttyACM0",
        help="serial port of the servo driver board",
    )
    parser.add_argument("-a", "--action_scale", type=float, default=DEFAULT_ACTION_SCALE)
    parser.add_argument("-p", type=int, default=DEFAULT_PID[0])
    parser.add_argument("-i", type=int, default=DEFAULT_PID[1])
    parser.add_argument("-d", type=int, default=DEFAULT_PID[2])
    parser.add_argument("-c", "--control_freq", type=int, default=DEFAULT_CONTROL_FREQ)
    parser.add_argument("--pitch_bias", type=float, default=0, help="deg")
    parser.add_argument(
        "--commands",
        action="store_true",
        default=True,
        help="external commands, keyboard or gamepad. Launch control_server.py on host computer",
    )
    parser.add_argument(
        "--save_obs",
        type=str,
        required=False,
        default=False,
        help="save the run's observations",
    )
    parser.add_argument(
        "--replay_obs",
        type=str,
        required=False,
        default=None,
        help="replay the observations from a previous run (can be from the robot or from mujoco)",
    )
    parser.add_argument("--cutoff_frequency", type=float, default=None)
    parser.add_argument(
        "--max_target_offset",
        type=float,
        default=DEFAULT_MAX_TARGET_OFFSET,
        help="rad, how far a motor target may stray from the standing pose",
    )
    parser.add_argument(
        "--max_motor_velocity",
        type=float,
        default=DEFAULT_MAX_MOTOR_VELOCITY,
        help="rad/s, how fast a motor target may move",
    )

    args = parser.parse_args()
    pid = [args.p, args.i, args.d]

    print("Done parsing args")
    rl_walk = RLWalk(
        args.onnx_model_path,
        duck_config_path=args.duck_config_path,
        serial_port=args.serial_port,
        action_scale=args.action_scale,
        pid=pid,
        control_freq=args.control_freq,
        commands=args.commands,
        pitch_bias=args.pitch_bias,
        save_obs=args.save_obs,
        replay_obs=args.replay_obs,
        cutoff_frequency=args.cutoff_frequency,
        max_target_offset=args.max_target_offset,
        max_motor_velocity=args.max_motor_velocity,
    )
    print("Done instantiating RLWalk")
    rl_walk.run()
