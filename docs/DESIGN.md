# RudramOS: Design Document

Status: draft v0.1 (2026-10-18)
Working name: **RudramOS** (final name and branding are still to be decided; see [Open decisions](#16-open-decisions))

---

## 1. Overview

RudramOS is a personal desktop operating system for x86-64 PCs. It aims to be **secured like a Mac and as easy to use as a Mac**. Users can install apps and change settings freely. Every system-level change needs explicit approval, the disk can only be read on the PC it's installed on, nothing tracks the user, and devices on the network or plugged into USB get no access without permission.

### 1.1 Goals
| # | Goal |
|---|---|
| G1 | **Secure by default**: an immutable OS, signed updates, verified boot, encrypted disk |
| G2 | **Mac-like usability**: a polished GNOME desktop; installs and changes need only a password |
| G3 | **Optional physical-key protection**: the user can choose to require a FIDO2 USB key for admin actions |
| G4 | **Only this PC can read the disk**: LUKS2 encryption sealed to the TPM |
| G5 | **No tracking**: no telemetry, private networking, a hardened browser |
| G6 | **Nothing gets in without permission**: other network devices and USB devices are blocked until approved |
| G7 | **Built-in tools**: hardware monitor with fan control, PC cleaner, Android phone integration |
| G8 | **Choices, not lockdown**: security and privacy levels are user-selectable presets |

### 1.2 Non-goals
- Writing a new kernel or a distribution from scratch. We build on Fedora.
- Enterprise lockdown: domain allowlists, banning installs, central fleet management. These were considered and rejected as too restrictive for personal use.
- Running Windows apps natively. A VM can be added later if needed.
- iPhone integration (Apple limits these features to Macs).

---

## 2. Platform choice

### 2.1 Options considered
| Path | Description | Verdict |
|---|---|---|
| **A** | Immutable Fedora **bootc** image (container-built OS) | ✅ **Chosen** |
| B | Traditional custom distro (Linux From Scratch / Buildroot / Yocto / archiso) | ❌ We'd have to patch every package ourselves forever |
| C | Our own kernel (Rust, OSDev) | ❌ Years of work before it supports real hardware or apps; possible as a separate learning project |
| D | A seL4/Genode microkernel OS | ❌ Too little desktop hardware and app support |

### 2.2 Why Fedora bootc
- Fedora provides the kernel, drivers, security fixes and thousands of packages. We concentrate on the top layer: policy, user experience and built-in apps.
- **bootc** builds the whole OS from a `Containerfile`. The output is a signed OCI image that PCs pull and apply **atomically**, and the previous version always stays available for **rollback**.
- `/usr` is **read-only** and integrity-checked (composefs). This is our equivalent of macOS's System Integrity Protection.
- Proven in practice: Bluefin, Aurora, Bazzite and secureblue (Universal Blue / BlueBuild) are all built this way.
- SELinux is enforcing by default, Secure Boot is supported, and the release cadence is fast.

### 2.3 Base image
- **Desktop:** GNOME, the closest match to the Mac look and feel.
- **Base:** `ghcr.io/ublue-os/bluefin` (polished GNOME) **or** `ghcr.io/ublue-os/base-main` (leaner). Default plan: **Bluefin**, plus selected hardening from **secureblue**.
- **Build tooling:** the Universal Blue `image-template` (Containerfile + GitHub Actions + cosign) to start; **BlueBuild** recipes if the build becomes more modular.

---

## 3. System architecture

```
                    ┌──────────────────────────────────────────────┐
  Git repo ───────► │  GitHub Actions CI                           │
  (Containerfile,   │  build 3 image variants → cosign sign →      │
   configs, apps)   │  push to ghcr.io → build ISO (bootc-image-   │
                    │  builder)                                    │
                    └───────────────┬──────────────────────────────┘
                                    │ signed OCI images
                                    ▼
┌─────────────────────────── PC running RudramOS ───────────────────────────┐
│ UEFI Secure Boot → shim → GRUB/UKI → signed kernel → initrd            │
│   └─ TPM2 unseals LUKS2 key (opt. PIN / FIDO2)                          │
│                                                                         │
│ /usr  (read-only, composefs, from signed image)                         │
│ /etc  (machine config, 3-way merged on update)                          │
│ /var  (state: Flatpaks, logs, USBGuard rules, history DBs)              │
│ /home (user data)            — all on the encrypted LUKS2 volume        │
│                                                                         │
│ Policy services: firewalld · USBGuard · fapolicyd · SELinux · polkit    │
│ RudramOS services:  pcosd (root helper) · pcos-usb-prompt · monitor svc    │
│                  · fan daemon                                           │
│ Apps: Control Center · Temp Monitor · PC Cleaner · GSConnect · scrcpy   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.1 Image variants (graphics drivers)
All variants are built from one recipe; only the GPU driver layer differs.

| Image | For | Driver |
|---|---|---|
| `pcos` | AMD and Intel GPUs (e.g. Radeon Pro 5500M) | Open drivers in the kernel + Mesa |
| `pcos-nvidia` | NVIDIA Turing and newer: RTX 20/30/40/50, GTX 16 (e.g. **RTX 3060**) | NVIDIA latest, open kernel modules |
| `pcos-nvidia-legacy` | NVIDIA Pascal/Maxwell: GTX 10 series (e.g. **GTX 1050 Ti**) | NVIDIA **580xx** legacy branch (RPM Fusion / negativo17); expected end of life around 2028 |

NVIDIA kernel modules are **pre-built and signed** by Universal Blue's akmods pipeline:
- `pcos-nvidia` inherits them from `bluefin-nvidia-open`.
- `pcos-nvidia-legacy` installs `ghcr.io/ublue-os/akmods-nvidia-lts:coreos-stable-<fedora>-<kernel>` (580 branch, closed modules), always matched to the base image's exact kernel (`build_files/gpu.sh`).

**Driver Assistant** (users never pick a variant by hand): everyone installs from the standard `pcos` ISO. At login, `pcos-driver-assistant` (XDG autostart) runs `pcos-gpu-detect`, which classifies the display controllers from `lspci` PCI IDs:

| NVIDIA device ID | Generation | Variant |
|---|---|---|
| ≥ 0x1E00 | Turing and newer | `pcos-nvidia` |
| 0x1340–0x1DFF | Maxwell / Pascal / Volta | `pcos-nvidia-legacy` |
| < 0x1340 | Kepler and older | `pcos` (nouveau; no current driver) |

If the installed variant (`/usr/share/pcos/gpu-variant`) doesn't match, a notification offers **Install driver / Not now / Don't ask again**. Installing runs `pkexec pcos-gpu-switch <variant>` (polkit action `org.pcos.driver-assistant.switch`, admin approval) → a signature-checked `bootc switch`, plus queued MOK enrollment on Secure Boot PCs → "Restart now". This also works in reverse: a disk moved to a PC without NVIDIA is offered the standard variant. `pcos-driver-assistant --check` shows the result without changing anything.

They're signed with the **Universal Blue akmods key**, which Bluefin already ships. Users enroll it once for Secure Boot (`ujust enroll-secure-boot-key`, MOK password `universalblue`). Signing with our own RudramOS MOK key is deferred to the UKI / own-keys work ("Later / optional" in the roadmap).

### 3.2 Updates and rollback
- `bootc upgrade` runs automatically on a timer: it downloads in the background and applies on the next reboot.
- Update policy: images are only accepted if they carry a valid **cosign signature** from the RudramOS key (`/etc/containers/policy.json` set to `sigstore` for our registry).
- Rollback: `bootc rollback`, or pick the previous entry in the boot menu.
- The PC Cleaner "old OS versions" item always keeps **one rollback deployment**.

### 3.3 Where software comes from
| Type | Source | Who can install |
|---|---|---|
| Core OS, drivers, built-in apps | The image (RPMs baked in at build time) | Only the image maintainer, through a new signed image |
| Desktop apps | **Flatpak** (Flathub + an optional RudramOS repo) | The user, after **admin approval** |
| Extra system packages | `rpm-ostree install` (layering) | The user, after **admin approval** (discouraged; prefer Flatpak) |
| Downloaded binaries/AppImages | — | Blocked until approved (see §4.4) |

---

## 4. Security design

### 4.1 Boot chain
- **UEFI Secure Boot is on.** Fedora's Microsoft-signed `shim` loads GRUB and the Fedora-signed kernel. Our NVIDIA modules are signed with the RudramOS key, enrolled in MOK.
- **Phase 2 hardening:** a signed **Unified Kernel Image (UKI)** (kernel + initrd + kernel command line in one signed file), so the initrd and boot parameters can't be tampered with.
- **The kernel only loads signed modules** (`module.sig_enforce=1`), and lockdown runs in `integrity` mode.
- **Setup recommendation:** set a UEFI/BIOS password and disable booting from USB (documented in first-boot setup).

### 4.2 Disk encryption (FileVault equivalent)
- **LUKS2** with AES-256-XTS (argon2id key derivation) covering root, `/var` and `/home`, with swap encrypted or zram only.
- **Key slots:**
  | Slot | Purpose |
  |---|---|
  | TPM2 | Automatic or PIN-protected unlock, sealed to **PCR 7** (Secure Boot state); later also a signed PCR 11 policy once UKI is used |
  | Optional TPM2+PIN or FIDO2 | Stronger unlock (user's choice) |
  | Recovery key | A high-entropy key shown once at setup for the user to store offline |
  | (Install passphrase) | Removed after TPM enrollment, or kept as the user chooses |
- **Result:** if the drive is moved to another PC, the TPM there can't unseal it, so the drive is unreadable. If Secure Boot is turned off or the boot chain is changed, the TPM refuses to unseal and asks for the recovery key.
- **Unlock options at first boot:** `TPM only` (default) / `TPM + PIN` (recommended for laptops) / `FIDO2 key`.
- **Tooling:** `pcos-disk-security` (`status`, `tpm`, `tpm-pin`, `fido2`, `recovery-key`, `reseal`, `remove-*`), a wrapper around `systemd-cryptenroll --tpm2-device=auto --tpm2-pcrs=7 [--tpm2-with-pin=yes]` / `--fido2-device=auto`. The initramfs carries the `tpm2-tss`, `fido2` and `pkcs11` dracut modules, and systemd-cryptsetup picks up enrolled tokens automatically, so no extra kernel arguments are needed. Encryption is chosen in the installer (optional, recommended).
- **Firmware updates** can change PCR values, so the update flow re-seals the key, with the recovery key as a fallback.

### 4.3 Admin approval modes (Standard / Strong)
Every privileged action goes through **one shared PAM include**, `/etc/pam.d/pcos-admin`, used by `sudo` and `polkit-1`.

| Mode | `/etc/pam.d/pcos-admin` content | User experience |
|---|---|---|
| **Standard** (default, Mac-like) | the system password stack only | Enter your password |
| **Strong** | password stack **+** `auth required pam_u2f.so authfile=/etc/u2f_mappings cue pinverification=1 origin=pam://pcos appid=pam://pcos` | Password **+ touch the FIDO2 key** |

- **Key registry:** `/etc/u2f_mappings` (root-owned, 0644), so user-level malware can't add keys. At least 2 keys are recommended: main + backup.
- **Switching modes** happens in Control Center → Security → Admin protection:
  - Standard → Strong: admin password, then register the key(s), then a test touch
  - Strong → Standard: password **+ key** (stops an attacker who only has the password from downgrading)
- **Lost all keys:** boot into recovery with the **recovery key**, which resets to Standard mode.
- **Login** stays password-only by default. Requiring the key at login is optional.
- **Optional:** a separate **admin password**, different from the login password, for Standard mode.
- **What needs approval:** app install/remove, OS update/rollback/rebase, `sudo`, system settings (users, firewall, network trust, Secure Boot, date/time, drivers), approving a downloaded program, browser extension changes, USB device approval, enabling sharing, lowering fan safety limits.
- **What doesn't:** normal use, Wi-Fi/Bluetooth connections, brightness/volume, fan profile switching, cleaning user-level items.

### 4.4 App control (Gatekeeper equivalent)
- **Flatpak installs/removals** are system-wide and need admin approval through polkit (`org.freedesktop.Flatpak.*`). User-level (`--user`) installs are turned off by polkit rule.
- **fapolicyd** app approval (implemented in Phase 5, `pcos-app-guard`):
  - Blocked until approved: programs in each user's **Downloads** and **Desktop** (localized XDG names honoured), on **USB drives** (`/run/media`, `/media`), and **user-level Flatpaks** (`~/.local/share/flatpak`, which closes the "install without approval" gap)
  - Everything else runs normally: system programs, system Flatpaks, Steam games, Homebrew and developer tools. A strict "only trusted binaries anywhere" policy was rejected because it breaks games and dev tools, and the user asked for Mac-like freedom.
  - `trust = file` (approved files only; no rpmdb dependency on ostree), `integrity = sha256` (an approved file that changes needs approving again); root is never restricted
  - **"Allow this app"** flow: a blocked launch produces a notification with **Approve…** → admin approval (pkexec) → `fapolicyd-cli --file add` to `trust.d/pcos-approved`. Also from Control Center → Apps (file picker) or `sudo pcos-app-guard approve <file>`
  - Known limits (like macOS Gatekeeper): running a file through an interpreter (`bash x.sh`, `python x.py`) or moving it to another folder first bypasses the check
- **SELinux** stays enforcing. Toolbox/distrobox/podman are kept for the admin, and developers can enable them.

### 4.5 Browser extension control
- **Firefox** (Bluefin ships it as a Flatpak) is managed through the `org.mozilla.firefox.systemconfig` Flatpak extension directory (`/var/lib/flatpak/extension/org.mozilla.firefox.systemconfig/<arch>/stable/policies/policies.json`, root-owned), plus `/etc/firefox/policies/policies.json` for an RPM Firefox. `pcos-browser-extensions apply` writes both at boot from `/usr/share/pcos/firefox/policies.base.json` + the approved list `/etc/pcos/browser-extensions.json`:
  ```json
  {
    "policies": {
      "ExtensionSettings": {
        "*": { "installation_mode": "blocked",
               "blocked_install_message": "Extensions need admin approval. Open Control Center → Browser extensions." },
        "uBlock0@raymondhill.net": { "installation_mode": "force_installed",
               "install_url": "https://addons.mozilla.org/firefox/downloads/latest/ublock-origin/latest.xpi" }
      },
      "DisableTelemetry": true,
      "DisableFirefoxStudies": true,
      "DisablePocket": true,
      "EnableTrackingProtection": { "Value": true, "Cryptomining": true, "Fingerprinting": true, "Locked": false },
      "HttpsOnlyMode": "enabled",
      "DNSOverHTTPS": { "Enabled": false, "Locked": true }
    }
  }
  ```
- **Control Center → Browser extensions:** search by AMO link or ID → admin approval (password, or password + key) → `pcosd` adds `{"installation_mode": "allowed"}` (or `normal_installed` with an `install_url`) → Firefox picks it up on restart.
- Removing approval works the same way.
- Approved extensions keep working without the key. Only **changes** need it.
- Chromium-family browsers (optional): the same model through `/etc/chromium/policies/managed/*.json` (`ExtensionInstallBlocklist: ["*"]` + `ExtensionInstallAllowlist`).

### 4.6 Kernel and system hardening
Selected from secureblue / KSPP, avoiding settings known to break apps.
- **Kernel parameters:** `init_on_alloc=1 init_on_free=1 slab_nomerge page_alloc.shuffle=1 randomize_kstack_offset=on module.sig_enforce=1 iommu=force` (+ `intel_iommu=on` / `amd_iommu=force_isolation` where safe), `lockdown=integrity`
- **sysctl:** `kernel.kptr_restrict=2`, `kernel.dmesg_restrict=1`, `kernel.kexec_load_disabled=1`, `kernel.yama.ptrace_scope=1`, `fs.protected_{symlinks,hardlinks,fifos,regular}`, `net.ipv4.conf.*.rp_filter=1`, ICMP redirects off, `tcp_syncookies=1`
- **Kept enabled:** unprivileged user namespaces (needed by the Flatpak sandbox and browsers)
- **Optional (Maximum preset):** `hardened_malloc` globally, after a compatibility check
- **Services:** no `sshd` by default, no `cups-browsed`, Avahi off by default, Bluetooth off by default

### 4.7 Session security
- Password quality rules (`pwquality`), `faillock` (lockout after repeated failures), automatic screen lock (5 min default)
- Optional: FIDO2 or fingerprint at login
- The first user is an admin (`wheel`). Extra family accounts are standard users who can't approve changes.

### 4.8 Audit
- `auditd` records admin approvals, fapolicyd denials, USBGuard decisions and firewall changes
- Control Center → Security → **Activity log** shows these in plain language
- Short `journald` retention (privacy, see §7)

---

## 5. Network protection

### 5.1 Firewall
- **firewalld** with two custom zones:
  | Zone | Inbound | Notes |
  |---|---|---|
  | `pcos-public` (default) | **Drop everything**, no ICMP echo reply (stealth); only IPv6 neighbour discovery, router adverts, path-MTU and error ICMP allowed (`icmp-block-inversion`) | Sharing can't be enabled |
  | `pcos-home` | Same defaults; only services the user enabled are opened | `mdns`, `kdeconnect`, `rdp`, `samba`, `steam-streaming`, `ssh` via `pcos-network share` |
- Outbound: allowed (no domain restrictions; this was explicitly decided).
- Changing zones or rules needs admin approval.

### 5.2 Network trust prompt
- When a new connection appears, `pcos-network-prompt` (desktop session) asks **"Home (trusted) or Public?"**. Home is recorded by connection UUID in root-owned `/etc/pcos/trusted-networks`, and the root NetworkManager dispatcher hook enforces the zone. NetworkManager's per-connection `connection.zone` isn't trusted, because users can edit it without admin approval.
- Marking a network as **Home** needs admin approval.
- Unanswered means **Public**.

### 5.3 Nothing listening by default
- Off: `sshd`, Samba, GNOME remote desktop, media sharing, Avahi/mDNS announcements, LLMNR, NetBIOS, UPnP
- `cups-browsed` removed. Printers are added manually, or discovered only on Home networks.

### 5.4 Sharing (opt-in, Home networks only)
- **File sharing:** selected folders only, password required, automatically off when the PC leaves the Home network
- **Remote desktop:** its own password, with an on-screen indicator while someone is connected
- **Phone pairing:** approved per device (§9.3)
- **Bluetooth:** not discoverable, every pairing approved on screen
- **Control Center → Sharing:** shows what's shared, on which network and who's connected, with a single **Stop all sharing** button

### 5.5 Physical ports
- Thunderbolt/USB4: `bolt` device authorization + IOMMU (DMA protection)
- USB: see §6

---

## 6. USB device authorization

### 6.1 Engine
- **USBGuard**, configured with:
  - `ImplicitPolicyTarget=block`
  - `PresentDevicePolicy=apply-policy`
  - `InsertedDevicePolicy=apply-policy`
  - `PresentControllerPolicy=keep`
- **Initial rules:** generated at first boot from the devices already present (internal keyboard, trackpad, webcam, Bluetooth chip). Registered FIDO2 keys are always allowed.
- **Rule matching:** vendor/product ID **+ serial + interface layout (`with-interface`)** + parent hub where it makes sense. This makes copying a trusted device's identity harder.

### 6.2 Prompt app: `pcos-usb-prompt`
- A user-session service that listens to the USBGuard D-Bus signals (`DevicePresenceChanged`). When a device is blocked, it shows:

  > 🔌 **New USB device connected**: SanDisk Ultra (Storage)
  > **[Block]  [Allow once]  [Always allow]**

- Allow → polkit approval (Standard or Strong mode) → `applyDevicePolicy(id, allow, permanent)`.
- **Device class shown in plain words:** Storage, Keyboard, Mouse, Network adapter, Audio, Phone, Hub, etc.
- **BadUSB heuristics** (red warning, default action Block):
  - storage + HID (keyboard) in one device
  - an unexpected network adapter
  - a keyboard appearing while another keyboard is active
- **Locked screen:** all new devices are blocked silently. They can be reviewed after unlocking.

### 6.3 After approval
- No autorun: GNOME `autorun-never=true`, no "open folder" on insert
- Removable media mounted with `nosuid,nodev,noexec` (udisks2 `mount_options.conf`)
- No thumbnails for removable media
- Optional ClamAV scan on mount

### 6.4 Modes (Control Center → Security → USB devices)
- **Ask** (default) / **Allow keyboards and mice, ask for everything else** / **Off**
- A list of always-allowed devices (with remove) and recently blocked devices

---

## 7. Privacy and anti-tracking

### 7.1 No phone-home
| Item | Setting |
|---|---|
| `rpm-ostree-countme` / DNF countme | Disabled |
| ABRT crash reporting | Off (or local only) |
| NetworkManager connectivity check | `[connectivity] enabled=false` (Balanced: optionally pointed at a self-hosted endpoint) |
| GNOME location services | Off |
| Time sync | chrony with **NTS** servers |

### 7.2 Network identity
- NetworkManager defaults:
  - `wifi.scan-rand-mac-address=yes`
  - `wifi.cloned-mac-address=stable` (a different MAC address per network)
  - `ethernet.cloned-mac-address=stable` (Maximum preset)
  - `ipv4.dhcp-send-hostname=false`
  - `ipv6.dhcp-send-hostname=false`
  - `ipv6.ip6-privacy=2`
- Generic hostname by default, Bluetooth not discoverable, no automatic joining of open Wi-Fi networks

### 7.3 DNS
- `systemd-resolved` with **DNS-over-TLS** (Quad9 by default; Mullvad or custom selectable), `LLMNR=no`, `MulticastDNS=no` (except on Home when enabled)
- **Optional system-wide tracker/ad blocking:** a blocklist served through a local resolver layer (e.g. a selectable list such as OISD or Hagezi), toggled in Control Center

### 7.4 Browser
- Firefox policies (§4.5): strict tracking protection, telemetry/studies/Pocket/sponsored content off, HTTPS-only, uBlock Origin installed
- Optional: clear cookies and history on exit
- Optional browsers: **Mullvad Browser**, **Tor Browser** (Flatpak)

### 7.5 Apps and data
- Flatpak permissions are edited in Control Center: camera, microphone, location, files, **network** (per app)
- Camera/microphone indicators through xdg-desktop-portal prompts
- **Metadata Cleaner** (mat2) preinstalled
- Options to limit or turn off the recent-files list and the search index
- `journald`: `MaxRetentionSec=2week` (Balanced), `3day` (Maximum)

### 7.6 VPN / Tor
- WireGuard through NetworkManager, with a **kill switch** (firewall drops non-VPN traffic while the VPN is active)
- Tor option through Tor Browser

### 7.7 Presets (Control Center → Privacy)
| Preset | Contents |
|---|---|
| **Balanced** (default) | §7.1, §7.2 (Wi-Fi), DoT, Firefox strict + uBlock |
| **Maximum** | Balanced + tracker blocklist + randomized wired MAC + clear-on-exit + VPN kill switch + minimal history + scheduled privacy clean (PC Cleaner) |
| **Custom** | Individual toggles |

### 7.8 Limits (documented to the user)
No OS can stop tracking through accounts you're signed into, browser fingerprinting (Firefox strict reduces it; Mullvad/Tor Browser greatly reduce it), or your ISP seeing IP addresses without a VPN.

---

## 8. RudramOS Control Center and helper service

The custom features above need one place in the UI and one privileged backend.

### 8.1 `pcos-control` (Control Center app)
- **Toolkit:** GTK4 + libadwaita (native GNOME look). Language: Python (PyGObject) for speed of development.
- **Pages:**
  - **Security:** admin protection mode, keys, disk unlock, recovery key status, approved apps (fapolicyd), activity log
  - **Browser extensions:** approved list, add/remove
  - **USB devices**
  - **Network:** network trust, firewall status, sharing
  - **Privacy:** presets and toggles, app permissions
  - **Phone:** pairing, per-phone permissions, "Show phone screen"
  - **Updates:** current version, update now, rollback, image variant

### 8.2 `pcosd` (privileged helper)
- A root systemd service on the D-Bus **system bus** with a small, fixed API, for example `SetAdminMode`, `RegisterFidoKey`, `ApproveExtension`, `TrustExecutable`, `SetNetworkTrust`, `ApplyPrivacyPreset`
- Each method is backed by its own **polkit action** (`org.pcos.*`), so the approval prompt follows the admin mode
- Strict input validation; no generic "run command" method
- Writes only to `/etc` and `/var` files it owns, and logs every change to audit

---

## 9. Built-in apps

### 9.1 Temp Monitor (port of the user's app: `C:\Venky\work\temp_monitor`)
**Current state:** .NET 8 WPF + LibreHardwareMonitorLib (Windows-only). The clean split is `SensorService.Read() → List<Reading>`, and the UI is `MainWindow` / `MetricCard` / `TrayIcon`.

**Target architecture**
```
┌────────────────────────┐  D-Bus  ┌──────────────────────────────┐
│ Temp Monitor UI        │◄──────►│ Monitor service (user)       │
│ Avalonia (C#)          │        │ 1 s sensor polling, history  │
│ cards · charts · fans  │        │ SQLite, notifications        │
└────────────────────────┘        └──────────────┬───────────────┘
                                                 │ D-Bus + polkit
                                  ┌──────────────▼───────────────┐
                                  │ Fan daemon (root, minimal)   │
                                  │ hwmon PWM · NVML · amdgpu ·  │
                                  │ liquidctl · safety failsafe  │
                                  └──────────────────────────────┘
```
- **One codebase, two platforms:** an `ISensorProvider` interface → `WindowsSensorProvider` (the existing LibreHardwareMonitor code) and `LinuxSensorProvider`
- **UI:** WPF → **Avalonia** (XAML is close to WPF; `MetricCard` / `MainWindow` translate almost directly)
- **Linux sensors** (no root needed):

  | | Temperature | Usage |
  |---|---|---|
  | CPU | hwmon `coretemp` / `k10temp` (Tctl/Tdie) | `/proc/stat` |
  | GPU AMD | `amdgpu` hwmon edge + junction | `gpu_busy_percent`, `mem_info_vram_*` |
  | GPU NVIDIA | NVML | NVML utilization + VRAM |
  | RAM | `jc42` / `spd5118` (if present) | `/proc/meminfo` |
  | NVMe | `nvme` hwmon | `/proc/diskstats` active time + filesystem usage |
  | SATA/USB disks | `drivetemp` (loaded by default in the image) | `/proc/diskstats` |
  | Fans | hwmon `fan*_input`, NVML fan speed | — |

- **Kept from the original:** N/A shown with a reason (never an estimate), the source label under each temperature, the "All sensors" view, °F toggle, diagnostics, single instance
- **Linux integration:** top-bar indicator (AppIndicator) showing CPU temperature colour-coded; XDG autostart replaces Task Scheduler

**Fan control**
- Per fan: rename, **Identify** (briefly spins that fan up), modes **Auto (BIOS) / Fixed % / Curve** (choice of temperature source, or max of several; curve points; hysteresis)
- Profiles: Silent / Balanced / Performance / custom, switchable from the app or the indicator
- **Backends:** hwmon `pwmN` + `pwmN_enable` (Super I/O: `nct6775`, `it87`; laptops: `thinkpad_acpi`, `dell-smm-hwmon`; Apple: `applesmc`), NVML `nvmlDeviceSetFanSpeed_v2` (NVIDIA), `amdgpu` fan curve (`gpu_od/fan_ctrl`), **liquidctl** (AIOs/USB controllers)
- Fans the firmware controls are shown as **"Read-only: controlled by firmware"**
- **Safety:**
  - minimum floor
  - **critical temperature sets all fans to 100%**
  - a daemon or app crash restores `pwm_enable` to BIOS auto
  - a fan stall (0 RPM while commanded to spin) raises an alert
  - lowering the floor or turning off the override needs admin approval
- **Windows:** LibreHardwareMonitorLib also supports fan control, so the same feature works there

**Overheat notifications**
- Thresholds per component; defaults come from hwmon `*_max`/`*_crit`, with 70/85 °C as the fallback
- Warning: above "hot" for 30 s (configurable). Critical: an urgent notification + optional "fans to 100%"
- Cooldown, a "back to normal" message, and an **event log**
- Run by the background monitor service, so they work with the window closed

**Usage history**
- Per component: temperature, usage, secondary value (VRAM / memory / disk space / RPM)
- SQLite stored locally. 1 s live data → 1 min averages → 10 min averages; retention 7/30/90 days
- Ranges 5 m / 1 h / 24 h / 7 d / 30 d; min/avg/max; time above "hot"; overlay comparison (e.g. CPU temperature vs. fan RPM); CSV export; **Clear history**

### 9.2 PC Cleaner (port of the user's app: `C:\Venky\work\pc_cleaner`)
**Current state:** Python + tkinter/ttkbootstrap, about 3.4k lines, with tests. The `core.py` model (`Target` / `Files` / `RegKeys` / `Custom`) is portable. The Windows-specific parts are `winutil`, `regutil`, `scheduler`, the Explorer/Windows cleaners and `winapp2`.

**Port**
- **Platform layer:** `winutil` → `platform/linux.py`

  | Windows | Linux |
  |---|---|
  | `running_processes` | `/proc` |
  | polite close → forced close | `SIGTERM` → `SIGKILL` (still asks first) |
  | Recycle Bin | `gio trash` |
  | `show_in_explorer` / `startfile` | FileManager1 D-Bus / `xdg-open` |
  | Task Scheduler | **systemd user timer** (`Persistent=true`, so missed runs happen at next start) |
  | Run as administrator | **per-action approval** through the `pcosd` / pkexec helper, not an elevated GUI |
  | Start-menu shortcut | `.desktop` file |

- **Paths:** XDG (`~/.config/pccleaner`, `~/.local/state/pccleaner/logs`)
- **Linux catalog** (same safe-by-default ticking):
  - **System:** `~/.cache` (per app), thumbnails, Trash, Mesa/NVIDIA shader caches; with admin approval: journal vacuum, coredumps, unused Flatpak runtimes, old container images, **old OS deployments (always keep one rollback)**
  - **Desktop history:** `recently-used.xbel`, file-manager history, search index reset, shell history (off by default)
  - **Browsers:** Firefox, Chrome, Chromium, Brave, Vivaldi, Edge, both native and **Flatpak** (`~/.var/app/<id>`), all profiles. The Firefox SQL cleanup that keeps bookmarks is reused.
  - **Media:** VLC, mpv, Celluloid
  - **Apps:** VS Code / VSCodium, LibreOffice recents, **generic Flatpak app caches**
  - **Developer tools:** npm, Yarn, pip, NuGet, Cargo, Go
- **winapp2 equivalent:** BleachBit **CleanerML** rules (download on request, installed apps only, unticked, warnings shown)
- **Safety rules kept:** 1-hour minimum age for temp files, links removed but never followed, protected folders (adding `/usr /etc /boot /proc /sys`, and `~/.var` for Large Files) refused, in-use files skipped, deletes go to Trash
- **Privacy integration:** the Maximum preset can turn on a scheduled privacy clean
- **UI:** keep tkinter/ttkbootstrap for v1 (runs under XWayland). A native GTK4 UI is an option later.

### 9.3 Android phone integration (Continuity-like)
- **GSConnect** (GNOME implementation of KDE Connect) preinstalled; **Valent** as an alternative. On the phone, the **KDE Connect** app (Play Store / F-Droid).
- **Features:**
  - notifications with quick reply
  - SMS read/send
  - incoming call alert + mute ringer
  - file send/receive and browsing phone storage
  - shared clipboard
  - battery level
  - find my phone
  - remote input/media control
  - pause media when a call comes in
- **Screen control:** **scrcpy** (USB or wireless ADB, with audio forwarding), started from a **"Show phone screen"** button
- **Security:**
  - pairing approved on both devices
  - TLS encryption, LAN only, no cloud
  - ports open only in `pcos-home`
  - permissions per phone
  - plugging in a phone with USB debugging goes through the USBGuard prompt
- **Limits:** answering calls with PC audio relies on Bluetooth HFP (PipeWire) and is **experimental**; RCS chats are only reachable as notifications; no iPhone support.

---

## 10. First-boot setup flow
1. Language, keyboard, time zone
2. Create the admin user (password)
3. **Admin protection:** Standard or Strong → (Strong) register key 1, key 2, test touch
4. **Disk unlock:** TPM / TPM + PIN / FIDO2 → **recovery key** shown once, to print or write down, and confirmed
5. **Privacy preset:** Balanced / Maximum / Custom
6. **This network:** Home or Public
7. **Enroll the NVIDIA signing key (MOK)**, only on NVIDIA images
8. **Connect your phone** (optional, can be skipped)
9. Recommendations: set a BIOS password, disable USB boot (with links to guidance)

Implementation: GNOME Initial Setup with added RudramOS pages, or a dedicated `pcos-firstboot` app that runs after GNOME Initial Setup. To be decided in phase 12.

---

## 11. Hardware support and test matrix
| Machine | GPU | Image | Notes |
|---|---|---|---|
| Dev PC (likely Intel MacBook Pro 16" 2019, **T2**) | AMD Radeon Pro 5500M | `pcos` | Needs a **t2linux** kernel for keyboard, trackpad, audio and Wi-Fi; Apple Secure Boot settings must allow external boot; fan control through `applesmc` |
| Desktop 1 | NVIDIA **RTX 3060** | `pcos-nvidia` | Main NVIDIA test machine |
| Desktop 2 | NVIDIA **GTX 1050 Ti** | `pcos-nvidia-legacy` | 580xx driver; plan support until about 2028 |
| VMs | virtual | `pcos` | Hyper-V Gen 2 (Secure Boot + vTPM) on Windows 10 Pro; QEMU/KVM + swtpm on Linux |

**T2 Mac support** would need a separate `pcos-t2` variant (t2linux kernel and firmware). It's optional and planned as a later phase.

---

## 12. Recovery and lockout
| Situation | Recovery |
|---|---|
| Bad update | Boot the previous deployment / `bootc rollback` |
| TPM won't unseal (firmware update, Secure Boot change) | Enter the **recovery key** at boot, then re-seal through Control Center |
| Main FIDO2 key lost | Use the backup key to remove the lost key and register a new one |
| All FIDO2 keys lost | Recovery boot + recovery key → reset to Standard mode |
| Recovery key lost **and** TPM unusable | **Data is unrecoverable by design.** Backups are essential. |
| Fan misconfiguration | Daemon failsafe → BIOS auto; Control Center "Reset fans" |

Backups: recommend an encrypted backup tool (e.g. Pika Backup / Déjà Dup, Flatpak) to an external drive. Possibly a built-in backup page later.

---

## 13. Repository layout
The image files sit at the repo root, following the Universal Blue image-template, so the template's Justfile and CI work unchanged.
```
PC_OS/
├── README.md
├── docs/
│   ├── DESIGN.md            ← this document
│   └── ROADMAP.md
├── Containerfile            ← base + layers (ARG for GPU variant in phase 2)
├── Justfile                 ← build recipes from the template (used by CI)
├── image-template.env       ← image name, registry owner, description
├── disk_config/             ← ISO / disk image configs (bootc-image-builder)
├── build_files/build.sh     ← script run during image build
├── system_files/            ← files copied into /usr and /etc
│   ├── etc/firefox/policies/policies.json
│   ├── etc/pam.d/pcos-admin(.standard|.strong)
│   ├── etc/usbguard/…
│   ├── etc/firewalld/zones/pcos-{public,home}.xml
│   ├── etc/NetworkManager/conf.d/…
│   ├── etc/systemd/resolved.conf.d/…
│   └── usr/share/polkit-1/{actions,rules.d}/…
├── apps/
│   ├── pcos-control/        ← Control Center (GTK4/Python)
│   ├── pcosd/               ← privileged helper (D-Bus)
│   ├── pcos-usb-prompt/
│   ├── temp-monitor/        ← port; or a submodule of the user's repo
│   └── pc-cleaner/          ← port; or a submodule
├── keys/                    ← public keys only (cosign.pub, MOK cert); private keys in CI secrets
└── .github/workflows/       ← build, sign, ISO
```
The two existing apps can stay in their own repositories and be pulled in at image build time. Decide in phase 9/10.

---

## 14. Key management
| Key | Use | Storage |
|---|---|---|
| cosign key | Signs OS images | Private key in a GitHub Actions secret + an offline backup |
| MOK / module signing key | Signs NVIDIA kmods (and the UKI later) | CI secret + offline backup |
| (Later) own Secure Boot db key | Full custom Secure Boot | Offline |

**Losing or leaking these keys compromises every RudramOS install.** They're protected with 2FA (preferably a FIDO2 key) on GitHub, and kept in an offline backup.

---

## 15. Threat model (summary)
| Threat | Mitigation |
|---|---|
| Stolen laptop (powered off) | LUKS2 + TPM (+ PIN) |
| Drive removed and read elsewhere | TPM-sealed key |
| Evil-maid boot tampering | Secure Boot + PCR-bound unseal (+ UKI) |
| Malware installing persistently | Read-only `/usr`, fapolicyd, admin approval, signed updates |
| Malware or a shoulder-surfer with the password | Strong mode (FIDO2 touch) |
| Malicious browser extension | Policy-blocked installs |
| Network attackers / LAN devices | Default-deny inbound, stealth, no listening services, DoT, HTTPS-only |
| BadUSB / malicious USB stick | USBGuard + prompt + heuristics + noexec/no autorun |
| Trackers / telemetry | Privacy presets (§7) |
| Compromised update server | cosign signature verification |
| **Out of scope** | Nation-state hardware implants, firmware-level attacks beyond Secure Boot, the user approving malware themselves |

---

## 16. Open decisions
1. **Name and branding** of the OS
2. **Base image:** Bluefin vs. `base-main` (+ how much secureblue hardening)
3. **Firefox:** RPM in the image (current plan, simplest policy handling) vs. Flatpak
4. **First-boot:** extend GNOME Initial Setup vs. a separate `pcos-firstboot` app
5. **Temp Monitor UI:** Avalonia (current plan, reuses C#) vs. native GTK4
6. **PC Cleaner UI:** keep tkinter for v1 (current plan) vs. GTK4
7. **App repos:** monorepo vs. the existing separate repos as submodules
8. **T2 Mac variant:** in v1 or later
9. **Default DNS-over-TLS provider:** Quad9 (current plan) vs. Mullvad vs. ask at setup
