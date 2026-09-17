# Running Open Duck Mini with Nix / NixOS

This repository ships a Nix flake that packages the runtime, exposes each
script as an executable, provides a NixOS service (notably the RL walk), and can
build a bootable Raspberry Pi Zero 2 W SD-card image.

> Requires Nix with flakes enabled
> (`experimental-features = nix-command flakes`). The compiled `rustypot`
> dependency is consumed as an upstream wheel, so only `x86_64-linux` and
> `aarch64-linux` are supported.

## Run a script as a package

Every runnable script under `scripts/` is exposed as `open-duck-<name>`
(underscores become dashes):

```bash
nix run .#v2-rl-walk -- --onnx_model_path ./BEST_WALK_ONNX_2.onnx
nix run .#check-motors
nix run .#imu-server
nix run .#find-soft-offsets
```

Or build the whole bundle and put it on your PATH:

```bash
nix build .#scripts
./result/bin/open-duck-v2-rl-walk --help
```

Available commands: `open-duck-v2-rl-walk`, `-check-motors`, `-check-voltage`,
`-configure-motor`, `-configure-all-motors`, `-find-soft-offsets`, `-turn-on`,
`-turn-off`, `-head-puppet`, `-imu-server`, `-calibrate-imu`,
`-antennas-controller-test`, `-plot-recorded-data`, `-record-data`,
`-new-record-data`.

The wrappers `chdir` into the bundled `scripts/` directory so the relative
data files (`polynomial_coefficients.pkl`, the sound assets) resolve.

`cam_test`, `fc_test` and `imu_client` are intentionally not packaged (they need
`picamzero` / `FramesViewer`, which are Raspberry-Pi-camera or host-only).

## Run the walk (and other scripts) as a NixOS service

Add the module to your NixOS configuration:

```nix
{
  inputs.open-duck.url = "github:apirrone/Open_Duck_Mini_Runtime/nix-flake";

  # in your system modules:
  imports = [ open-duck.nixosModules.default ];

  services.open-duck.walk = {
    enable = true;
    restart = true;                       # start on boot
    onnxModelPath = "/var/lib/open-duck/BEST_WALK_ONNX_2.onnx";
    # Stable /dev/servohat symlink for the Waveshare servo board (see below).
    servoBoard = { vendorId = "1a86"; productId = "55d3"; };
    controlFreq = 50;
    actionScale = 0.25;
    pid = { p = 30; i = 0; d = 0; };
    pitchBias = 0.0;
    cutoffFrequency = 40.0;               # null to disable the action filter
    commands = true;                      # gamepad / keyboard control

    # Declarative duck_config.json (or set duckConfigPath to an existing file):
    duckConfig = {
      start_paused = true;
      imu_upside_down = false;
      phase_frequency_factor_offset = 0.0;
      expression_features = { eyes = false; projector = false; antennas = false; speaker = false; };
      joints_offsets = { left_hip_yaw = 0.0; /* ... */ };
    };
  };
}
```

The service runs as the `open-duck` system user, added to the
`dialout i2c gpio audio input` groups for hardware access, with its state in
`/var/lib/open-duck`. Secrets (e.g. `OPENAI_API_KEY`) go through
`services.open-duck.walk.environmentFile`.

With `servoBoard` set, udev names the board `/dev/servohat` whatever `ttyACM`
number it gets, and the service is bound to that device: a low-battery USB
drop-out stops the walk cleanly, and it starts again when the board comes back.
The walk also pauses whenever the gamepad disconnects. Unpause with A (Cross on
a PS4 controller).

To pair a gamepad automatically, set its Bluetooth address:

```nix
services.open-duck.controller.address = "1C:96:5A:2F:7F:14";
```

The first time, put the controller in pairing mode (PS4: hold Share + PS until
the light bar flashes); afterwards pressing PS/Xbox reconnects it.

Manage it like any unit:

```bash
systemctl start open-duck-walk
journalctl -u open-duck-walk -f
```

## Build the Raspberry Pi Zero 2 W image

`nixosConfigurations.rpi` (see `nix/rpi-image.nix`) is an aarch64 NixOS system
with the walk service, I2C, Bluetooth (for the controller), SSH and the FTDI
latency udev rule preconfigured. It:

- is reachable as `canard.local` (avahi);
- joins the `Okartie` or `escargot` Wi-Fi network;
- starts the walk on boot, paused, with the upstream `BEST_WALK_ONNX_2.onnx`
  policy baked in;
- pairs the PS4 controller and uses `/dev/servohat` for the servo board.

The Wi-Fi passwords are not in the image: after flashing, create
`wireless.env` on the FAT firmware partition with `psk_okartie=...` and
`psk_escargot=...` lines. The IMU calibration and joint offsets in
`nix/rpi-image.nix` are this duck's; refill them from `find_soft_offsets` for
another robot.

```bash
# On aarch64, or an x86_64 host with binfmt/qemu emulation
# (boot.binfmt.emulatedSystems = [ "aarch64-linux" ];):
nix build .#packages.aarch64-linux.sd-image
```

Flash `result/sd-image/*.img` to an SD card and boot. The default login user
is `canard` (password `canard` — change it). `ssh canard@canard.local`, then
`journalctl -u open-duck-walk -f` to watch the walk.

## Tests / checks

```bash
nix flake check
```

runs:

- **runtime** — the `mini_bdx_runtime` package builds and imports.
- **scripts-compile** — every script byte-compiles (syntax check, no hardware).
- **pytest** — runs `pytest` at the repo root (passes cleanly when there are no
  tests yet; drop `tests/` in and they'll be picked up).

## Dev shell

```bash
nix develop      # python 3.12 with the runtime, pypot, matplotlib, pytest
```
