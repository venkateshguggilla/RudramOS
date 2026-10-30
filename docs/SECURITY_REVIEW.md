# RudramOS security review (Phase 13, October 2026)

A review of everything RudramOS adds that runs as root or decides what may run as root. The
base system (Fedora / Bluefin, GNOME, systemd, polkit, USBGuard, fapolicyd, bootc) was not
reviewed; its updates come from upstream.

## Scope

| Area | What was reviewed |
|---|---|
| Admin approval (polkit) | The 11 `org.pcos.*` actions, Temp Monitor's 2 actions, PC Cleaner's action, `/etc/polkit-1/rules.d/00-pcos-flatpak.rules` |
| Tools run through pkexec | `pcos-admin-mode`, `pcos-disk-security`, `pcos-app-guard`, `pcos-browser-extensions`, `pcos-network`, `pcos-privacy`, `pcos-killswitch`, `pcos-usb`, `pcos-update`, `pcos-gpu-switch`, `pcos-grub-theme`, `pccleaner-system` |
| Root services | `pcos-usb-watch`, `pcos-usb-firstboot`, `pcos-image-rename`, `pcos-grub-theme.service`, the NetworkManager hook `50-pcos-network-trust`, fapolicyd rule generation (`pcos-app-guard regenerate-rules`), the Temp Monitor fan service |
| Input shown to people | USB device descriptions and prompts (device-supplied names and IDs), approval prompt texts |
| Files | Modes of everything in `system_files/`, files the tools write, build-time `install`/`chmod` |

## Method

Read every root entry point and followed each piece of caller- or device-controlled input
(command-line arguments, files in home folders, NetworkManager settings a user can edit, USB
descriptors, socket requests) to where it is used: rule files, config files, other commands,
prompts and logs. Each finding below was fixed with a test that fails without the fix.

## Findings

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | **High** | **App approval rules built from a user's own file.** At every boot `pcos-app-guard regenerate-rules` (root) wrote each user's Downloads and Desktop folders, read from their `~/.config/user-dirs.dirs`, into fapolicyd's rules. Any user could point "Downloads" at `/usr` (no program would run for any user: every login breaks) or put spaces / rule syntax in it (fapolicyd rejects the rules and doesn't start: app approval silently off). | Only folders inside the user's own home without spaces, control characters, rule syntax or `..` are used; anything else falls back to the default folder name. Approving a file whose name has a line break is refused (it would split its line in the trust file). Tests: `tests/test-app-guard.sh`. |
| 2 | **Medium** | **Fake security keys.** A USB device counted as a "security key" by its vendor ID alone. Vendor IDs are easy to fake (BadUSB tools set any ID), so a "Yubico" keyboard + storage stick got no warning, and its only allow button allowed it permanently. | A security key must also have only HID and smart-card interfaces. A security-key maker's ID on anything else is shown as a red warning: "It claims to be a security key, but a real one can't also be …". Tests: `tests/test-usb-describe.sh`. |
| 3 | **Medium** | **Fan service could be made to hold unlimited data.** Any local user may connect to the root fan service. A request line had no length limit and every connection got a thread, so one client could exhaust its memory or threads (fans then go back to firmware control: safe, but fan control stops). | At most 64 KB per request, 32 connections at once, 60 s idle timeout; curves at most 32 points, at most 16 temperature sources. temp-monitor `189c5bd`, tests in `FanControlTests`. |
| 4 | Low | **Approval prompt text before validation.** The fan service put a new fan name into the polkit prompt before checking it, so a long or multi-line name could pad or spoof the prompt (and client text could add fake lines to the service log). | Values are checked before anyone is asked (names at most 40 characters, no control characters); client text in the log is shortened with line breaks removed. temp-monitor `189c5bd`. |
| 5 | Low | **Network name read as an nmcli option.** `pcos-network trust <name>` passed the name straight to `nmcli connection show`, so a name starting with `-` acted as an option (e.g. `--active` picked some active network). | Names are looked up with `nmcli … show id <name>`, UUIDs with `show uuid <uuid>`. Tests: `tests/test-network.sh`. |
| 6 | Low | **Kill switch built rules from user-editable VPN settings.** A WireGuard connection's interface name and endpoint port (editable without admin approval) went into nftables rules loaded as root. nftables' syntax check rejected broken rules, so the switch failed closed, but the values weren't checked. | Interface names must be plain (`[A-Za-z0-9_.-]`, at most 15) and ports 1–65535; anything else is left out. Tests: `tests/test-killswitch.sh`. |
| 7 | Low | **Hand-typed extension approvals unchecked.** `pcos-browser-extensions approve <id> <url>` accepted any ID and any install address, including plain `http://`. | IDs must be `{uuid}` or `name@domain`; install links must be `https://`. Tests: `tests/test-browser-extensions.sh`. |

## Accepted risks (by design, documented)

- **Test overrides in root tools** (`PCOS_TEST_ROOT`, `MODE_FILE`, `RULES_DIR`, `PAM_DIR`, …): read
  from the environment, but pkexec and sudo reset the environment, and services run with a fixed one.
  Only someone who is already root can set them.
- **`/etc/u2f_mappings` is world-readable (0644).** It holds security-key credential IDs and public
  keys, not secrets; Control Center reads it without a password to show how many keys are registered.
- **Universal Blue's public MOK password (`universalblue`).** Enrolling the NVIDIA driver signing key
  needs someone at the PC's blue MOK screen during boot; the password only confirms that step.
- **Fan control needs no password for the logged-in user** (`allow_active=yes`): changing a fan's
  speed can't overheat the PC because the critical-temperature override always runs every fan at full
  speed, and lowering a safety limit needs an admin.
- **GSConnect's powerful phone permissions are on by default** for a newly paired phone ("Control this
  PC": remote mouse and keyboard; "Run commands"). Pairing itself must be accepted on both devices and
  only works on Home networks. Recommendation for a later change: default these two off.
- **Approval remembered for a few minutes** (`auth_admin_keep`) only on privacy settings, updates,
  the boot menu theme, PC Cleaner's maintenance and app installs. Everything that changes who can get
  in (disk unlock, admin mode, security keys, USB, app approval, networks, the kill switch, drivers)
  asks every time.
- **`/run/pcos/usb-pending` is world-readable**: descriptions of USB devices waiting for approval
  (name, IDs, serial), so the desktop prompt can show them without root.

## Already good

- Every polkit action has `allow_any` and `allow_inactive` set to `no` (Temp Monitor: `auth_admin`):
  nothing works without a local, active session.
- Root tools take fixed words or strictly checked values (device and rule numbers are digits, image
  and mode names come from fixed lists), refuse anything else, and build JSON with `jq` (no injection).
- Secrets (disk passphrase, PINs, the password for the key test) go to tools on stdin, never on a
  command line where other programs can read them; recovery keys are masked in progress output.
- The fan service identifies callers through the kernel (`SO_PEERCRED`) and asks polkit with the
  process start time, so a reused process ID can't borrow an approval; its systemd unit allows no
  network, no home folders and nothing writable except `/sys`, its runtime and config folders.
- USBGuard's IPC is root-only (approvals always go through the admin prompt); its rules are 0600.
- No setuid or world-writable files in `system_files/`; generated config files are written to a
  temporary file and moved into place.

## Not covered yet (rest of Phase 13)

- A network scan of a running PC (Public network: nothing reachable; Home: only the sharing turned on).
- Lockout drills on real hardware: lost key, all keys lost, TPM change, bad update.
