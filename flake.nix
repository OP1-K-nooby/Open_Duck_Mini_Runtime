{
  description = "Open Duck Mini runtime — packages, NixOS services and a Raspberry Pi image";

  inputs = {
# A released channel so onnxruntime/scipy/opencv substitute from the
    # binary cache (both x86_64 and aarch64) instead of building from source.
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
  };

  outputs = { self, nixpkgs }:
    let
      # Systems we can build the python bits for (rustypot wheels exist for both).
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f system);

      # Overlay: a python312 interpreter carrying the runtime + its extra deps.
      overlay = final: prev:
        let
          duckPython = prev.python312.override {
            self = final.duckPython;
            packageOverrides = import ./nix/python-packages.nix {
              pkgs = final;
              src = self;
            };
          };
        in
        {
          inherit duckPython;

          # Interpreter with everything the packaged scripts need on PYTHONPATH.
          duckEnv = duckPython.withPackages (ps:
            [ ps.mini-bdx-runtime ps.pypot ps.matplotlib ]
            # GPIO backend for Adafruit Blinka, Pi-only (won't build on x86).
            ++ nixpkgs.lib.optionals (final.stdenv.hostPlatform.system == "aarch64-linux")
              (with ps; [ rpi-gpio ]));

          open-duck-scripts = final.callPackage ./nix/scripts.nix {
            src = self;
            duckEnv = final.duckEnv;
          };

          # The upstream walk policies: open-duck-models.{best-walk,best-walk-2}.
          open-duck-models = final.callPackage ./nix/models.nix { };
        };

      pkgsFor = system: import nixpkgs {
        inherit system;
        overlays = [ overlay ];
      };

      # One NixOS configuration per robot: every directory under ./ducks is a
      # duck, its default.nix layered on top of the shared Pi image.
      ducks = nixpkgs.lib.filterAttrs (_: type: type == "directory")
        (builtins.readDir ./ducks);
      mkDuck = name: _: nixpkgs.lib.nixosSystem {
        modules = [
          { nixpkgs.overlays = [ overlay ]; }
          self.nixosModules.default
          ./nix/rpi-image.nix
          (./ducks + "/${name}")
        ];
      };
    in
    {
      overlays.default = overlay;

      packages = forAllSystems (system:
        let pkgs = pkgsFor system; in
        {
          default = pkgs.open-duck-scripts;
          scripts = pkgs.open-duck-scripts;
          # The python interpreter+runtime, handy for `nix run .#python`.
          python = pkgs.duckEnv;
          # The runtime library on its own.
          runtime = pkgs.duckPython.pkgs.mini-bdx-runtime;
          # The pinned upstream walk policies (ONNX files).
          model-best-walk = pkgs.open-duck-models.best-walk;
          model-best-walk-2 = pkgs.open-duck-models.best-walk-2;
        }
        # The SD images are aarch64; expose them where they can be built
        # natively. `sd-image` is the first duck, canard.
        // nixpkgs.lib.optionalAttrs (system == "aarch64-linux") (
          nixpkgs.lib.mapAttrs' (name: _: nixpkgs.lib.nameValuePair "sd-image-${name}"
            self.nixosConfigurations.${name}.config.system.build.sdImage)
            ducks
          // { sd-image = self.packages.${system}.sd-image-canard; }
        ));

      apps = forAllSystems (system:
        let
          pkgs = pkgsFor system;
          mkApp = name: {
            type = "app";
            program = "${pkgs.open-duck-scripts}/bin/${name}";
          };
        in
        {
          default = mkApp "open-duck-v2-rl-walk";
          v2-rl-walk = mkApp "open-duck-v2-rl-walk";
          check-motors = mkApp "open-duck-check-motors";
          find-soft-offsets = mkApp "open-duck-find-soft-offsets";
          imu-server = mkApp "open-duck-imu-server";
          calibrate-imu = mkApp "open-duck-calibrate-imu";
          turn-on = mkApp "open-duck-turn-on";
          turn-off = mkApp "open-duck-turn-off";
        });

      devShells = forAllSystems (system:
        let pkgs = pkgsFor system; in
        {
          default = pkgs.mkShell {
            packages = [
              (pkgs.duckPython.withPackages (ps: [
                ps.mini-bdx-runtime
                ps.pypot
                ps.matplotlib
                ps.pytest
                ps.pip
              ]))
            ];
            shellHook = ''
              echo "Open Duck Mini dev shell — python ${pkgs.duckPython.version}"
            '';
          };
        });

      checks = forAllSystems (system:
        let pkgs = pkgsFor system; in
        {
          # The runtime library builds (and imports) cleanly.
          runtime = pkgs.duckPython.pkgs.mini-bdx-runtime;

          # All packaged scripts byte-compile (syntax check without hardware).
          scripts-compile = pkgs.runCommand "open-duck-scripts-compile"
            { nativeBuildInputs = [ pkgs.duckEnv ]; } ''
            cp -r ${self}/scripts scripts
            cp -r ${self}/mini_bdx_runtime mini_bdx_runtime
            chmod -R u+w scripts mini_bdx_runtime
            python -m compileall -q scripts mini_bdx_runtime
            touch $out
          '';

          # Run the unit-test suite from ./tests if present. (The scripts/*_test.py
          # files are hardware bring-up scripts, not pytest tests, so we do not
          # collect from the repo root.) Passes cleanly when there are no tests.
          pytest = pkgs.runCommand "open-duck-pytest"
            {
              nativeBuildInputs = [
                (pkgs.duckPython.withPackages (ps: [ ps.mini-bdx-runtime ps.pypot ps.pytest ]))
              ];
            } ''
            if [ -d ${self}/tests ]; then
              cp -r ${self}/tests tests
              chmod -R u+w tests
              python -m pytest -q -p no:cacheprovider tests
            else
              echo "No ./tests directory; nothing to run."
            fi
            touch $out
          '';
        });

      # NixOS module: services.open-duck.*
      nixosModules.default = import ./nix/module.nix { inherit self; };
      nixosModules.open-duck = self.nixosModules.default;

      # Raspberry Pi Zero 2 W image configurations, one per duck. `rpi` is kept
      # as an alias for canard, the first one.
      nixosConfigurations = nixpkgs.lib.mapAttrs mkDuck ducks
        // { rpi = self.nixosConfigurations.canard; };

      formatter = forAllSystems (system: (pkgsFor system).nixpkgs-fmt);
    };
}
