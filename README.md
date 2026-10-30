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
- [User guide](docs/USER_GUIDE.md): everyday use and what to do when something goes wrong, in plain words

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
| `.github/workflows/build.yml` | Builds, signs and publishes `ghcr.io/venkateshguggilla/rudramos` |
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
| `rudramos` | AMD and Intel graphics |
| `rudramos-nvidia` | NVIDIA RTX 20/30/40/50 and GTX 16 series (e.g. RTX 3060) |
| `rudramos-nvidia-legacy` | NVIDIA GTX 10 series and older Pascal/Maxwell (e.g. GTX 1050 Ti), 580 LTS driver |

**Use the standard `rudramos` ISO on every PC.** After the first login, the **Driver Assistant** detects the graphics card and, if it's NVIDIA, offers to install the right driver (admin approval, download, restart). On Secure Boot PCs a blue **MOK Manager** screen appears once after that restart: choose **Enroll MOK → Continue → Yes**, enter `universalblue`, then **Reboot**. Check with `nvidia-smi`.

Check what was detected, from a terminal:
```bash
pcos-driver-assistant --check
```

Switch variants by hand (signature-checked), if ever needed:
```bash
sudo bootc switch --enforce-container-sigpolicy ghcr.io/venkateshguggilla/rudramos-nvidia:latest
```

**Renamed from `pcos` (October 2026).** The images used to be `pcos`, `pcos-nvidia` and `pcos-nvidia-legacy`. They are still published, signed, under those names during the switch-over. Installed PCs move to the new names by themselves (`pcos-image-rename.timer`), but only once the new name can be downloaded. Nothing is downloaded at that moment; only where updates come from changes. The command names (`pcos-usb`, `pcos-control`, ...) are unchanged for now.

One-time step after the first build with the new names: on GitHub, open each new package (`rudramos`, `rudramos-nvidia`, `rudramos-nvidia-legacy`) → Package settings → **Change visibility → Public**. New packages start private, and until they're public, installed PCs stay on the old names.

## First start: Welcome to RudramOS
After installing, **Welcome to RudramOS** opens at your first login (after GNOME's own language and accounts setup). One step per page:
1. **Admin approval:** Standard (password) or Strong (password + security key); register keys.
2. **Disk encryption:** create the **recovery key** and write it down, then choose how the drive unlocks (TPM, TPM + PIN, security key).
3. **Privacy:** Balanced or Maximum.
4. **This network:** Home or Public (only if you're connected).
5. **Graphics driver:** only if your card needs a different driver, with what to do on the blue MOK screen.
6. **Your phone** (optional): Phone link and pairing.
7. **Protect this PC:** BIOS password, start only from this drive, with a button to restart into the BIOS.

Close it to finish later: it opens again at the next login until you press **Finish** or **Skip setup**. Run it again any time: **Welcome to RudramOS** in the app grid, Control Center → System, or `pcos-setup` (`pcos-setup --reset` shows it at the next login). It opens only for admins: other users can't change these settings.

## RudramOS Control Center
Open **RudramOS Control Center** from the app grid (or run `pcos-control`). Everyday tasks are buttons; changes ask for your admin password in the usual system prompt. No terminal needed.

| Page | What you can do |
|---|---|
| **Updates** | See whether RudramOS is up to date (checked without a password), **Update now**, **Restart** to finish, **Roll back** to the previous version, see when the next automatic update runs |
| Security | Admin protection (Standard / Strong), register and test security keys |
| Apps | Approve a downloaded program, turn app approval on or off, approve or remove browser extensions |
| **Phone** | Phone link on or off, pair a phone, choose what each paired phone may do, **Show screen**, pair over Wi-Fi |
| Network | Mark a network Home or Public, turn sharing on or off |
| USB | Approve waiting devices, choose the USB protection mode |
| Privacy | Presets, DNS, tracker blocking, VPN kill switch |
| Disk | Recovery key, unlock with TPM / TPM + PIN / security key |
| Graphics | Install the right graphics driver |
| System | Boot menu theme on or off, **Restart into BIOS / UEFI settings**, run the first-time setup again |

Nothing opens a terminal. Steps that need a secret, like your disk passphrase, a PIN or a touch of your security key, happen in a small window: you type it there (it goes straight to the tool, never onto a command line), the window says when to touch the key, and a new disk recovery key is shown once with a **Copy** button. The pages are in a sidebar, like GNOME Settings. `pcos-control --page disk` opens a page directly.

## Admin approval: Standard or Strong
Every admin action (installing apps, system settings, `sudo`) asks for approval.
- **Standard** (default): your password, like a Mac.
- **Strong**: your password **and** a touch of a registered FIDO2 security key (e.g. YubiKey).

Each approval prompt says **who is asking and what will change**, for example:
- "The App Store (or a terminal) wants to install an app for everyone on this PC: app/org.mozilla.firefox/x86_64/stable from flathub"
- "RudramOS Control Center wants to update RudramOS or go back to the previous version (/usr/libexec/pcos/pcos-update upgrade)"
- "Temp Monitor wants to change fan settings: switch the fan profile to Silent"

If a prompt appears that you didn't expect, click **Cancel**.

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
- **App Store:** open **App Store** from the app grid (or Control Center → Apps → Open). It's Bluefin's store, **Bazaar**, with apps from Flathub. Bazaar is downloaded on the first start with internet; if that hasn't happened yet, App Store downloads it when you first open it (a few hundred MB, once).
- **Installing apps** (App Store or `flatpak install`) asks for admin approval. Updates stay automatic.
- **Downloaded programs** (in Downloads, on the Desktop or on a USB drive) don't run until approved, like Gatekeeper on a Mac. When one is blocked, a notification offers **Approve…**. You can also approve from Control Center → **Apps**, or:
  ```bash
  sudo pcos-app-guard approve ~/Downloads/SomeApp.AppImage
  ```
- **Firefox extensions** install only if approved. uBlock Origin is always installed. Approve one by pasting its addons.mozilla.org link in Control Center → **Apps**, or:
  ```bash
  sudo pcos-browser-extensions approve https://addons.mozilla.org/firefox/addon/bitwarden-password-manager/
  ```

## Networks and sharing
- Every network is **Public** until you mark it **Home**: nothing on the network can connect to this PC, and it doesn't answer pings (stealth).
- When you join a new network, a notification asks **Home or Public?** Choosing Home needs admin approval.
- Sharing (printer discovery, phone link, remote desktop, file sharing, Steam Remote Play, SSH) can only be turned on for **Home** networks, so it's closed automatically everywhere else. Use Control Center → **Network**, or:
  ```bash
  pcos-network status
  ```
  ```bash
  sudo pcos-network share phone on
  ```

## USB devices
- A newly connected USB device is **blocked until you allow it**. A notification describes it in plain words: **Keep blocked / Allow once / Always allow**. Devices connected when RudramOS first started are trusted.
- **Suspicious devices** (a "USB stick" that can also type like a keyboard, or one that's also a network adapter) get a red warning. These are common USB attacks.
- Nothing is asked, and nothing new works, while the screen is locked.
- Security keys (YubiKey, Nitrokey, ...) are always allowed permanently once approved.
- Modes in Control Center → **USB**: *Ask* (default), *Allow keyboards and mice*, *Off*. Or `sudo pcos-usb mode allow-input`.
- **You can't be locked out by your own keyboard:** while no USB keyboard is allowed (at the login screen, say), a plain keyboard or mouse works without asking. A fake "keyboard" stick plugged in next to your keyboard is still blocked. Allowed devices are recognised by what they are, not by which USB port they're in, so moving them to another port is fine.
- **Still no working keyboard:** at the boot menu (hold Shift or press Esc while the PC starts) press **e**, add `systemd.mask=usbguard.service` to the line starting with `linux`, then press **Ctrl+X**. This boots once with USB protection off, so you can approve the new keyboard.

## Privacy
No telemetry, usage reports or "count me" pings in any setting. Time is synced over encrypted, authenticated NTS. Choose a preset in Control Center → **Privacy**, or:
```bash
sudo pcos-privacy preset maximum
```
| | Balanced (default) | Maximum |
|---|---|---|
| Wi-Fi MAC address | different per network | different per network |
| Wired MAC address | real | different per network |
| DNS | encrypted (Quad9), falls back if blocked | encrypted only, plus ad/tracker blocking (Mullvad) |
| Wi-Fi login page detection | on | off |
| Firefox | strict tracking protection, uBlock Origin | + forgets cookies and history on close |
| System logs kept | 14 days | 3 days |

**A hotel or café login page won't load?** Temporarily set DNS to *This network's DNS* in Control Center → Privacy (or `sudo pcos-privacy set dns network`), sign in, then switch back.

**VPN kill switch:** add your WireGuard VPN in Settings → Network → VPN, then turn on *VPN kill switch* in Control Center → Privacy (or `sudo pcos-killswitch on`). Internet then only works through the VPN. The local network (router, printers) still works.

## Look and feel
RudramOS is themed around Shiva's eyes and the trishul:
- **Boot animation:** the artwork, animated, while the PC starts. The disk password prompt appears under it. Press **Esc** during boot to see the start-up messages instead.
- **Boot menu:** normally hidden. It appears after a failed start, or when **Shift** (or **Esc**) is held while the PC starts, with the same art and a red highlight. To use GRUB's plain menu instead:
  ```bash
  sudo touch /etc/pcos/no-grub-theme
  ```
  ```bash
  sudo systemctl start pcos-grub-theme
  ```
- **Desktop:** the "RudramOS Trishul" wallpaper (also on the lock screen), GNOME's **red** accent and dark style. A second wallpaper, "RudramOS Emblem", is in Settings → Appearance. These are defaults, so change them freely.
- **Logo:** the trishul emblem on the login screen, in Settings → About and on the top-bar menu button.
- **The name RudramOS everywhere people see it:** Settings → About ("RudramOS 2026.10.27 (based on Fedora 44)"), the boot menu, the installer, the computer's default name (`rudramos`), terminal windows (a one-line greeting; `fastfetch` shows the trishul), the app grid (**RudramOS Guide**, **System Update** opens Control Center → Updates) and the top-left menu's Documentation item. Bluefin's community links and monthly wallpapers are gone, and the leftover Fedora logo images show the trishul. Hide the terminal greeting with `touch ~/.config/pcos/no-terminal-greeting`.
- **Still "Fedora" in two places**, on purpose: the PC's firmware boot list (F12 menu) entry, which the bootloader updater owns and renaming it could stop the PC from starting, and the release files programs check (`/etc/fedora-release`). RudramOS is built on Fedora (through Bluefin), and the version says so.

The images are generated by `tools/make-branding.py` (logo, wallpapers, boot menu) and `tools/make-plymouth-frames.py` (boot animation frames from a GIF).

## Running apps (task manager)
**Mission Center**, pinned in the dock, shows every running app and process with its CPU and memory use, like Task Manager on Windows. Select one and click **End task** to close a stuck app. Its other tabs show live CPU, GPU, memory, disk and network use. It's downloaded from Flathub on the first start with internet, like the App Store.

## Android phone
Everything is on Control Center → **Phone**.

**Phone link** (GSConnect, the KDE Connect protocol) brings your phone's notifications (with reply), text messages, call alerts, files and links, a shared clipboard, battery level and "find my phone" to the PC. To set it up:
1. On the phone, install **KDE Connect** (Play Store or F-Droid).
2. Connect both to the same Wi-Fi and mark that network **Home** (Network page). Phones can never connect on Public networks.
3. Phone page → **Allow phones on Home networks** (once, admin password), then **Pair…**, and accept on both sides.

Each paired phone has switches for what it may do. *Control this PC* (remote mouse and keyboard) and *Run commands* are the powerful ones: turn them off if you don't use them.

**Phone screen** shows the phone in a window, sound included, and lets you use it with the mouse and keyboard ([scrcpy](https://github.com/Genymobile/scrcpy)). Open **Phone Screen** from the app grid, or **Show screen** on the Phone page.
- **USB:** on the phone, Settings → About phone → tap *Build number* 7 times, then Developer options → *USB debugging*. Plug it in, approve it in the RudramOS USB prompt, and tap *Allow* on the phone.
- **Wi-Fi** (Android 11+): Developer options → *Wireless debugging* → *Pair device with pairing code*. Type the address and code it shows into the Phone page, then the address from the Wireless debugging screen into *Connect over Wi-Fi*.

From a terminal: `pcos-phone screen`, `pcos-phone devices`, `pcos-phone pair ADDRESS:PORT CODE`, `pcos-phone connect ADDRESS:PORT`.

## PC Cleaner
**PC Cleaner** (app grid, or `pc-cleaner` in a terminal) removes junk files and privacy traces:
- app and Flatpak caches, shader caches, thumbnails and the Trash;
- recent-files history and terminal history;
- history, cache and cookies of Firefox, Chrome, Chromium, Brave, Edge and Vivaldi (normal and Flatpak; Firefox bookmarks are kept);
- VLC and mpv history, editor and developer caches.

Tick items, **Analyze** to see how much space they take, then **Run Cleaner**. Safe items are ticked by default. Anything disruptive (Trash, thumbnails, cookies, terminal history) you tick yourself. **System maintenance** items (system logs older than 7 days, crash dumps, unused app runtimes) ask for your admin password when they're cleaned. **Schedule** cleans automatically every day or week, and a run missed while the PC was off happens at the next start. Details: [pc-cleaner README](https://github.com/venkateshguggilla/pc-cleaner#linux-rudramos).

## Temp Monitor and fans
**Temp Monitor** (app grid, or `temp-monitor`) shows live temperature and usage for the CPU, GPU, RAM and every drive, plus every fan's speed. `temp-monitor --print` prints the same in a terminal.

Fans are left to the BIOS until you choose otherwise. In Temp Monitor's **Fans** card, pick a profile in the card's header, use **Edit** on a fan for its own fixed speed or curve (drag the points), or open **Safety limits…**. The same from a terminal:
```bash
temp-monitor fan
```
```bash
temp-monitor fan profile balanced
```
- **Profiles:** *Auto* (BIOS, the default), *Silent*, *Balanced*, *Performance*, or *Custom* (each fan Auto, a fixed %, or its own temperature curve, e.g. `temp-monitor fan curve 1 40:30 60:50 80:100`).
- **Always on:** fans never drop below 20 %. If the CPU reaches 95 °C or the GPU 90 °C, every fan goes to 100 %. A fan that stops while it should be spinning is flagged. Lowering these limits asks for your admin approval.
- If the fan service stops or crashes, every fan goes back to BIOS control exactly as it was.
- **Overheat alerts and history:** while you're logged in, a background monitor records temperatures, usage and fan speeds (1-second detail for 2 hours, per-minute for 30 days, kept on this PC only). It notifies you when something stays hot for 30 seconds, urgently when it goes 5 °C past that or a fan stops. See it all in Temp Monitor → **History** (or click a card's graph): 5 minutes to 30 days, compare two series, past alerts, CSV export. Details: [temp-monitor docs/MONITOR.md](https://github.com/venkateshguggilla/temp-monitor/blob/main/docs/MONITOR.md).
- Full guide: [temp-monitor docs/FANS.md](https://github.com/venkateshguggilla/temp-monitor/blob/main/docs/FANS.md).

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

## Dual boot with Windows
RudramOS can share a PC with Windows (UEFI).
- **Best:** a second drive just for RudramOS. Choose that drive in the installer and Windows' drive is never touched.
- **Same drive:** in Windows, back up first, save the **BitLocker recovery key** (Microsoft account) and suspend BitLocker, turn off *Fast Startup*, and shrink the Windows partition in Disk Management (at least 100 GB free). In the installer's *Installation Destination*, install into the **free space only**.

After installing:
- **Boot menu:** when Windows' boot manager is found on any drive, the RudramOS boot menu shows a **Windows** entry and waits 5 seconds (otherwise 1). GRUB checks at every start, so nothing needs setting up, and the entry goes away by itself if Windows does. To leave it out: Control Center → System → *Windows in the boot menu* off (`sudo /usr/libexec/pcos/pcos-grub-theme windows-off`). The PC's own boot key (often F12) also works.
- **Clock:** Windows keeps the hardware clock in local time, Linux in UTC, so the time jumps by your time zone's offset when switching. Turn on **Same clock as Windows** (Control Center → System, or the *Windows on this PC* step of Welcome to RudramOS), which runs `timedatectl set-local-rtc 1`.
- **BitLocker:** if Windows asks for its recovery key when started from the RudramOS menu, start it with the PC's boot key instead, or suspend and resume BitLocker once in Windows.
- Windows can't read RudramOS's encrypted drive. RudramOS can read Windows' files only if BitLocker is off.

## Building the installer ISO
GitHub → Actions → **Build RudramOS installer ISO** → Run workflow (platform `amd64`, choose the **variant**). Download the `<variant>-anaconda-iso` artifact.
