# PC OS

A personal desktop operating system for PCs: **secured like a Mac and as easy to use as a Mac**. It's built as an immutable, signed Fedora **bootc** image with a GNOME desktop.

## Highlights
- **Admin approval for every system change.** Choose **Standard** (password, Mac-like) or **Strong** (password + FIDO2 USB key).
- **Only this PC can read the disk.** Full-disk LUKS2 encryption sealed to the TPM, with an optional PIN or FIDO2 unlock.
- **Read-only, signed OS** with automatic updates and one-click rollback.
- **Gatekeeper-style app approval.** Browser extensions can only be installed after admin approval.
- **No tracking.** Privacy presets (Balanced / Maximum / Custom).
- **Nothing gets in without permission.** Incoming network connections are blocked (stealth), and new USB devices are blocked until approved.
- **Built-in apps:** Temp Monitor (temperatures, per-fan control, overheat alerts, history), PC Cleaner, and Android phone integration (notifications, SMS, calls, screen control).
- **GPU support:** AMD/Intel, NVIDIA RTX/GTX 16+, NVIDIA GTX 10 (legacy driver).

## Documents
- [Design document](docs/DESIGN.md): architecture and every feature in detail
- [Build roadmap](docs/ROADMAP.md): phases, checklists and "done when" criteria

## Status
Planning complete. Next: Phase 0 (repo, VM template, FIDO2 keys, signing keys).

## Repository layout
Built from the [Universal Blue image-template](https://github.com/ublue-os/image-template) (Apache-2.0, see `LICENSE`).

| Path | Purpose |
|---|---|
| `Containerfile` | Base image (Bluefin) + build steps |
| `build_files/build.sh` | Customizations run during the image build |
| `system_files/` | Files copied into the image (`/etc`, `/usr`) |
| `disk_config/` | Installer ISO / VM disk settings |
| `keys/cosign.pub` | Public key the OS uses to verify updates |
| `.github/workflows/build.yml` | Builds, signs and publishes `ghcr.io/venkateshguggilla/pcos` |
| `.github/workflows/build-disk.yml` | Builds the installer ISO (run manually) |

## One-time setup (GitHub)
1. Create the GitHub repository and push this repo.
2. Add the private signing key as a repository secret named `SIGNING_SECRET` (the contents of `cosign.key`).
3. After the first successful build, make the `pcos` package on ghcr.io **public**, so PCs can download updates without logging in.
4. Back up `cosign.key` offline (e.g. an encrypted USB drive), then delete it from this folder. **Never commit it.**

## Building the installer ISO
GitHub → Actions → **Build PC OS installer ISO** → Run workflow (platform `amd64`). Download the `anaconda-iso` artifact.
