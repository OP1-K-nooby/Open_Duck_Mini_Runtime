# NixOS configuration for a Raspberry Pi Zero 2 W (aarch64) SD-card image that
# boots straight into the Open Duck Mini runtime.
#
# Build with:
#   nix build .#images.rpi
# (needs an aarch64 builder or binfmt/qemu emulation on the build host).
{ modulesPath, lib, pkgs, config, ... }:
{
  imports = [
    "${modulesPath}/installer/sd-card/sd-image-aarch64.nix"
  ];

  nixpkgs.hostPlatform = lib.mkDefault "aarch64-linux";

  # Keep the image small-ish and buildable without extra channels.
  sdImage.compressImage = lib.mkDefault false;

  boot.loader.grub.enable = false;
  boot.loader.generic-extlinux-compatible.enable = true;

  networking.hostName = lib.mkDefault "open-duck";
  # Bring your own wifi: set networking.wireless / systemd-networkd as needed.
  networking.wireless.enable = lib.mkDefault false;

  # Hardware buses used by the runtime (IMU over I2C, motor board over USB serial).
  hardware.i2c.enable = true;

  # The runtime touches GPIO/pwm via Adafruit Blinka; make sure the group exists.
  users.groups.gpio = { };
  services.udev.extraRules = ''
    # Motor control board: minimise USB-serial latency.
    SUBSYSTEM=="usb-serial", DRIVER=="ftdi_sio", ATTR{latency_timer}="1"
    # GPIO/I2C access for the gpio group.
    SUBSYSTEM=="gpio", GROUP="gpio", MODE="0660"
    SUBSYSTEM=="i2c-dev", GROUP="i2c", MODE="0660"
  '';

  # A convenience login user for pairing controllers / debugging.
  users.users.duck = {
    isNormalUser = true;
    extraGroups = [ "wheel" "dialout" "i2c" "gpio" "audio" "input" ];
    initialPassword = lib.mkDefault "duck";
  };
  security.sudo.wheelNeedsPassword = lib.mkDefault false;

  services.openssh.enable = true;
  hardware.bluetooth.enable = true; # xbox controller pairing

  # The runtime environment on the PATH for interactive use.
  environment.systemPackages = [ config.services.open-duck.package ];

  # Enable the walk service. onnxModelPath points at a file you drop on the
  # device; flip `restart` on once you trust it to walk on boot.
  services.open-duck.walk = {
    enable = lib.mkDefault true;
    restart = lib.mkDefault false;
    onnxModelPath = lib.mkDefault "/var/lib/open-duck/BEST_WALK_ONNX_2.onnx";
    serialPort = lib.mkDefault "/dev/ttyACM0";
    duckConfig = lib.mkDefault {
      start_paused = true;
      imu_upside_down = false;
      phase_frequency_factor_offset = 0.0;
      expression_features = {
        eyes = false;
        projector = false;
        antennas = false;
        speaker = false;
        microphone = false;
        camera = false;
      };
      joints_offsets = {
        left_hip_yaw = 0.0;
        left_hip_roll = 0.0;
        left_hip_pitch = 0.0;
        left_knee = 0.0;
        left_ankle = 0.0;
        neck_pitch = 0.0;
        head_pitch = 0.0;
        head_yaw = 0.0;
        head_roll = 0.0;
        right_hip_yaw = 0.0;
        right_hip_roll = 0.0;
        right_hip_pitch = 0.0;
        right_knee = 0.0;
        right_ankle = 0.0;
      };
    };
  };

  system.stateVersion = lib.mkDefault "24.11";
}
