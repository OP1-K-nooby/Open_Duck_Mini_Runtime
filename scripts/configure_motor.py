import argparse
import sys
import time

from pypot.feetech import FeetechSTS3215IO

DEFAULT_ID = 1  # A brand new motor should have id 1
# Feetech IDs are a single byte, so scan the whole 0..254 range.
SCAN_MAX_ID = 255
# Proportional coefficient written to a freshly configured motor.
DEFAULT_P_COEFFICIENT = 32

parser = argparse.ArgumentParser()
parser.add_argument(
    "--port",
    help=(
        "The port the motor is connected to. Default is /dev/ttyACM0. "
        "Use `ls /dev/tty* | grep usb` to find the port."
    ),
    default="/dev/ttyACM0",
)
parser.add_argument("--id", help="The id to set to the motor.", type=str, required=True)
args = parser.parse_args()
io = FeetechSTS3215IO(args.port)

current_id = DEFAULT_ID


def scan() -> int | None:
    found_id = None
    for i in range(SCAN_MAX_ID):
        print(f"scanning for id {i} ...")
        try:
            io.get_present_position([i])
            found_id = i
            print(f"Found motor with id {found_id}")
            break
        except Exception:
            pass
    return found_id


try:
    io.get_present_position([DEFAULT_ID])
except Exception:
    print(
        f"Could not find motor with default id ({DEFAULT_ID}). Scanning for motor ..."
    )
    res = scan()
    if res is not None:
        current_id = res
    else:
        print("Could not find motor. Exiting ...")
        sys.exit()


io.set_lock({current_id: 0})
io.set_mode({current_id: 0})
io.set_maximum_acceleration({current_id: 0})
io.set_acceleration({current_id: 0})
io.set_P_coefficient({current_id: DEFAULT_P_COEFFICIENT})
io.set_I_coefficient({current_id: 0})
io.set_D_coefficient({current_id: 0})
io.change_id({current_id: int(args.id)})

current_id = int(args.id)

time.sleep(1)

io.set_goal_position({current_id: 0})

time.sleep(1)

print("===")
print("Done configuring motor.")
print(f"Motor id: {current_id}")
print(f"P coefficient : {io.get_P_coefficient([current_id])}")
print(f"I coefficient : {io.get_I_coefficient([current_id])}")
print(f"D coefficient : {io.get_D_coefficient([current_id])}")
print(f"acceleration: {io.get_acceleration([current_id])}")
print(f"max_acceleration: {io.get_maximum_acceleration([current_id])}")
print(f"mode: {io.get_mode([current_id])}")
print("===")
