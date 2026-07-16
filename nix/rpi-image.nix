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

  # WiFi via wpa_supplicant. The PSK is kept out of the image (and the git repo)
  # and read at runtime from a secrets file on the FAT firmware partition, which
  # you can edit from any machine before first boot. Create a file named
  # `wireless.env` on that partition (mounted at /boot/firmware) containing:
  #     psk_okartie=okartie_SR
  # If the file is missing, wpa_supplicant won't bring up the link.
  networking.wireless = {
    enable = lib.mkDefault true;
    secretsFile = lib.mkDefault "/boot/firmware/wireless.env";
    networks."Okartie".pskRaw = lib.mkDefault "ext:psk_okartie";
  };
  # Pull an address over DHCP on the wireless link.
  networking.useDHCP = lib.mkDefault true;

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

  # Bluetooth, tuned for game controllers (PS4 DualShock 4 / PS5 DualSense, and
  # also Xbox). The controllers speak standard Bluetooth HID (hid_playstation /
  # hid_sony in the kernel) and pair without a PIN ("Just Works").
  hardware.bluetooth = {
    enable = true;
    powerOnBoot = true;
    settings.General = {
      # DualSense/DualShock re-advertise a fresh identity each time they enter
      # pairing mode; allow re-pairing an already-known device without a PIN.
      JustWorksRepairing = "always";
      # Advertise both BR/EDR and LE so either controller generation connects.
      ControllerMode = "dual";
      FastConnectable = true;
      # Present as an input host so controllers offer their HID service.
      Class = "0x000100";
    };
  };

  # Auto-accept incoming pairings and auto-trust so a controller reconnects on
  # its own after the first pair. Put the controller in pairing mode (PS4: hold
  # SHARE + PS until the bar double-flashes; PS5: hold CREATE + PS), then from an
  # SSH session run:  bluetoothctl -- scan on   (find its MAC) and
  # bluetoothctl -- pair <MAC>  — the agent accepts and trusts it for you.
  systemd.services.bt-agent = {
    description = "Bluetooth auto-pairing agent for game controllers";
    after = [ "bluetooth.target" ];
    wantedBy = [ "bluetooth.target" ];
    serviceConfig = {
      Type = "simple";
      ExecStartPre = pkgs.writeShellScript "bt-pairable" ''
        ${pkgs.bluez}/bin/bluetoothctl -- power on || true
        ${pkgs.bluez}/bin/bluetoothctl -- pairable on || true
      '';
      ExecStart = "${pkgs.bluez-tools}/bin/bt-agent --capability=NoInputNoOutput";
      Restart = "always";
      RestartSec = 2;
    };
  };

  # The runtime environment on the PATH for interactive use, plus BT tooling.
  environment.systemPackages = [
    config.services.open-duck.package
    pkgs.bluez
    pkgs.bluez-tools
  ];

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
