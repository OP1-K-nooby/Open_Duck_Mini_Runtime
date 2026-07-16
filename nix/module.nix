# NixOS module exposing the Open Duck Mini runtime as systemd services.
#
# The flagship service is `services.open-duck.walk`, which runs the RL walk
# policy (scripts/v2_rl_walk_mujoco.py). A small generic `services.open-duck.scripts`
# mechanism is also provided to run any other packaged script as a service.
{ self }:
{ config, lib, pkgs, ... }:
let
  cfg = config.services.open-duck;

  # The scripts package for the host's system, from this flake's overlay.
  defaultPackage = self.packages.${pkgs.stdenv.hostPlatform.system}.scripts;

  # The RL walk policy checkpoint, pinned to a static upstream revision for
  # reproducibility (raw file from apirrone/Open_Duck_Mini@v2).
  defaultOnnxModel = pkgs.fetchurl {
    name = "BEST_WALK_ONNX_2.onnx";
    url = "https://raw.githubusercontent.com/apirrone/Open_Duck_Mini/b23317a485b3cec7d8417f352478778b3475173c/BEST_WALK_ONNX_2.onnx";
    hash = "sha256-PGBvk4GhcQzI/s23RCeH3L/OPum8AqbxIkd0qys6EGc=";
  };

  # Turn an attrset into a duck_config.json in the nix store.
  configFile = name: value:
    pkgs.writeText "${name}.json" (builtins.toJSON value);

  walk = cfg.walk;

  # Resolve the duck config path: an explicit path wins, otherwise a generated
  # file from `duckConfig`, otherwise the per-service state file.
  walkConfigPath =
    if walk.duckConfigPath != null then walk.duckConfigPath
    else if walk.duckConfig != null then configFile "duck_config" walk.duckConfig
    else "/var/lib/open-duck/duck_config.json";

  walkArgs = lib.escapeShellArgs ([
    "--onnx_model_path" (toString walk.onnxModelPath)
    "--duck_config_path" (toString walkConfigPath)
    "--control_freq" (toString walk.controlFreq)
    "-a" (toString walk.actionScale)
    "-p" (toString walk.pid.p)
    "-i" (toString walk.pid.i)
    "-d" (toString walk.pid.d)
    "--pitch_bias" (toString walk.pitchBias)
  ]
  ++ lib.optionals (walk.cutoffFrequency != null) [ "--cutoff_frequency" (toString walk.cutoffFrequency) ]
  ++ lib.optionals walk.commands [ "--commands" ]
  ++ walk.extraArgs);

  hardwareGroups = [ "dialout" "i2c" "gpio" "audio" "input" ];
in
{
  options.services.open-duck = {
    package = lib.mkOption {
      type = lib.types.package;
      default = defaultPackage;
      defaultText = lib.literalExpression "open-duck flake scripts package";
      description = "The open-duck-scripts package providing the executables.";
    };

    walk = {
      enable = lib.mkEnableOption "the Open Duck Mini RL walk service";

      onnxModelPath = lib.mkOption {
        type = lib.types.path;
        default = defaultOnnxModel;
        defaultText = lib.literalExpression
          "BEST_WALK_ONNX_2.onnx fetched from apirrone/Open_Duck_Mini@b23317a";
        example = "/var/lib/open-duck/BEST_WALK_ONNX_2.onnx";
        description = ''
          Path to the ONNX walk policy checkpoint. Defaults to the pinned
          upstream BEST_WALK_ONNX_2.onnx fetched at build time.
        '';
      };

      duckConfigPath = lib.mkOption {
        type = lib.types.nullOr lib.types.path;
        default = null;
        description = ''
          Path to an existing duck_config.json. If null and {option}`duckConfig`
          is set, a config file is generated; otherwise
          /var/lib/open-duck/duck_config.json is used.
        '';
      };

      duckConfig = lib.mkOption {
        type = lib.types.nullOr (lib.types.attrsOf lib.types.anything);
        default = null;
        example = lib.literalExpression ''
          {
            start_paused = false;
            imu_upside_down = false;
            phase_frequency_factor_offset = 0.0;
            expression_features = { eyes = false; projector = false; antennas = false; speaker = false; };
            joints_offsets = { left_hip_yaw = 0.0; /* ... */ };
          }
        '';
        description = "Declarative duck configuration, rendered to JSON. Ignored if duckConfigPath is set.";
      };

      serialPort = lib.mkOption {
        type = lib.types.str;
        default = "/dev/ttyACM0";
        description = "Serial port of the motor control board.";
      };

      controlFreq = lib.mkOption {
        type = lib.types.int;
        default = 50;
        description = "Control loop frequency in Hz.";
      };

      actionScale = lib.mkOption {
        type = lib.types.numbers.nonnegative;
        default = 0.25;
        description = "Action scale applied to the policy output.";
      };

      pid = {
        p = lib.mkOption { type = lib.types.int; default = 30; description = "Proportional gain."; };
        i = lib.mkOption { type = lib.types.int; default = 0; description = "Integral gain."; };
        d = lib.mkOption { type = lib.types.int; default = 0; description = "Derivative gain."; };
      };

      pitchBias = lib.mkOption {
        type = lib.types.numbers.between (-90.0) 90.0;
        default = 0.0;
        description = "User pitch bias in degrees.";
      };

      cutoffFrequency = lib.mkOption {
        type = lib.types.nullOr lib.types.numbers.nonnegative;
        default = null;
        description = "Low-pass action filter cutoff frequency (Hz). Null disables filtering.";
      };

      commands = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Enable external commands (gamepad / keyboard).";
      };

      extraArgs = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [ ];
        description = "Extra command-line arguments passed to v2_rl_walk_mujoco.py.";
      };

      environmentFile = lib.mkOption {
        type = lib.types.nullOr lib.types.path;
        default = null;
        description = "systemd EnvironmentFile for secrets (e.g. OPENAI_API_KEY).";
      };

      user = lib.mkOption {
        type = lib.types.str;
        default = "open-duck";
        description = "User the walk service runs as.";
      };

      group = lib.mkOption {
        type = lib.types.str;
        default = "open-duck";
        description = "Group the walk service runs as.";
      };

      restart = lib.mkOption {
        type = lib.types.bool;
        default = false;
        description = ''
          Automatically (re)start the walk on boot. Off by default: an
          unattended walking robot on boot is usually not what you want.
        '';
      };
    };
  };

  config = lib.mkIf walk.enable {
    users.users.${walk.user} = lib.mkIf (walk.user == "open-duck") {
      isSystemUser = true;
      group = walk.group;
      extraGroups = hardwareGroups;
      home = "/var/lib/open-duck";
      createHome = true;
    };
    users.groups.${walk.group} = lib.mkIf (walk.group == "open-duck") { };

    systemd.services.open-duck-walk = {
      description = "Open Duck Mini RL walk";
      wantedBy = lib.mkIf walk.restart [ "multi-user.target" ];
      after = [ "network.target" "sound.target" ];

      serviceConfig = {
        ExecStart = "${cfg.package}/bin/open-duck-v2-rl-walk ${walkArgs}";
        User = walk.user;
        Group = walk.group;
        SupplementaryGroups = hardwareGroups;
        StateDirectory = "open-duck";
        WorkingDirectory = "/var/lib/open-duck";
        Restart = "on-failure";
        RestartSec = 3;
        EnvironmentFile = lib.mkIf (walk.environmentFile != null) walk.environmentFile;
        # HOME so that scripts falling back to ~/duck_config.json behave.
        Environment = [ "HOME=/var/lib/open-duck" ];
      };
    };
  };
}
