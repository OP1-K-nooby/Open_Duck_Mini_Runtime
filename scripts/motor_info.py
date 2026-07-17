#!/usr/bin/env python3
import argparse

from pypot.feetech import FeetechSTS3215IO

# Servo IDs are scanned over this (inclusive-exclusive) range.
SERVO_ID_MIN = 1
SERVO_ID_MAX = 34


def discover_servos(io) -> list[int]:
    """Return a list of IDs for which get_present_position succeeds."""
    found = []
    for sid in range(SERVO_ID_MIN, SERVO_ID_MAX):
        try:
            io.get_present_position([sid])
            found.append(sid)
        except Exception:
            pass
    return found


def read_params(io, sid: int) -> dict:
    """Read all required parameters for a single servo ID."""
    return {
        'id': sid,
        'P': io.get_P_coefficient([sid])[0],
        'I': io.get_I_coefficient([sid])[0],
        'D': io.get_D_coefficient([sid])[0],
        'acceleration': io.get_acceleration([sid])[0],
        'max_acceleration': io.get_maximum_acceleration([sid])[0],
        'mode': io.get_mode([sid])[0],
    }

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover STS3215 servos on a serial port and dump their parameters"
    )
    parser.add_argument(
        "--port",
        default="/dev/ttyACM0",
        help="Serial port (e.g. /dev/ttyACM0)",
    )
    args = parser.parse_args()

    io = FeetechSTS3215IO(args.port)
    print(f"Scanning for servos on port {args.port}…")
    servos = discover_servos(io)

    if not servos:
        print("No servos found.")
        return

    # Print table header
    print("\nFound servos:", servos, "\n")
    header = ["ID", "P", "I", "D", "accel", "max_accel", "mode"]
    print("{:>3} {:>5} {:>5} {:>5} {:>7} {:>10} {:>6}".format(*header))

    # Print each servo's parameters
    for sid in servos:
        p = read_params(io, sid)
        print("{:>3} {:>5} {:>5} {:>5} {:>7} {:>10} {:>6}".format(
            p['id'], p['P'], p['I'], p['D'],
            p['acceleration'], p['max_acceleration'], p['mode']
        ))

if __name__ == "__main__":
    main()
