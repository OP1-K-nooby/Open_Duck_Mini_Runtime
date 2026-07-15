let
  # We pin to a specific nixpkgs commit for reproducibility.
  # Last updated: 2024-04-29. Check for new commits at https://status.nixos.org.
  pkgs = import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/b3d51a0365f6695e7dd5cdf3e180604530ed33b4.tar.gz") {};

  myPython = pkgs.python312;

  pythonWithPkgs = myPython.withPackages (pythonPkgs: with pythonPkgs; [
    pip
    setuptools
    virtualenvwrapper
    wheel
  ]);

  lib-path = with pkgs; lib.makeLibraryPath [
    stdenv.cc.cc
    zlib
  ];

  shell = pkgs.mkShell {
    buildInputs = [
      # my python and packages
      pythonWithPkgs
    ];

    shellHook = ''
      # Allow the use of wheels.
      SOURCE_DATE_EPOCH=$(date +%s)
      # Augment the dynamic linker path
      export "LD_LIBRARY_PATH=$LD_LIBRARY_PATH:${lib-path}"
      # Setup the virtual environment if it doesn't already exist.
      VENV=.venv
      if test ! -d $VENV; then
        virtualenv $VENV
      fi
      source ./$VENV/bin/activate
      export PYTHONPATH=`pwd`/$VENV/${myPython.sitePackages}/:$PYTHONPATH
    '';
  };
in 
  shell
