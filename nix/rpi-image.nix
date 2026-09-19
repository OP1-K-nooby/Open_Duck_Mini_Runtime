# NixOS configuration for a Raspberry Pi Zero 2 W (aarch64) SD-card image that
# boots straight into the Open Duck Mini runtime. This is shared by every duck;
# the robot-specific settings (hostname, controller, calibration) live in
# ducks/<name>/default.nix.
#
# Build with:
#   nix build .#packages.aarch64-linux.sd-image-<name>
# (needs an aarch64 builder or binfmt/qemu emulation on the build host).
{ modulesPath, lib, pkgs, config, ... }:
{
  imports = [
    "${modulesPath}/installer/sd-card/sd-image-aarch64.nix"
  ];

  nixpkgs.hostPlatform = lib.mkDefault "aarch64-linux";

  # Keep the image small-ish and buildable without extra channels.
  sdImage.compressImage = lib.mkDefault false;

  # nixpkgs' profiles/base.nix (pulled in by sd-image-aarch64.nix) turns on ZFS
  # by default. A duck never sees a zpool, and it costs a few hundred MB of
  # image plus a memory-hungry module on a 512 MB board.
  boot.supportedFilesystems.zfs = lib.mkForce false;

  boot.loader.grub.enable = false;
  boot.loader.generic-extlinux-compatible.enable = true;

  # nixpkgs' sd-image.nix mounts the FAT firmware partition `nofail,noauto`, on
  # the grounds that nothing needs it at runtime. We do: wpa_supplicant reads
  # its PSKs from wireless.env there (see below). Left at `noauto`,
  # /boot/firmware is an empty directory on the running system, so the secrets
  # file is invisible no matter what you write onto the card.
  fileSystems."/boot/firmware".options = lib.mkForce [ "nofail" ];

  # WiFi via wpa_supplicant; joins whichever of these networks is in range. The
  # PSKs are kept out of the image (and the git repo) and read at runtime from a
  # secrets file on the FAT firmware partition, which you can edit from any
  # machine before first boot. Create a file named `wireless.env` on that
  # partition (mounted at /boot/firmware) containing:
  #     psk_okartie=<password>
  #     psk_escargot=<password>
  # Write it with Unix newlines: the value is taken verbatim, so a CRLF file
  # puts a stray \r in the passphrase and authentication fails silently.
  # If the file is missing, wpa_supplicant won't bring up the link.
  networking.wireless = {
    enable = lib.mkDefault true;
    secretsFile = lib.mkDefault "/boot/firmware/wireless.env";
    extraConfig = "country=FR";
    networks = {
      Okartie = { pskRaw = lib.mkDefault "ext:psk_okartie"; priority = 10; };
      escargot = { pskRaw = lib.mkDefault "ext:psk_escargot"; priority = 5; };
    };
  };

  # wpa_supplicant runs hardened: PrivateMounts + a RootDirectory, with
  # secretsFile bind-mounted in. That namespace is built when the unit starts,
  # so if /boot/firmware is mounted afterwards the daemon never sees the file —
  # it starts fine and then just fails every `ext:` PSK lookup at association
  # time, with nothing obvious in the log. Order it after the mount.
  systemd.services.wpa_supplicant = lib.mkIf config.networking.wireless.enable {
    unitConfig.RequiresMountsFor = [ "/boot/firmware" ];
  };
  # Pull an address over DHCP on the wireless link.
  networking.useDHCP = lib.mkDefault true;

  # Reachable as <hostname>.local.
  services.avahi = {
    enable = true;
    nssmdns4 = true;
    openFirewall = true;
    publish = {
      enable = true;
      addresses = true;
      workstation = true;
    };
  };

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

  # Login user, mirroring the `canard` user from the Raspbian duck: same name and
  # hardware groups. Its SSH keys are set per duck, in ducks/<name>/default.nix.
  users.users.canard = {
    isNormalUser = true;
    extraGroups = [ "wheel" "dialout" "i2c" "gpio" "audio" "video" "input" "netdev" "plugdev" ];
    initialPassword = lib.mkDefault "canard";
  };
  security.sudo.wheelNeedsPassword = lib.mkDefault false;

  # `colmena apply` copies an unsigned closure straight into the duck's store
  # over SSH as this user, which nix only allows for a trusted one (the
  # default is just root). Activation then goes through sudo, which wheel
  # already has without a password.
  nix.settings.trusted-users = [ "root" "@wheel" ];
  # A duck is a machine you end up debugging over SSH; `nix store`, `nix
  # build` and friends are not much use with the default nix.conf.
  nix.settings.experimental-features = [ "nix-command" "flakes" ];

  services.openssh.enable = true;
  # Pi Zero 2 W Wi-Fi/Bluetooth chip firmware.
  hardware.enableRedistributableFirmware = true;

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

  # The walk starts on boot, paused (press A / Cross to start walking). It also
  # pauses whenever the controller disconnects. onnxModelPath defaults to the
  # pinned upstream model (see nix/module.nix).
  services.open-duck.walk = {
    enable = lib.mkDefault true;
    restart = lib.mkDefault true;
  };

  system.stateVersion = lib.mkDefault "24.11";
}
