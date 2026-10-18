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
Phase 1 complete (2026-10-18). Phase 2 in progress: three GPU image variants build in CI; hardware testing on the NVIDIA PCs pending.

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
3. Back up `cosign.key` offline (e.g. an encrypted USB drive), then delete it from this folder. **Never commit it.**

## Private image: letting a PC download updates
The repository and the `pcos` image on ghcr.io are **private**, so each installed PC must log in to ghcr.io to pull updates:
1. Create a GitHub **classic personal access token** with only the `read:packages` scope (no expiry, or set a reminder to renew it).
2. On the installed PC, run:
   ```bash
   sudo podman login ghcr.io --authfile /etc/ostree/auth.json -u venkateshguggilla
   ```
   ```bash
   sudo chmod 600 /etc/ostree/auth.json
   ```
3. Check that updates work:
   ```bash
   sudo bootc upgrade --check
   ```

The token can only read packages, so a leaked token can't change the repo or publish images. Updates are still verified against `keys/cosign.pub`.

**GitHub Actions minutes:** private repos get a limited free monthly quota (public repos are free). Each image build takes roughly 20–40 minutes, and `build.yml` runs daily. Change its `schedule` to weekly if you get close to the limit.

## Image variants
| Image | For |
|---|---|
| `pcos` | AMD and Intel graphics |
| `pcos-nvidia` | NVIDIA RTX 20/30/40/50 and GTX 16 series (e.g. RTX 3060) |
| `pcos-nvidia-legacy` | NVIDIA GTX 10 series and older Pascal/Maxwell (e.g. GTX 1050 Ti), 580 LTS driver |

**NVIDIA with Secure Boot:** after installing an NVIDIA variant, enroll the driver signing key once, then reboot:
```bash
ujust enroll-secure-boot-key
```
On reboot a blue **MOK Manager** screen appears: choose **Enroll MOK → Continue → Yes**, enter the password `universalblue`, then **Reboot**. Check the driver with `nvidia-smi`.

Switch an existing install to another variant (signature-checked):
```bash
sudo bootc switch --enforce-container-sigpolicy ghcr.io/venkateshguggilla/pcos-nvidia:latest
```

## Building the installer ISO
GitHub → Actions → **Build PC OS installer ISO** → Run workflow (platform `amd64`, choose the **variant**). Download the `<variant>-anaconda-iso` artifact.
