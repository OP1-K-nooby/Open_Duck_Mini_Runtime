# The downstream Raspberry Pi kernel, repackaged from Raspberry Pi OS's own
# .deb instead of compiled: the same 6.12.75-1+rpt1 as nixpkgs' linux_rpi, but
# built with Raspberry Pi's config (the one Raspbian ducks run) and taking
# minutes rather than an emulated kernel build. The price is that it cannot be
# patched or reconfigured, so the kernelPatches NixOS passes in must be empty.
#
# Returns a linuxPackages set, for boot.kernelPackages.
{ lib, stdenvNoCC, fetchurl, dpkg, kmod, linuxPackagesFor }:
let
  version = "6.12.75-1+rpt1";
  modDirVersion = "6.12.75+rpt-rpi-v8";

  # The CONFIG_*=y/m lines of the .deb's /boot/config-*, which is all NixOS
  # reads of a kernel config at evaluation time (kernel.config.isYes & co., for
  # system.requiredKernelConfig). Committed so evaluation doesn't have to
  # unpack the .deb; the build fails if it no longer matches.
  yesModConfig = ./rpi-kernel.config;

  # As nixpkgs' kernel/build.nix does it.
  config =
    let
      matchLine = line:
        let match = lib.match "(CONFIG_[^=]+)=([ym])" line; in
        lib.optional (match != null) { name = lib.elemAt match 0; value = lib.elemAt match 1; };
      values = lib.listToAttrs (lib.concatMap matchLine (lib.splitString "\n" (builtins.readFile yesModConfig)));
      attrName = attr: "CONFIG_" + attr;
    in
    rec {
      isSet = attr: values ? ${attrName attr};
      getValue = attr: values.${attrName attr} or null;
      isYes = attr: getValue attr == "y";
      isNo = attr: getValue attr == "n";
      isModule = attr: getValue attr == "m";
      isEnabled = attr: isModule attr || isYes attr;
      isDisabled = attr: !(isSet attr) || isNo attr;
    }
    // values;

  # Overridable with the arguments NixOS's boot.kernelPackages passes to
  # kernel.override; there is nothing to rebuild, so they are only recorded.
  mkKernel = lib.makeOverridable (
    { features ? { }, kernelPatches ? [ ], randstructSeed ? "" }:
    assert lib.assertMsg (kernelPatches == [ ])
      "rpi-kernel.nix: a prebuilt kernel cannot take kernelPatches (${toString (map (p: p.name or "?") kernelPatches)})";
    stdenvNoCC.mkDerivation (finalAttrs: {
      pname = "linux-rpi-deb";
      inherit version;

      src = fetchurl {
        url = "http://archive.raspberrypi.com/debian/pool/main/l/linux/linux-image-${modDirVersion}_${version}_arm64.deb";
        hash = "sha256-kyhMuXBbGVMyOieoorYNJO46zg0hQr3bKGvuoOx1HzE=";
      };

      nativeBuildInputs = [ dpkg kmod ];

      unpackPhase = ''
        dpkg-deb -x $src .
      '';

      installPhase = ''
        grep -E '^CONFIG_[^=]+=[ym]$' boot/config-${modDirVersion} | diff -u ${yesModConfig} - \
          || { echo "nix/rpi-kernel.config is out of date for ${modDirVersion}" >&2; exit 1; }

        mkdir -p $out/lib/modules $out/dtbs
        # U-Boot's booti wants the uncompressed Image, as nixpkgs installs it.
        gunzip -c boot/vmlinuz-${modDirVersion} > $out/Image
        cp boot/System.map-${modDirVersion} $out/System.map
        cp boot/config-${modDirVersion} $out/config
        cp -r usr/lib/modules/${modDirVersion} $out/lib/modules/
        cp -r usr/lib/linux-image-${modDirVersion}/. $out/dtbs/
        # Debian generates the module index at install time (postinst).
        depmod -b $out -a ${modDirVersion}
      '';

      # Prebuilt aarch64 binaries: nothing to strip or patch.
      dontFixup = true;

      passthru = {
        inherit modDirVersion config features kernelPatches;
        # The full config, which some NixOS modules grep for values other than
        # y/m (sysctl.nix: CONFIG_ARCH_MMAP_RND_BITS_MAX).
        configfile = "${finalAttrs.finalPackage}/config";
        # `version` must be the kernel's own for kernelOlder/kernelAtLeast.
        version = "6.12.75";
        baseVersion = "6.12.75";
        kernelOlder = lib.versionOlder "6.12.75";
        kernelAtLeast = lib.versionAtLeast "6.12.75";
        isZen = false;
        isHardened = false;
        withRust = false;
      };

      meta = {
        description = "Raspberry Pi kernel ${modDirVersion}, repackaged from Raspberry Pi OS";
        platforms = [ "aarch64-linux" ];
        sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
        license = lib.licenses.gpl2Only;
      };
    }));
in
linuxPackagesFor (mkKernel { features.efiBootStub = false; })
