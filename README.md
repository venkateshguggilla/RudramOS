# RudramOS

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

## If the images are private: letting a PC download updates
Only needed while the images on ghcr.io are **private**. Once they are public, PCs download updates and drivers without logging in. While private, each installed PC must log in to ghcr.io:
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

**Use the standard `pcos` ISO on every PC.** After the first login, the **Driver Assistant** detects the graphics card and, if it's NVIDIA, offers to install the right driver (admin approval, download, restart). On Secure Boot PCs a blue **MOK Manager** screen appears once after that restart: choose **Enroll MOK → Continue → Yes**, enter `universalblue`, then **Reboot**. Check with `nvidia-smi`.

Check what was detected, from a terminal:
```bash
pcos-driver-assistant --check
```

Switch variants by hand (signature-checked), if ever needed:
```bash
sudo bootc switch --enforce-container-sigpolicy ghcr.io/venkateshguggilla/pcos-nvidia:latest
```

## RudramOS Control Center
Open **RudramOS Control Center** from the app grid (or run `pcos-control`). It shows and changes admin protection, disk encryption, the graphics driver and updates in one place. Steps that need your password or a security-key touch open in a terminal window.

## Admin approval: Standard or Strong
Every admin action (installing apps, system settings, `sudo`) asks for approval.
- **Standard** (default): your password, like a Mac.
- **Strong**: your password **and** a touch of a registered FIDO2 security key (e.g. YubiKey).

Switch to Strong (register both keys first):
```bash
sudo pcos-admin-mode add-key
```
```bash
sudo pcos-admin-mode add-key
```
```bash
sudo pcos-admin-mode strong
```
`strong` first runs a password + touch test and refuses if it fails, so you can't lock yourself out by mistake. Back to Standard: `sudo pcos-admin-mode standard` (needs the key while in Strong mode). Check with `pcos-admin-mode status`.

**Lost all keys while in Strong mode** (not yet tested end to end): boot the RudramOS installer USB, press **Ctrl+Alt+F2** for a root shell, unlock the drive with the recovery key (`cryptsetup open /dev/<partition> sysroot`), mount it, and copy `/usr/share/pcos/pam/pcos-admin.standard` over `ostree/deploy/default/deploy/<current>/etc/pam.d/pcos-admin`.

## Apps and browser extensions
- **Installing apps** (App Store or `flatpak install`) asks for admin approval. Updates stay automatic.
- **Downloaded programs** (in Downloads, on the Desktop or on a USB drive) don't run until approved, like Gatekeeper on a Mac. When one is blocked, a notification offers **Approve…**. You can also approve from Control Center → **Apps**, or:
  ```bash
  sudo pcos-app-guard approve ~/Downloads/SomeApp.AppImage
  ```
- **Firefox extensions** install only if approved. uBlock Origin is always installed. Approve one by pasting its addons.mozilla.org link in Control Center → **Apps**, or:
  ```bash
  sudo pcos-browser-extensions approve https://addons.mozilla.org/firefox/addon/bitwarden-password-manager/
  ```

## Disk encryption
Tick **Encrypt my data** in the installer's **Installation Destination** and choose a passphrase. After the first login, set up how the drive unlocks:
```bash
sudo pcos-disk-security recovery-key
```
```bash
sudo pcos-disk-security tpm
```
- `recovery-key`: shows a recovery key **once**. Write it down and keep it away from the PC. Without it, a failed TPM or motherboard means the data is lost.
- `tpm`: unlocks automatically on this PC only, as long as Secure Boot is unchanged. Use `tpm-pin` to also type a PIN at boot (recommended for laptops), or `fido2` for a security key.
- `status` shows what's set up. After a BIOS/firmware update asks for the recovery key, run `reseal`.

## Building the installer ISO
GitHub → Actions → **Build RudramOS installer ISO** → Run workflow (platform `amd64`, choose the **variant**). Download the `<variant>-anaconda-iso` artifact.
