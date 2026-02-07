{
  description = "aico-cli: Native Static Build & Dev Shell";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    crane.url = "github:ipetkov/crane";
    rust-overlay = {
      url = "github:oxalica/rust-overlay";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      crane,
      rust-overlay,
      ...
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs {
          inherit system;
          overlays = [ (import rust-overlay) ];
        };
        inherit (pkgs) lib stdenv;

        # Static musl target on Linux, native on macOS
        target =
          if stdenv.isLinux then pkgs.pkgsMusl.stdenv.hostPlatform.config else stdenv.hostPlatform.config;

        rustToolchain = pkgs.rust-bin.stable."1.93.0".default.override {
          extensions = [
            "rust-src"
            "clippy"
            "rustfmt"
          ];
          targets = [
            target
            "aarch64-unknown-linux-musl"
            "riscv64gc-unknown-linux-musl"
          ];
        };

        craneLib = (crane.mkLib pkgs).overrideToolchain rustToolchain;

        src = lib.cleanSourceWith {
          src = craneLib.path ./.;
          filter =
            path: type: (craneLib.filterCargoSources path type) || (lib.hasInfix "/.aico/addons/" path);
        };

        commonArgs = {
          inherit src;
          strictDeps = true;
          doCheck = false;

          cargoExtraArgs = "--target ${target}";

          nativeBuildInputs = [ pkgs.pkg-config ] ++ lib.optional stdenv.isLinux pkgs.pkgsMusl.stdenv.cc;
          buildInputs = lib.optionals stdenv.isDarwin (
            with pkgs.darwin.apple_sdk.frameworks;
            [
              pkgs.libiconv
              Security
              SystemConfiguration
            ]
          );
        }
        // lib.optionalAttrs stdenv.isLinux (
          let
            cc = "${pkgs.pkgsMusl.stdenv.cc}/bin/cc";
            targetEnv = lib.replaceStrings [ "-" ] [ "_" ] target;
          in
          {
            "CARGO_TARGET_${lib.toUpper targetEnv}_LINKER" = cc;
            "CC_${targetEnv}" = cc;
            CFLAGS = "-U_FORTIFY_SOURCE";
          }
        )
        // {
          VERGEN_GIT_SHA = self.rev or "dirty";
          VERGEN_GIT_COMMIT_TIMESTAMP = self.lastModifiedDate or "19700101";
        };

        cargoArtifacts = craneLib.buildDepsOnly commonArgs;

        aico = craneLib.buildPackage (
          commonArgs
          // {
            inherit cargoArtifacts;
          }
        );

      in
      {
        packages.default = aico;

        checks = {
          inherit aico;

          aico-clippy = craneLib.cargoClippy (
            commonArgs
            // {
              inherit cargoArtifacts;
              cargoClippyExtraArgs = "--all-targets -- --deny warnings";
            }
          );

          aico-fmt = craneLib.cargoFmt { inherit src; };

          aico-nextest = craneLib.cargoNextest (
            commonArgs
            // {
              inherit cargoArtifacts;
            }
          );
        };

        # Dev Shell
        # Uses nix-ld (system-level) for glibc compat with mise-managed toolchains,
        # avoiding buildFHSEnv which conflicts with direnv (nested shell, broken terminal)
        devShells.default =
          let
            # Wrapper cc that replaces rust's -B gcc-ld (bundled rust-lld) with
            # nix's ld.lld which knows nix store library paths.
            # rust-overlay ships prebuilt rust-lld that can't find nix's glibc.
            # See rust-lang/rust#125321
            nixLldDir = pkgs.writeShellScriptBin "ld.lld" ''
              exec "${pkgs.llvmPackages.bintools}/bin/ld.lld" -L"${pkgs.glibc}/lib" "$@"
            '';
            wrappedCC = pkgs.writeShellScriptBin "cc" ''
              # Replace rust's gcc-ld directory with our nix-aware one
              args=()
              for arg in "$@"; do
                case "$arg" in
                  -B*/gcc-ld) args+=("-B${nixLldDir}/bin") ;;
                  *) args+=("$arg") ;;
                esac
              done
              exec "${pkgs.stdenv.cc}/bin/cc" "''${args[@]}"
            '';
            x86_64-musl-cc = pkgs.pkgsMusl.stdenv.cc;
            aarch64-musl-cc = pkgs.pkgsCross.aarch64-multiplatform-musl.stdenv.cc;
            riscv64-musl-cc = pkgs.pkgsCross.riscv64-musl.stdenv.cc;
            clitest = pkgs.runCommand "clitest" { } ''
              mkdir -p $out/bin
              cp ${
                pkgs.fetchurl {
                  url = "https://raw.githubusercontent.com/aureliojargas/clitest/master/clitest";
                  hash = "sha256-8JBOJa9kVzTj7/JHFBLE6HE62XA3SZCw9CtWj8TiL5Q=";
                  executable = true;
                }
              } $out/bin/clitest
            '';
          in
          pkgs.mkShell {
            packages = with pkgs; [
              rustToolchain
              cargo-nextest
              mise
              gnumake
              pkg-config
              openssl.dev
              zlib.dev
              git
              curl
              wget
              jq
              clitest
            ];

            shellHook = ''
              # Ensure our cc wrapper takes priority
              export PATH="${wrappedCC}/bin:$PATH"
              export MISE_YES=1
              echo ":: aico-cli Development Environment ::"
            '';

            # Use our cc wrapper for native compilation
            CC = "${wrappedCC}/bin/cc";
            CC_x86_64_unknown_linux_gnu = "${wrappedCC}/bin/cc";

            # Musl cross-linkers via env vars (overrides .cargo/config.toml for nix)
            CARGO_TARGET_X86_64_UNKNOWN_LINUX_MUSL_LINKER = "${x86_64-musl-cc}/bin/cc";
            CARGO_TARGET_AARCH64_UNKNOWN_LINUX_MUSL_LINKER = "${aarch64-musl-cc}/bin/aarch64-unknown-linux-musl-cc";
            CARGO_TARGET_RISCV64GC_UNKNOWN_LINUX_MUSL_LINKER = "${riscv64-musl-cc}/bin/riscv64-unknown-linux-musl-cc";

            # CC for the cc crate (used by ring, openssl-sys, etc.)
            CC_x86_64_unknown_linux_musl = "${x86_64-musl-cc}/bin/cc";
            CC_aarch64_unknown_linux_musl = "${aarch64-musl-cc}/bin/aarch64-unknown-linux-musl-cc";
            CC_riscv64gc_unknown_linux_musl = "${riscv64-musl-cc}/bin/riscv64-unknown-linux-musl-cc";

            NIX_LD_LIBRARY_PATH = lib.makeLibraryPath (
              with pkgs;
              [
                openssl
                zlib
                stdenv.cc.cc.lib
              ]
            );

            NIX_LD = lib.fileContents "${pkgs.stdenv.cc}/nix-support/dynamic-linker";
          };
      }
    );
}
