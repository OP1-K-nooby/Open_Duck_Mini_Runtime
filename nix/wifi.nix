# Wi-Fi via wpa_supplicant: the duck joins whichever of its networks is in
# range. Each duck lists them in ducks/<name>/default.nix:
#
#     duck.wifiNetworks = [ "Okartie" "escargot" ];   # most preferred first
#
# The passphrases are kept out of the image (and the git repo) and read at
# runtime from a secrets file on the FAT firmware partition, which you can
# edit from any machine before first boot. Create a file named `wireless.env`
# on that partition (mounted at /boot/firmware) with one line per network:
#     psk_okartie=<password>
#     psk_escargot=<password>
# The key is psk_ followed by the SSID lowercased, anything but letters and
# digits turned into "_". Write it with Unix newlines: the value is taken
# verbatim, so a CRLF file puts a stray \r in the passphrase and
# authentication fails silently. If the file is missing, wpa_supplicant won't
# bring up the link.
{ lib, config, ... }:
let
  cfg = config.duck;
  pskKey = ssid:
    "psk_" + lib.stringAsChars
      (c: if builtins.match "[a-z0-9]" c != null then c else "_")
      (lib.toLower ssid);
  count = builtins.length cfg.wifiNetworks;
in
{
  options.duck.wifiNetworks = lib.mkOption {
    type = lib.types.listOf lib.types.str;
    default = [ ];
    example = [ "Okartie" "escargot" ];
    description = ''
      SSIDs of the Wi-Fi networks the duck joins, most preferred first. The
      passphrase of each is read at runtime from wireless.env on the firmware
      partition, as psk_<ssid> (lowercased, other characters than letters and
      digits turned into "_").
    '';
  };

  config = {
    assertions = [
      {
        assertion = !config.networking.wireless.enable || count > 0;
        message = "duck.wifiNetworks is empty: the duck would never get on a network.";
      }
      {
        assertion = lib.allUnique (map pskKey cfg.wifiNetworks);
        message = "duck.wifiNetworks: two SSIDs map to the same wireless.env key ("
          + lib.concatStringsSep ", " (map pskKey cfg.wifiNetworks) + ").";
      }
    ];

    networking.wireless = {
      enable = lib.mkDefault true;
      secretsFile = lib.mkDefault "/boot/firmware/wireless.env";
      extraConfig = "country=FR";
      # The first network gets the highest priority.
      networks = lib.listToAttrs (lib.imap0
        (i: ssid: lib.nameValuePair ssid {
          pskRaw = lib.mkDefault "ext:${pskKey ssid}";
          priority = 5 * (count - i);
        })
        cfg.wifiNetworks);
    };

    # wpa_supplicant runs hardened: PrivateMounts + a RootDirectory, with
    # secretsFile bind-mounted in. That namespace is built when the unit
    # starts, so if /boot/firmware is mounted afterwards the daemon never sees
    # the file — it starts fine and then just fails every `ext:` PSK lookup at
    # association time, with nothing obvious in the log. Order it after the
    # mount.
    systemd.services.wpa_supplicant = lib.mkIf config.networking.wireless.enable {
      unitConfig.RequiresMountsFor = [ "/boot/firmware" ];
    };
  };
}
