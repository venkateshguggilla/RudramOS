# RudramOS: Phased Build Roadmap

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
- [~] Add RudramOS branding basics: `/etc/os-release` name (done), wallpaper, logo (Phase 12)
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
- [~] Secure Boot signing: uses the Universal Blue akmods key (`ujust enroll-secure-boot-key`); own RudramOS MOK key deferred
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
- [~] **LUKS2** for the whole system: chosen in the installer (Installation Destination → **Encrypt my data**); Fedora's installer uses LUKS2 + argon2id. Kept optional, not forced by kickstart (forced autopart could wipe the wrong disk)
- [x] Unlock tool `pcos-disk-security`: `tpm` (sealed to PCR 7), `tpm-pin`, `fido2`, `status`; tests in `tests/test-disk-security.sh`
- [x] **Recovery key**: `pcos-disk-security recovery-key` (shown once, replaces the old one); `remove-passphrase` refuses unless a recovery key + TPM/FIDO2 exist
- [x] Initramfs includes TPM2/FIDO2 unlock (`90-pcos-unlock.conf`); legacy NVIDIA image now rebuilds its initramfs so the unlock screen has a display
- [x] Conservative kernel arguments (`kargs.d/10-pcos-hardening.toml`) and sysctl hardening (`sysctl.d/60-pcos-hardening.conf`); network sysctls deferred to Phase 6
- [x] Re-seal flow after firmware updates: `pcos-disk-security reseal`
- [ ] Document the BIOS password / no-USB-boot recommendation (user guide, Phase 12)
- [ ] GUI for all of this in Control Center (Phase 4)
- [ ] *Stretch:* signed **UKI** + PCR 11 policy

**Done when:**
- [ ] the VM boots and unlocks automatically through the vTPM; with Secure Boot disabled it **asks for the recovery key**
- [ ] the VM disk attached to a different VM can't be unlocked without the recovery key
- [ ] TPM+PIN and FIDO2 unlock both tested (FIDO2 through USB passthrough)

---

## Phase 4: Admin approval modes + Control Center skeleton (L)
**Part 1: approval engine (done)**
- [x] `/etc/pam.d/pcos-admin` include, used by `sudo` and `polkit-1` (build fails if the routing can't be applied); templates `/usr/share/pcos/pam/pcos-admin.{standard,strong}`
- [x] Strong = password (`substack system-auth`) + `pam_u2f` touch, keys in root-owned `/etc/u2f_mappings`, origin `pam://pcos`
- [x] `pcos-admin-mode` (`status`, `add-key`, `remove-keys`, `test`, `strong`, `standard`); packages `pam-u2f`, `pamu2fcfg`, `pamtester`
- [x] Lockout protection: Strong refused without a registered key and a passing password + touch test (`pamtester` on a temporary PAM service); can't remove your own keys while in Strong mode; leaving Strong needs the key because it runs through sudo
- [x] Tests: `tests/test-admin-mode.sh` (21 cases, stubbed key tools) in CI
- [ ] Verify on real hardware with FIDO2 keys (Hyper-V can't pass USB devices to Linux VMs)
- [ ] Recovery procedure when all keys are lost (installer shell + recovery key), tested

**Part 2: Control Center**
- [x] **`pcos-control`** app (GTK4/libadwaita, Python, "RudramOS Control Center" in the app grid) with pages **Security** (admin mode, keys), **Disk** (encryption, TPM, Secure Boot, unlock setup), **Graphics** (detected GPU, install driver via pkexec) and **System** (version, pending update, check for updates, roll back)
- [x] Status is read without root (`pcos_control/status.py`, 10 unit tests in CI); steps that need typing or a key touch open in a terminal via `pcos-terminal-run`
- [ ] Replace the terminal steps with native dialogs through a **`pcosd`** privileged helper (D-Bus system bus, polkit actions `org.pcos.*`)
- [ ] Optional separate admin password (Standard mode)
- [ ] auditd rules for approvals; Activity log page (basic)

**Done when:**
- [ ] Standard: installing a Flatpak asks for the password only
- [ ] Strong: the same action needs password + touch, and fails without the key
- [ ] `sudo` follows the same mode
- [ ] downgrading without the key is refused; recovery reset works

---

## Phase 5: App control + browser extension control (L)
- [x] Flatpak install/remove/repo changes need admin approval: `/etc/polkit-1/rules.d/00-pcos-flatpak.rules` (AUTH_ADMIN_KEEP), sorting before Fedora's rule that lets `wheel` install silently; updates stay automatic
- [x] **App approval (Gatekeeper-style)** with fapolicyd, `trust = file`, `integrity = sha256`, RudramOS rules replace Fedora's strict defaults: programs in each user's **Downloads** and **Desktop**, on **USB drives**, and **user-level Flatpaks** run only after approval; everything else (system, Flatpaks, Steam games, Homebrew, dev tools) is untouched
- [x] `pcos-app-guard` (`status`, `list`, `approve`, `revoke`, `on`, `off`, `regenerate-rules`); per-user rules generated at boot (`pcos-app-guard-rules.service`, honours localized XDG folders); tests `tests/test-app-guard.sh`
- [x] "Program blocked" notification with **Approve…** (`pcos-app-guard-notify`, reads fapolicyd's journal; admin users)
- [x] Firefox (Flatpak, via the `org.mozilla.firefox.systemconfig` extension dir, plus `/etc/firefox` for an RPM Firefox): all extensions blocked except approved ones; uBlock Origin always installed; telemetry off, strict tracking protection, HTTPS-only
- [x] `pcos-browser-extensions` (`list`, `approve <AMO link | id>`, `revoke`, `apply`; looks the id up on addons.mozilla.org; approved ones install automatically); written at boot by `pcos-firefox-policy.service`; tests `tests/test-browser-extensions.sh`
- [x] Control Center **Apps** page: approve a program (file picker), turn app approval on/off, approve/remove browser extensions by pasting a link; polkit actions `org.pcos.app-guard` and `org.pcos.browser-extensions`
- [ ] Known gaps, documented: running a blocked file through an interpreter (`bash file.sh`, `python file.py`) or moving it to another folder first isn't blocked (same class of limit as macOS Gatekeeper); Chromium-family browsers not covered yet

**Done when:**
- [ ] a downloaded binary/AppImage is blocked; after approval it runs
- [ ] installing a Flatpak from the App Store asks for admin approval
- [ ] installing a Firefox extension directly is blocked with our message; after approval in Control Center it installs
- [ ] in Strong mode both approvals need the key
- [ ] no regressions: Flatpak apps, Steam, browsers, GNOME extensions still work

---

## Phase 6: Network protection (M)
- [x] firewalld zones `pcos-public` (default) and `pcos-home` in `/usr/lib/firewalld/zones`: target DROP (stealth: no ping replies, no "closed" answers), `icmp-block-inversion` allowing only IPv6 neighbour discovery, router adverts, path-MTU and error ICMP; replaces Fedora Workstation's zone that opened ports 1025–65535; build validates with `firewall-offline-cmd --check-config`
- [x] `pcos-network` (`status`, `trust <network> home|public`, `share <what> on|off`, `stop-sharing`, `apply`); trusted list `/etc/pcos/trusted-networks` (root-owned); polkit action `org.pcos.network`; tests `tests/test-network.sh` (27 cases)
- [x] NetworkManager hook `50-pcos-network-trust` (root) puts each Wi-Fi/Ethernet connection in the zone the admin chose, overriding a zone set by editing the connection profile
- [x] "Connected to X: Home or Public?" notification (`pcos-network-prompt`); Home needs admin approval; unanswered = Public
- [x] Sharing (printer discovery, phone link, remote desktop, file sharing, Steam Remote Play, SSH) can only be opened in `pcos-home`, so it's closed automatically on any other network; SSH also starts/stops `sshd`
- [x] Nothing announcing: `sshd` disabled, `cups-browsed` masked, Avahi `disable-publishing=yes`, LLMNR/mDNS off in systemd-resolved
- [x] Network sysctls: no ICMP redirects or source routing, broadcast-ping and bogus-error ignore, SYN cookies, RFC 1337 (`61-pcos-network.conf`)
- [x] Control Center **Network** page: active networks with Make Home / Make Public, sharing switches, Stop all sharing
- [ ] `bolt` Thunderbolt authorization is Fedora's default (GNOME prompts); IOMMU kernel flags deferred (hardware compatibility)
- [ ] Known limit: a network is recognised by its NetworkManager profile, so a fake Wi-Fi with the same name and password as a Home network would be treated as Home (same as macOS/Windows)

**Done when:**
- [ ] an `nmap` scan from another LAN machine shows **no open ports and no ping reply** on a Public network
- [ ] on Home with file sharing enabled, only the shared folder is reachable, with a password
- [ ] switching to a Public network turns sharing off automatically

---

## Phase 7: USB device authorization (M)
- [x] USBGuard: implicit block, apply-policy for present and inserted devices, IPC for root only (Fedora lets `wheel` talk to the daemon directly; removed so approvals always go through admin approval), `rules.d` folder
- [x] First boot trusts the devices already connected (`pcos-usb-firstboot`, `usbguard generate-policy`); USBGuard `Requires=` it, so if that step fails USBGuard doesn't start and USB keeps working (fails open)
- [x] `pcos-usb-describe`: devices in plain words (Storage, Keyboard, Security key, Network adapter, ...) with **BadUSB warnings**: storage that can type, or storage that's also a network adapter = danger; network adapters and keyboards = caution; tests `tests/test-usb-describe.sh` (15 cases)
- [x] `pcos-usb` (`status`, `devices`, `allow <id> [--permanent]`, `block`, `rules`, `forget`, `mode ask|allow-input|off`); **security keys are always allowed permanently** (otherwise a blocked key couldn't approve itself in Strong mode); `allow-input` uses `match-all { 03:01:01 03:01:02 03:00:00 }` so keyboard+storage sticks still ask; polkit action `org.pcos.usb`; tests `tests/test-usb.sh` (19 cases)
- [x] Root watcher (`pcos-usb-watch`) publishes blocked devices to `/run/pcos/usb-pending/`; plain hubs are allowed automatically (devices behind them are still checked)
- [x] Desktop prompt (`pcos-usb-prompt`): Keep blocked / Allow once / Always allow, red warning + no "always" for danger devices; **nothing is asked while the screen is locked**
- [x] GNOME: autorun off, new drives not opened automatically, GNOME's own USBGuard integration off (it allows devices on unlock); `usbguard-dbus` deliberately not installed
- [x] Programs on USB drives already need approval (Phase 5 fapolicyd rules for `/run/media`)
- [x] Control Center **USB** page: waiting devices with Allow buttons, protection mode, connected and always-allowed devices
- [ ] Optional ClamAV scan on mount (later)
- [ ] Recovery if no USB keyboard works (e.g. a desktop's only keyboard replaced): at the boot menu press `e` and add `systemd.mask=usbguard.service` (GRUB runs before Linux, so its keyboard works); verify on real hardware

**Done when:**
- [ ] a new flash drive stays invisible until approved; "Always allow" survives a reboot
- [ ] a test BadUSB-style device (e.g. a Pico/Digispark acting as keyboard + storage) is flagged and blocked
- [ ] nothing new connects while the screen is locked
- [ ] the existing keyboard, mouse and FIDO2 keys work without prompts

---

## Phase 8: Privacy presets (M)
- [x] No phone-home in any preset: `rpm-ostree-countme` masked; GNOME problem reports, usage stats and location off (dconf defaults); `DO_NOT_TRACK`, Homebrew/.NET/PowerShell/Next.js telemetry opt-outs for the session and terminals
- [x] Time from **NTS** servers (Cloudflare, Netnod, PTB) instead of plain NTP pools (chrony)
- [x] `pcos-privacy` (`status`, `preset balanced|maximum`, `set <option> <value>`, `apply`), state `/etc/pcos/privacy.conf`; tests `tests/test-privacy.sh` (36 cases)
  - MAC: random while scanning, stable per Wi-Fi network; wired per-network (Maximum); IPv6 privacy addresses; hostname not sent over DHCP
  - DNS-over-TLS through systemd-resolved (Quad9 / Mullvad / Cloudflare); NetworkManager no longer passes the network's plain-text DNS servers (`dns=none`), so lookups don't leak. Balanced = opportunistic, Maximum = strict. Option `network` uses the Wi-Fi's own DNS for login pages that need it
  - Tracker blocking: Mullvad's filtering DoT resolver `base.dns.mullvad.net` (194.242.2.4 / 2a07:e340::4) instead of a local blocklist service (verify its filter list)
  - Captive-portal check on in Balanced, off in Maximum; journald retention 14 / 3 days; Firefox clear-on-exit in Maximum (merged into the Firefox policy from `/etc/pcos/firefox-policies.d/`)
- [x] **VPN kill switch** `pcos-killswitch` (`on`, `off`, `status`, `load`): nftables table allowing only VPN interfaces, the WireGuard servers (resolved from NetworkManager connections, bracketed IPv6 handled), the local network, DHCP and IPv6 neighbour discovery; rules checked with `nft -c` before loading; `pcos-killswitch.service` reloads it at boot before networking; tests `tests/test-killswitch.sh` (18 cases)
- [x] Metadata Cleaner preinstalled (Flatpak preinstall)
- [x] Control Center **Privacy** page: presets, DNS provider, tracker blocking, strict DNS, wired MAC, login-page detection, Firefox forget-on-close, log retention, recent files (per user), VPN kill switch; polkit actions `org.pcos.privacy`, `org.pcos.killswitch`
- [ ] Mullvad Browser / Tor Browser: install from the App Store when wanted (not preinstalled)
- [ ] Kill switch covers WireGuard VPNs set up in NetworkManager; OpenVPN and VPN apps with their own tunnels aren't detected yet

**Done when:**
- [ ] a packet capture of a freshly booted idle PC shows **no unexpected outbound connections** (only DoT to the chosen resolver, NTS and update checks)
- [ ] the Wi-Fi MAC differs per network, and DNS queries aren't visible in plain text
- [ ] switching presets applies and reverts cleanly

---

## Phase 9: Temp Monitor port (Track B, L overall)
Repo: `C:\Venky\work\temp_monitor` (or `apps/temp-monitor`)

### 9a: Refactor on Windows (S)
- [x] Extract `ISensorProvider` from `SensorService`; `WindowsSensorProvider` = the current LibreHardwareMonitor code (projects `TempMonitor.Core` + `TempMonitor.Sensors.Windows`; WPF app builds on them; 15 Core unit tests)
- [x] Keep `Reading` as the shared model; graph/history logic moved to `CardHistory` in Core
- [ ] Add a `Fan` reading type (RPM, controllable, mode): moved to 9d with fan control

### 9b: Avalonia UI on Windows (M)
- [x] Port `MainWindow` / `MetricCard` / `TrayIcon` from WPF to **Avalonia 11.3.22** (`TempMonitor.Avalonia`; Avalonia 12 needs the .NET 9/10 SDK compiler, so 11.3 for now); platform layer (`Platform.cs`) ready for a Linux provider
- [x] Feature parity with the current app on Windows: verified side by side on the MacBook (live CPU/GPU/RAM/SSD cards, graphs, banner, status line); single-file release exe 45 MB (WPF 73 MB)
- [ ] Still to verify by hand: tray icon number rendering, elevated run (CPU/RAM temps via PawnIO), start-with-Windows task switching to the new exe

### 9c: Linux sensor provider (M)
- [x] `TempMonitor.Sensors.Linux` (no root): coretemp / k10temp / zenpower + `/proc/stat` + cpufreq; amdgpu hwmon/sysfs (edge, junction, busy, VRAM, power, clock); NVML for NVIDIA; Intel iGPU noted; `/proc/meminfo` + jc42/spd5118; NVMe/drivetemp hwmon, `/proc/diskstats`, udev for USB, space traced through partitions and LUKS/device-mapper; GPU names from `pci.ids`
- [x] Avalonia app targets `net8.0-windows` + `net8.0` (Linux): Unix-socket single instance, XDG autostart, `--print` for terminals; compressed single-file `linux-x64` publish (42 MB)
- [x] 25 tests against fake `/sys` and `/proc` trees (MacBook, NVIDIA desktop, Ryzen); verified on real Linux (WSL Ubuntu 24.04) with `--print`
- [x] RudramOS image: load `drivetemp` (`/usr/lib/modules-load.d`), ship Temp Monitor (built and unit-tested in a Containerfile stage from a pinned commit of github.com/venkateshguggilla/temp-monitor; installed to `/usr/lib/temp-monitor` + `temp-monitor` command + `.desktop` + icon; `--print` smoke test in the build)
- [ ] AppIndicator top-bar icon check on GNOME (needs a real RudramOS session)
- [ ] Real-hardware check on RudramOS: MacBook (coretemp, amdgpu, NVMe behind LUKS), RTX 3060 (NVML), GTX 1050 Ti (NVML 580)

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

**Done when:** `python -m pccleaner scan` / `clean` work on RudramOS; Firefox history cleaned with bookmarks kept; a scheduled clean runs from the systemd timer, and a missed run happens after the next boot.

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

**Done when:** a non-technical person can install RudramOS from USB and finish setup without help.

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
