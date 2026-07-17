import contextlib
import time
from queue import Queue
from threading import Thread

import numpy as np
import pygame

from mini_bdx_runtime.buttons import Buttons

X_RANGE = [-0.15, 0.15]
Y_RANGE = [-0.2, 0.2]
YAW_RANGE = [-1.0, 1.0]

# rads
NECK_PITCH_RANGE = [-0.34, 1.1]
HEAD_PITCH_RANGE = [-0.78, 0.3]
HEAD_YAW_RANGE = [-0.5, 0.5]
HEAD_ROLL_RANGE = [-0.5, 0.5]

# Xbox pad axis indices.
AXIS_LEFT_X = 0
AXIS_LEFT_Y = 1
AXIS_LEFT_TRIGGER = 2
AXIS_RIGHT_X = 3
AXIS_RIGHT_Y = 4
AXIS_RIGHT_TRIGGER = 5

# Xbox pad button indices.
BUTTON_A = 0
BUTTON_B = 1
BUTTON_X = 3
BUTTON_Y = 4
BUTTON_LB = 6
BUTTON_RB = 7

# Trigger readings below this are treated as fully released.
TRIGGER_DEADZONE = 0.1
# Decimal places commands and triggers are rounded to.
ROUND_DECIMALS = 3
# The worker only keeps the most recent command.
CMD_QUEUE_SIZE = 1


class XBoxController:
    def __init__(self, command_freq: float, only_head_control: bool = False) -> None:
        self.command_freq = command_freq
        self.head_control_mode = only_head_control
        self.only_head_control = only_head_control

        self.last_commands = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self.last_left_trigger = 0.0
        self.last_right_trigger = 0.0
        pygame.init()
        self.p1 = pygame.joystick.Joystick(0)
        self.p1.init()
        print(f"Loaded joystick with {self.p1.get_numaxes()} axes.")
        self.cmd_queue: Queue = Queue(maxsize=CMD_QUEUE_SIZE)

        self.A_pressed = False
        self.B_pressed = False
        self.X_pressed = False
        self.Y_pressed = False
        self.LB_pressed = False
        self.RB_pressed = False

        self.buttons = Buttons()

        Thread(target=self.commands_worker, daemon=True).start()

    def commands_worker(self) -> None:
        while True:
            self.cmd_queue.put(self.get_commands())
            time.sleep(1 / self.command_freq)

    def get_commands(self) -> tuple:
        last_commands = self.last_commands
        left_trigger = self.last_left_trigger
        right_trigger = self.last_right_trigger

        l_x = -1 * self.p1.get_axis(AXIS_LEFT_X)
        l_y = -1 * self.p1.get_axis(AXIS_LEFT_Y)
        r_x = -1 * self.p1.get_axis(AXIS_RIGHT_X)

        right_trigger = np.around((self.p1.get_axis(AXIS_RIGHT_TRIGGER) + 1) / 2, ROUND_DECIMALS)
        left_trigger = np.around((self.p1.get_axis(AXIS_LEFT_TRIGGER) + 1) / 2, ROUND_DECIMALS)

        if left_trigger < TRIGGER_DEADZONE:
            left_trigger = 0
        if right_trigger < TRIGGER_DEADZONE:
            right_trigger = 0

        if not self.head_control_mode:
            lin_vel_y = l_x
            lin_vel_x = l_y
            ang_vel = r_x
            if lin_vel_x >= 0:
                lin_vel_x *= np.abs(X_RANGE[1])
            else:
                lin_vel_x *= np.abs(X_RANGE[0])

            if lin_vel_y >= 0:
                lin_vel_y *= np.abs(Y_RANGE[1])
            else:
                lin_vel_y *= np.abs(Y_RANGE[0])

            if ang_vel >= 0:
                ang_vel *= np.abs(YAW_RANGE[1])
            else:
                ang_vel *= np.abs(YAW_RANGE[0])

            last_commands[0] = lin_vel_x
            last_commands[1] = lin_vel_y
            last_commands[2] = ang_vel
        else:
            last_commands[0] = 0.0
            last_commands[1] = 0.0
            last_commands[2] = 0.0
            last_commands[3] = 0.0  # neck pitch 0 for now

            head_yaw = l_x
            head_pitch = l_y
            head_roll = r_x

            if head_yaw >= 0:
                head_yaw *= np.abs(HEAD_YAW_RANGE[0])
            else:
                head_yaw *= np.abs(HEAD_YAW_RANGE[1])

            if head_pitch >= 0:
                head_pitch *= np.abs(HEAD_PITCH_RANGE[0])
            else:
                head_pitch *= np.abs(HEAD_PITCH_RANGE[1])

            if head_roll >= 0:
                head_roll *= np.abs(HEAD_ROLL_RANGE[0])
            else:
                head_roll *= np.abs(HEAD_ROLL_RANGE[1])

            last_commands[4] = head_pitch
            last_commands[5] = head_yaw
            last_commands[6] = head_roll

        for event in pygame.event.get():
            if event.type == pygame.JOYBUTTONDOWN:

                if self.p1.get_button(BUTTON_A):
                    self.A_pressed = True

                if self.p1.get_button(BUTTON_B):
                    self.B_pressed = True

                if self.p1.get_button(BUTTON_X):
                    self.X_pressed = True

                if self.p1.get_button(BUTTON_Y):
                    self.Y_pressed = True
                    if not self.only_head_control:
                        self.head_control_mode = not self.head_control_mode

                if self.p1.get_button(BUTTON_LB):
                    self.LB_pressed = True

                if self.p1.get_button(BUTTON_RB):
                    self.RB_pressed = True

            if event.type == pygame.JOYBUTTONUP:
                self.A_pressed = False
                self.B_pressed = False
                self.X_pressed = False
                self.Y_pressed = False
                self.LB_pressed = False
                self.RB_pressed = False

        up_down = self.p1.get_hat(0)[1]
        pygame.event.pump()  # process event queue

        return (
            np.around(last_commands, ROUND_DECIMALS),
            self.A_pressed,
            self.B_pressed,
            self.X_pressed,
            self.Y_pressed,
            self.LB_pressed,
            self.RB_pressed,
            left_trigger,
            right_trigger,
            up_down,
        )

    def get_last_command(self) -> tuple:
        A_pressed = False
        B_pressed = False
        X_pressed = False
        Y_pressed = False
        LB_pressed = False
        RB_pressed = False
        up_down = 0
        with contextlib.suppress(Exception):
            (
                self.last_commands,
                A_pressed,
                B_pressed,
                X_pressed,
                Y_pressed,
                LB_pressed,
                RB_pressed,
                self.last_left_trigger,
                self.last_right_trigger,
                up_down,
            ) = self.cmd_queue.get(False)  # non blocking

        self.buttons.update(
            A_pressed,
            B_pressed,
            X_pressed,
            Y_pressed,
            LB_pressed,
            RB_pressed,
            up_down == 1,
            up_down == -1,
        )

        return (
            self.last_commands,
            self.buttons,
            self.last_left_trigger,
            self.last_right_trigger,
        )

if __name__ == "__main__":
    controller = XBoxController(20)

    while True:
        print(controller.get_last_command())
        time.sleep(0.05)
