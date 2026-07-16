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

  # Login user, mirroring the `canard` user from the Raspbian duck: same name,
  # hardware groups and SSH authorized keys.
  users.users.canard = {
    isNormalUser = true;
    extraGroups = [ "wheel" "dialout" "i2c" "gpio" "audio" "video" "input" "netdev" "plugdev" ];
    initialPassword = lib.mkDefault "canard";
    openssh.authorizedKeys.keys = [
      "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQC1pc8NFhXyHkzqasmVCpReT0ctaGB7oIyY2WGMDjtqsyc8KaOglPKGX8ibyx6hITB4/81qKffeJ8uNdNW549wlOTvOMnBptDXBrOC+JtNWfz94jwWipWT3AEaeLKsMuNJKxPm+VN0wyg8Mv6J4stWcrPTVAyv8FrM4siV3yyVF6i1PsANhnSa/z++uZNieDCoGl/Nit5m8JI45vaQ/ZHNZ8Hr88Sl5C/RMdp545bTedunlAnCDcMivrjfz9flwQ1OU57fI5n0hq6y+zcUHCbYsU+9/ZXIZon6dgM5b9nUX6kxQwse0ZJv1IvxGae/8zFxOhKVUfUyZtSZ7WNDXrjIEvF9HehYuu+wQ9E7EdFN6BPewUsWLHzp0f6FWuLERq3S28B0hkyFGSu8tdjHH0dZH8pluzfepZbSl5L4FKQCV9VEnViLEKSd+mKuvAbBuoyoJPL3GZ0CFTOVpp3yS1/p7+Qe2H8wtJv3zCghpC1pddG+LJfnujltNczJmk5lIrfk= virgile@laptop-vquintin"
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDGgsoGWvO4ZtWyjJMpJ+beie8/+JTFFWDAQyXxztbOO virgile@desktop"
      "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQDPcPy0g5Z7SdJZxDg/K2YdMHhFWyy8xHNAWChxs8AyIvirouhI8G2GSNF9+ZcCcJ+LxEsTEWK8eiP0dafUCDVKDIUWLSQuZnmNCC9KRrAZEqY59qPz6iINbW7WrNnqs9pbfip9D/OEflA5Uq70vKuPaC7xNdwxF2kk8/+NCRxjGgA/ravUma7L6bxCuguMS4XcJb3Cg4y2+XmQPQ1Si3MDK6aHpPoU7pKscLzGCLUcpev0q3syW2eyAOQ9BhkJJFod99K0aUSsRfQgMS6PY2QOce0XlpaqeURvDHR+5C4muTo628IeAC7xULutCDlfqU+aa96ZMjXDQQtpOBJZdaZ7iYNvYRce6ONkB4ilx6Ug9M6/InqBSCRDT43fv5BtEJYzqzc6m1kau/GFk3hQoxGOzbY3xSkTn5zFN9BGoQY9odFXY4wZN/12+yCiRScro1e2oAjYr2RRhh/J/nnZv2SdMcn+Qc7uY2A9VklS2yV8cQDy5ufmnujmjsCd+NW7HGE= vquintin@desktop"
    ];
  };
  security.sudo.wheelNeedsPassword = lib.mkDefault false;

  services.openssh.enable = true;

  # Tailscale (as on the Raspbian duck). The daemon starts on boot; run
  # `sudo tailscale up` once to authenticate, or drop an auth key and set
  # services.tailscale.authKeyFile to join unattended.
  services.tailscale.enable = true;

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
    # Copied from the Raspbian duck's ~/duck_config.json (calibrated IMU offsets
    # and per-joint zero offsets for this specific robot).
    duckConfig = lib.mkDefault {
      start_paused = false;
      imu_upside_down = false;
      imu_calib = {
        accelerometer = [ (-86) (-22) (-9) ];
        gyroscope = [ 0 0 0 ];
        magnetometer = [ 0 0 0 ];
      };
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
        left_hip_yaw = 0.018;
        left_hip_roll = -0.003;
        left_hip_pitch = -0.057;
        left_knee = 0.051;
        left_ankle = 0.061;
        neck_pitch = 0.08;
        head_pitch = -0.022;
        head_yaw = -0.0056;
        head_roll = 0.029;
        right_hip_yaw = 0.009;
        right_hip_roll = 0.0;
        right_hip_pitch = 0.029;
        right_knee = -0.011;
        right_ankle = 0.048;
      };
    };
  };

  system.stateVersion = lib.mkDefault "24.11";
}
