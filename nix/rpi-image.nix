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

  # sd-image-aarch64.nix pulls in the installer's profiles/base.nix: disk
  # partitioning/repair and crypto tools, vim, and support for btrfs, xfs,
  # ntfs, cifs, f2fs and ZFS (a memory-hungry module on a 512 MB board). A duck
  # only ever mounts its own ext4 root and FAT firmware partition.
  disabledModules = [ "${modulesPath}/profiles/base.nix" ];

  # Nobody reads the NixOS/Nix manuals, man or info pages on the duck.
  # documentation.man.enable defaults to true on its own, and brings man-db
  # and groff.
  documentation.enable = false;
  documentation.man.enable = false;
  # The desktop MIME database; nothing on a headless duck opens files by type.
  xdg.mime.enable = false;
  # systemd-importd (machinectl pull/import of container and VM images) is the
  # only thing that references gnupg, to verify the downloads.
  systemd.suppressedSystemUnits = [ "systemd-importd.service" ];
  # nixos-rebuild & co. (and the second Python they bring): the duck is
  # deployed with colmena, which only needs switch-to-configuration.
  system.disableInstallerTools = true;

  nixpkgs.hostPlatform = lib.mkDefault "aarch64-linux";

  # Keep the image small-ish and buildable without extra channels.
  sdImage.compressImage = lib.mkDefault false;

  # The downstream Raspberry Pi kernel, not mainline. Adafruit Blinka and
  # RPi.GPIO — which the walk reaches the IMU and the antennas through — need
  # the Raspberry Pi userspace ABI: /dev/gpiomem, and the Hardware/Revision
  # lines in /proc/cpuinfo. Mainline provides none of that on aarch64, so
  # `import board` dies with "This module can only be run on a Raspberry Pi!"
  # however much you force adafruit-platformdetect with BLINKA_FORCEBOARD.
  # Repackaged from Raspberry Pi OS's .deb rather than compiled (see
  # nix/rpi-kernel.nix): the kernel Raspbian ducks run, in minutes instead of
  # an emulated kernel build.
  boot.kernelPackages = pkgs.linuxPackages_rpi-deb;

  # The initrd only needs to reach an ext4 root on the SD card, and the Pi
  # kernel builds both the SD controller and ext4 in. What NixOS asks for on
  # top — all-hardware.nix's PC storage drivers (sd-image.nix turns it on), the
  # default SATA/LVM set, the TPM drivers for systemd's TPM2 support — isn't
  # in this kernel at all, and a Pi has no TPM.
  hardware.enableAllHardware = lib.mkForce false;
  boot.initrd.includeDefaultModules = false;
  boot.initrd.systemd.tpm2.enable = false;
  systemd.tpm2.enable = false;

  # NixOS compresses firmware with zstd for any kernel >= 5.19, taking for
  # granted its own config's FW_LOADER_COMPRESS. Raspberry Pi's kernel is built
  # without it, so .zst firmware is invisible to it: no Wi-Fi (brcmfmac) and no
  # Bluetooth after boot, i.e. a headless duck that never comes back.
  hardware.firmwareCompression = "none";

  # The IMU is on I2C1, which the firmware only enables in the device tree it
  # hands over (see useGenerationDeviceTree below) when config.txt says so, as
  # Raspbian's does. sd-image-aarch64.nix's config.txt doesn't; its last
  # section is [all], so appending lands there. A deploy never rewrites the
  # firmware partition, so the activation script adds it to a flashed duck's
  # config.txt too; both take effect on the next reboot.
  sdImage.populateFirmwareCommands = lib.mkAfter ''
    # Copied read-only out of the store.
    chmod u+w firmware/config.txt
    echo "dtparam=i2c_arm=on" >> firmware/config.txt
  '';
  system.activationScripts.firmwareI2c = ''
    if [ -f /boot/firmware/config.txt ] && ! grep -qx 'dtparam=i2c_arm=on' /boot/firmware/config.txt; then
      echo "dtparam=i2c_arm=on" >> /boot/firmware/config.txt
    fi
  '';

  boot.loader.grub.enable = false;
  boot.loader.generic-extlinux-compatible = {
    enable = true;
    # Boot the device tree the Raspberry Pi firmware hands to U-Boot instead of
    # one out of the kernel's dtbs. The firmware's carries the properties it
    # injects at boot — linux,revision, which RPi.GPIO reads to identify the
    # board, among them — plus whatever config.txt's dtparam/dtoverlay lines
    # set up. Pointing U-Boot at FDTDIR throws all of that away.
    useGenerationDeviceTree = false;
  };

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
  # avahi-daemon is Type=dbus but isn't ordered after the bus, and on the Pi
  # kernel's faster boot it starts before dbus-broker is up and exits (status
  # 0, so nothing restarts it): no canard.local until someone restarts it.
  systemd.services.avahi-daemon.after = [ "dbus.service" ];

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
    # RPi.GPIO maps /dev/gpiomem (root-only by default) and falls back to
    # /dev/mem: "No access to /dev/mem. Try running as root!" for the walk's
    # open-duck user otherwise. As Raspbian's 99-com.rules.
    SUBSYSTEM=="gpiomem", GROUP="gpio", MODE="0660"
    # brcmfmac comes up with Wi-Fi power saving on, and the sleeping radio
    # misses multicast: mDNS queries go unanswered and canard.local resolves
    # one minute and not the next.
    ACTION=="add", SUBSYSTEM=="net", KERNEL=="wlan*", RUN+="${pkgs.iw}/bin/iw dev $name set power_save off"
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

  # A duck usually dies by losing power, and journald only syncs to the SD
  # card every 5 minutes: the walk's last words before a crash were lost.
  services.journald.extraConfig = ''
    SyncIntervalSec=1s
  '';

  services.openssh.enable = true;
  # Pi Zero 2 W Wi-Fi/Bluetooth chip firmware, and only that: the whole of
  # enableRedistributableFirmware (linux-firmware, sof, alsa, ...) is ~1.8 GB
  # once stored uncompressed (see firmwareCompression above).
  # raspberrypi-wireless-firmware (~3 MB) has what brcmfmac and hci_uart load
  # on every Zero 2 W radio variant (brcm/brcmfmac43430-sdio.raspberrypi,
  # model-zero-2-w.*, brcm/BCM43430A1.hcd, the 43430b0/43436 ones). All it
  # lacks is the generic 43430 firmware and its clm_blob (regulatory channel
  # data), which linux-firmware carries as symlinks into cypress/.
  hardware.firmware = [
    pkgs.raspberrypiWirelessFirmware
    (pkgs.runCommand "brcmfmac43430-sdio-firmware" { } ''
      mkdir -p $out/lib/firmware/brcm
      for f in brcmfmac43430-sdio.bin brcmfmac43430-sdio.clm_blob; do
        cp -L ${pkgs.linux-firmware}/lib/firmware/brcm/$f $out/lib/firmware/brcm/
      done
    '')
  ];
  hardware.wirelessRegulatoryDatabase = true;

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

  # The walk and scripts without matplotlib (plotting is for the desktop).
  services.open-duck.package = pkgs.open-duck-scripts-headless;

  # The runtime environment on the PATH for interactive use, plus BT tooling
  # and the few debugging tools base.nix's list had that a duck needs.
  environment.systemPackages = [
    config.services.open-duck.package
    pkgs.bluez
    pkgs.bluez-tools
    pkgs.iw
    pkgs.i2c-tools
    pkgs.usbutils
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
