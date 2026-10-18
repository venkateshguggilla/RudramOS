# PC OS: Phased Build Roadmap

Companion to [DESIGN.md](DESIGN.md). Each phase lists what gets built, a **Done when** checklist and a rough size:
- **S**: a few days
- **M**: 1–3 weeks
- **L**: a month or more, part-time

**Work in VMs first.** Test on real hardware only once each phase passes in a VM.

```
Track A (OS image)    P0 → P1 → P2 → P3 → P4 → P5 → P6 → P7 → P8 ─┐
Track B (Temp Mon.)        P9a ─ P9b ───────────── P9c → P9d → P9e ├→ P12 → P13 → v1.0
Track C (Cleaner)          P10a ──────────────────────── P10b ─────┤
Track D (Phone)                                    P11 ───────────┘
```
Tracks B and C start on **Windows** (refactor + cross-platform UI) and don't depend on the OS image until their Linux parts begin.

---

## Phase 0: Preparation (S)
- [ ] Choose a working name (can change later)
- [x] Create a GitHub repository for `PC_OS` and enable GitHub Actions + GitHub Container Registry (ghcr.io)
- [ ] Turn on 2FA for GitHub (preferably with a FIDO2 key)
- [ ] **Buy 2 FIDO2 keys** (e.g. 2× YubiKey 5 or 2× Nitrokey 3) and set a PIN on each
- [x] Enable **Hyper-V** on Windows 10 Pro, and create a Gen 2 VM template with **Secure Boot ("Microsoft UEFI Certificate Authority" template) + virtual TPM**, 4 vCPU, 8 GB RAM, 64 GB disk
- [ ] Optional: install WSL2 + Podman for local image builds (CI is the main build path)
- [x] Install `cosign` and generate the **image signing key pair**: public key → `keys/cosign.pub`, private key → GitHub secret + offline backup

**Notes:** the repo is private (installed PCs need a `read:packages` token in `/etc/ostree/auth.json`); VMs live on the external SSD at `D:\PC_OS\VMs`.

**Done when:** the repo exists, the VM template boots a stock Fedora ISO with Secure Boot on, and the cosign keys are stored safely.

---

## Phase 1: Minimal signed image (M): ✅ complete 2026-10-18
- [x] Start from the Universal Blue `image-template`. Create `Containerfile` `FROM ghcr.io/ublue-os/bluefin:stable` (or `base-main`)
- [~] Add PC OS branding basics: `/etc/os-release` name (done), wallpaper, logo (Phase 12)
- [x] GitHub Actions workflow: build → **cosign sign** → push `ghcr.io/<you>/pcos:latest` + dated tags
- [x] Workflow to build an **installer ISO** with `bootc-image-builder`
- [x] Container signature policy in the image (`/etc/containers/policy.json` + `registries.d`) so the PC **only accepts our signed images**
- [x] Automatic update timer (provided by Bluefin's `uupd.timer`)

**Done when:**
- [x] the ISO installs in the Hyper-V VM and boots to GNOME
- [x] pushing a change to Git produces a new image, and the VM updates to it after a reboot
- [x] `bootc rollback` returns to the previous version (07:55 ↔ 08:47 builds, 2026-10-18)
- [x] an unsigned image is **refused** on update (tested with `:unsigned-test`, 2026-10-18)

---

## Phase 2: GPU image variants (M)
- [x] `ARG BASE_IMAGE` + `ARG GPU=none|nvidia|nvidia-legacy` in the Containerfile; driver layer in `build_files/gpu.sh`
- [x] `pcos-nvidia`: based on `bluefin-nvidia-open` (NVIDIA latest driver, open kernel modules)
- [x] `pcos-nvidia-legacy`: NVIDIA **580 LTS** closed modules from Universal Blue's `akmods-nvidia-lts`, matched to the base kernel
- [~] Secure Boot signing: uses the Universal Blue akmods key (`ujust enroll-secure-boot-key`); own PC OS MOK key deferred
- [x] Build matrix in CI: 3 images (`build.yml`) + ISO per variant (`build-disk.yml` `variant` input)
- [x] Signature policy covers all 3 image repos, so switching variants is verified too
- [x] **Driver Assistant**: one ISO for every PC; at login it detects the GPU and offers the matching variant (`pcos-driver-assistant`, `pcos-gpu-detect`, `pcos-gpu-switch`, polkit action), with tests in `tests/test-gpu-detect.sh`
- [x] Repo and all 3 container images public (2026-10-18): PCs pull updates and drivers without a token; signatures verify anonymously

**Done when:**
- [ ] AMD/Intel: `pcos` boots in the VM, and on the dev PC (live USB) the GPU works with the `amdgpu` driver
- [ ] Standard ISO on an NVIDIA PC: Driver Assistant offers the right driver, and after restart + MOK enrollment the driver is active
- [ ] **RTX 3060** PC: `nvidia-smi` works with Secure Boot ON, Wayland desktop, a Steam game runs
- [ ] **GTX 1050 Ti** PC: same checks with the 580 LTS driver

---

## Phase 3: Disk encryption and boot hardening (M)
- [ ] The installer (kickstart in the ISO) sets up **LUKS2** (argon2id) for the whole system
- [ ] First-boot script: `systemd-cryptenroll --tpm2-device=auto --tpm2-pcrs=7` (+ `--tpm2-with-pin` or `--fido2-device` options)
- [ ] Generate the **recovery key** (`systemd-cryptenroll --recovery-key`) and show it once
- [ ] Kernel arguments and sysctl hardening from DESIGN §4.6 (start conservative and test every app)
- [ ] Re-seal flow after firmware updates
- [ ] Document the BIOS password / no-USB-boot recommendation
- [ ] *Stretch:* signed **UKI** + PCR 11 policy

**Done when:**
- [ ] the VM boots and unlocks automatically through the vTPM; with Secure Boot disabled it **asks for the recovery key**
- [ ] the VM disk attached to a different VM can't be unlocked without the recovery key
- [ ] TPM+PIN and FIDO2 unlock both tested (FIDO2 through USB passthrough)

---

## Phase 4: Admin approval modes + Control Center skeleton (L)
- [ ] `/etc/pam.d/pcos-admin` include, used by `sudo` and `polkit-1`; `.standard` and `.strong` variants
- [ ] `pam_u2f` with root-owned `/etc/u2f_mappings`; enrollment through `pamu2fcfg`
- [ ] **`pcosd`** privileged helper (D-Bus system bus, polkit actions `org.pcos.*`): `SetAdminMode`, `RegisterFidoKey`, `RemoveFidoKey`, `ListFidoKeys`
- [ ] **`pcos-control`** app (GTK4/libadwaita, Python): Security page → Admin protection (Standard/Strong, add/remove/test keys)
- [ ] Rule: Strong → Standard needs password **+ key**
- [ ] Recovery path: recovery key → reset to Standard
- [ ] Optional separate admin password (Standard mode)
- [ ] auditd rules for approvals; Activity log page (basic)

**Done when:**
- [ ] Standard: installing a Flatpak asks for the password only
- [ ] Strong: the same action needs password + touch, and fails without the key
- [ ] `sudo` follows the same mode
- [ ] downgrading without the key is refused; recovery reset works

---

## Phase 5: App control + browser extension control (L)
- [ ] polkit: system-wide Flatpak installs need admin approval; `--user` installs turned off
- [ ] **Spike:** validate **fapolicyd** on bootc (rpm trust backend on ostree, trust rules for `/var/lib/flatpak/app`)
- [ ] fapolicyd rules: block executables in `/home`, `/tmp`, `/var/tmp`, `/run/media`; `noexec` mounts
- [ ] "Blocked program" notification → Control Center **Approved apps** page → `pcosd.TrustExecutable` (admin approval)
- [ ] Firefox RPM + `/etc/firefox/policies/policies.json` (DESIGN §4.5), uBlock Origin force-installed
- [ ] Control Center **Browser extensions** page → `pcosd.ApproveExtension` / `RevokeExtension`
- [ ] Optional: Chromium policy equivalent

**Done when:**
- [ ] a downloaded binary/AppImage is blocked; after approval it runs
- [ ] installing a Firefox extension directly is blocked with our message; after approval in Control Center it installs
- [ ] in Strong mode both approvals need the key
- [ ] no regressions: Flatpak apps, Steam, browsers, GNOME extensions still work

---

## Phase 6: Network protection (M)
- [ ] firewalld zones `pcos-public` (default, drop + stealth) and `pcos-home`
- [ ] Remove/disable `sshd`, `cups-browsed`, Avahi announcements, LLMNR/NetBIOS, UPnP
- [ ] NetworkManager dispatcher + Control Center **network trust prompt**; Home requires admin approval
- [ ] Control Center **Sharing** page: file sharing (selected folders, password, auto-off when leaving Home), remote desktop, "Stop all sharing"
- [ ] `bolt` Thunderbolt authorization + IOMMU args

**Done when:**
- [ ] an `nmap` scan from another LAN machine shows **no open ports and no ping reply** on a Public network
- [ ] on Home with file sharing enabled, only the shared folder is reachable, with a password
- [ ] switching to a Public network turns sharing off automatically

---

## Phase 7: USB device authorization (M)
- [ ] USBGuard config (DESIGN §6.1), with initial rules generated at first boot; FIDO2 keys pre-allowed
- [ ] **`pcos-usb-prompt`**: listens on D-Bus, shows Block / Allow once / Always allow → polkit → `applyDevicePolicy`
- [ ] Device class shown in plain words + **BadUSB heuristics** (storage+HID, unexpected network adapter)
- [ ] Block all new devices while the screen is locked
- [ ] udisks2 `nosuid,nodev,noexec`, autorun off, no thumbnails on removable media
- [ ] Control Center **USB devices** page + modes (Ask / Allow HID / Off)

**Done when:**
- [ ] a new flash drive stays invisible until approved; "Always allow" survives a reboot
- [ ] a test BadUSB-style device (e.g. a Pico/Digispark acting as keyboard + storage) is flagged and blocked
- [ ] nothing new connects while the screen is locked
- [ ] the existing keyboard, mouse and FIDO2 keys work without prompts

---

## Phase 8: Privacy presets (M)
- [ ] Turn off countme, ABRT reporting, the connectivity check; chrony NTS
- [ ] NetworkManager MAC randomization, no hostname over DHCP, IPv6 privacy
- [ ] systemd-resolved DNS-over-TLS (Quad9 default), LLMNR/mDNS off
- [ ] Optional tracker blocklist (local resolver layer, selectable list)
- [ ] Firefox privacy policies (strict ETP, telemetry off, HTTPS-only, optional clear-on-exit)
- [ ] WireGuard VPN kill switch; Mullvad Browser / Tor Browser optional installs
- [ ] Metadata Cleaner preinstalled; journald retention
- [ ] Control Center **Privacy** page: Balanced / Maximum / Custom + per-app Flatpak permissions (including network)

**Done when:**
- [ ] a packet capture of a freshly booted idle PC shows **no unexpected outbound connections** (only DoT to the chosen resolver, NTS and update checks)
- [ ] the Wi-Fi MAC differs per network, and DNS queries aren't visible in plain text
- [ ] switching presets applies and reverts cleanly

---

## Phase 9: Temp Monitor port (Track B, L overall)
Repo: `C:\Venky\work\temp_monitor` (or `apps/temp-monitor`)

### 9a: Refactor on Windows (S)
- [ ] Extract `ISensorProvider` from `SensorService`; `WindowsSensorProvider` = the current LibreHardwareMonitor code
- [ ] Keep `Reading` as the shared model; add a `Fan` reading type (RPM, controllable, mode)

### 9b: Avalonia UI on Windows (M)
- [ ] Port `MainWindow` / `MetricCard` / `TrayIcon` from WPF to **Avalonia**
- [ ] Feature parity with the current app on Windows (tray temperature, °F, All sensors, diagnostics, single instance)

### 9c: Linux sensor provider (M)
- [ ] hwmon/proc/amdgpu/NVML/nvme/drivetemp readers (DESIGN §9.1); load `drivetemp` in the image
- [ ] AppIndicator top-bar temperature; XDG autostart
- [ ] RPM in the image + `.desktop` + icon

### 9d: Fan control (L)
- [ ] Root **fan daemon** (D-Bus + polkit): hwmon PWM, NVML, amdgpu fan curve, liquidctl
- [ ] Per-fan Auto / Fixed / Curve, rename, **Identify**, profiles
- [ ] Safety: floor, critical → 100%, crash → BIOS auto, stall alert
- [ ] Windows: fan control through LibreHardwareMonitorLib (same UI)

### 9e: Notifications + history (M)
- [ ] Background **monitor service** (user systemd unit): 1 s polling, SQLite with downsampling, retention setting
- [ ] Overheat warning/critical notifications, cooldown, event log
- [ ] Charts per component (5 m – 30 d), min/avg/max, time above hot, overlays, CSV export, Clear history

**Done when:** on the RTX 3060 PC every fan header and GPU fan can be controlled individually; killing the daemon returns fans to BIOS control; a stress test (`stress-ng`) triggers the overheat notification; history survives a reboot.

---

## Phase 10: PC Cleaner port (Track C, M)
Repo: `C:\Venky\work\pc_cleaner` (or `apps/pc-cleaner`)

### 10a: Platform refactor (on Windows, S)
- [ ] Move `winutil` / `regutil` / `scheduler` behind a `platform` package; the Windows behaviour stays identical; tests keep passing

### 10b: Linux implementation (M)
- [ ] `platform/linux.py`: `/proc`, SIGTERM→SIGKILL, `gio trash`, FileManager1, `xdg-open`, systemd user timer, `.desktop` shortcut
- [ ] XDG paths for settings and reports
- [ ] Linux cleaner catalog (DESIGN §9.2), including Flatpak browser/app paths
- [ ] Admin items through a `pcosd`/pkexec helper (journal vacuum, coredumps, Flatpak unused, old deployments keeping 1 rollback)
- [ ] CleanerML rule support (BleachBit format)
- [ ] Protected-path list for Linux; Large Files marks `~/.var` / dot-folders as *(app file)*
- [ ] Linux test suite (temp folders, throwaway SQLite); registry tests Windows-only
- [ ] RPM in the image

**Done when:** `python -m pccleaner scan` / `clean` work on PC OS; Firefox history cleaned with bookmarks kept; a scheduled clean runs from the systemd timer, and a missed run happens after the next boot.

---

## Phase 11: Android phone integration (Track D, S–M)
- [ ] GSConnect preinstalled (or Valent), enabled in the GNOME session
- [ ] Firewall: KDE Connect ports only in `pcos-home`
- [ ] scrcpy + "Show phone screen" action (USB / wireless ADB pairing helper)
- [ ] Control Center **Phone** page: pairing, per-phone permissions
- [ ] Experiment: Bluetooth HFP hands-free calls through PipeWire on the test phone; ship as "experimental" only if reliable

**Done when:** with a test Android phone: notifications + reply, SMS send/receive, call alert + mute, file transfer, clipboard, screen control over USB and Wi-Fi all work; on a Public network the phone can't connect.

---

## Phase 12: First-boot setup and polish (M)
- [ ] First-boot flow (DESIGN §10): admin mode, keys, disk unlock, recovery key, privacy preset, network trust, MOK enrollment, phone
- [ ] Branding: name, logo, wallpapers, boot splash (Plymouth), GNOME defaults (dock, apps)
- [ ] Control Center **Updates** page (version, update now, rollback)
- [ ] User guide (`docs/USER_GUIDE.md`): keys, recovery, USB prompts, extensions, phone

**Done when:** a non-technical person can install PC OS from USB and finish setup without help.

---

## Phase 13: Hardening review, hardware testing, v1.0 (M)
- [ ] Full test pass on: Hyper-V VM, RTX 3060 PC, GTX 1050 Ti PC, dev PC (AMD 5500M; T2 caveats)
- [ ] Security review: polkit actions, `pcosd` input validation, fan daemon API, file permissions, `nmap` scan, USB tests
- [ ] Lockout drills: lose a key, all keys, TPM change, bad update → recovery works every time
- [ ] Performance and battery check of the hardening flags
- [ ] Tag **v1.0**, publish ISOs + checksums + signature verification instructions

---

## Later / optional
- `pcos-t2` image variant for Intel Macs with the T2 chip (t2linux kernel/firmware)
- Signed UKI + own Secure Boot keys (full custom chain)
- `hardened_malloc` in the Maximum preset
- Built-in encrypted backup page
- Native GTK4 UI for PC Cleaner
- Windows app support through a locked-down VM
- Own Flatpak repo for curated apps

---

## Immediate next steps
1. Phase 0 checklist: GitHub repo, Hyper-V VM template, buy FIDO2 keys, cosign keys
2. Phase 1: first signed image + ISO booting in the VM
3. In parallel: Phase 9a (Temp Monitor refactor) and Phase 10a (PC Cleaner refactor) on Windows
