# RudramOS user guide

For people using RudramOS day to day. No terminal needed: everything here is a button in
**RudramOS Control Center** (app grid) unless it says otherwise. Technical details are in the
[README](../README.md) and [DESIGN](DESIGN.md).

- [First start](#first-start)
- [Installing apps](#installing-apps)
- [Programs you download](#programs-you-download)
- [Browser extensions](#browser-extensions)
- [USB devices](#usb-devices)
- [Networks](#networks)
- [Your phone](#your-phone)
- [Updates](#updates)
- [Security keys and admin approval](#security-keys-and-admin-approval)
- [Disk encryption and the recovery key](#disk-encryption-and-the-recovery-key)
- [Graphics driver](#graphics-driver)
- [Keeping the PC tidy and cool](#keeping-the-pc-tidy-and-cool)
- [When something goes wrong](#when-something-goes-wrong)

## First start
At your first login, **Welcome to RudramOS** walks you through the important choices: how admin
changes are approved, the disk recovery key, privacy, your home network, the graphics driver and
your phone. Close it to finish later; it comes back at the next login. Run it again any time from
the app grid (**Welcome to RudramOS**).

**Do this one thing even if you skip the rest:** create the disk **recovery key** and write it
down (Welcome → Disk encryption, or Control Center → Disk).

## Installing apps
Open **App Store** (in the dock, a shopping bag). Find an app, press **Install**, and approve with
your password. The prompt says what is being installed, for example *"The App Store wants to
install an app for everyone on this PC: org.mozilla.firefox"*. Apps install one after another,
not at the same time: that's normal.

The first time you use the PC with internet, the App Store and the task manager (Mission Center)
are downloaded in the background. If the App Store says it's setting itself up, give it a few
minutes.

## Programs you download
Programs and AppImages from Downloads, the Desktop or a USB drive don't run until you approve
them, like Gatekeeper on a Mac. When you try to open one, a notification says it was blocked.
To allow it: Control Center → **Apps** → **Approve a program** → pick the file. Only approve
programs from places you trust.

## Browser extensions
Firefox installs only extensions you approved. Control Center → **Apps** → paste the extension's
`addons.mozilla.org` link → Enter. Restart Firefox. uBlock Origin (ad and tracker blocking) is
always installed.

## USB devices
A **new** USB device is blocked until you allow it. As soon as you plug it in, a **"USB device
connected"** popup shows its name and what it is:
- **Open:** type your password in the window that appears; the device works until it's unplugged,
  and a USB drive opens in Files. (Keyboards and adapters say **Allow** instead.)
- **Always allow:** now and every time.
- **Keep blocked.**

A drive you always allowed shows "USB drive connected" with **Open** when you plug it in, without
asking for the password again.

A red warning means the device does something unusual for what it looks like, for example a
"USB stick" that can also type like a keyboard. That's a common attack: keep it blocked unless
you're sure.

Nothing new is allowed while the screen is locked. Your keyboard and mouse always work at the
login screen.

## Networks
Every network is **Public** until you say otherwise: nothing on it can reach this PC. Mark your
own Wi-Fi as **Home** (Control Center → **Network**) to let things you turn on there work: phone
link, printer discovery, file sharing. On any other network they're closed again automatically.

To check you're online: the top-right corner of the screen shows the Wi-Fi or network icon; click
it for details. If a hotel or café Wi-Fi needs a sign-in page, it opens by itself (Privacy page:
*Detect Wi-Fi login pages*).

## Your phone
Android phones only (Apple keeps these features to Macs).
- **Phone link** (notifications and replies, texts, call alerts, files, clipboard, find my
  phone): install **KDE Connect** on the phone, be on your **Home** Wi-Fi, then Control Center →
  **Phone** → **Allow phones on Home networks** (once) → **Pair…** and accept on both sides.
  Each paired phone has switches for what it may do.
- **Phone Screen** (see and use the phone in a window): turn on *USB debugging* on the phone
  (Settings → About phone → tap *Build number* 7 times → Developer options), plug it in, allow it
  in the USB prompt and on the phone, then open **Phone Screen**. Over Wi-Fi: Developer options →
  *Wireless debugging* → *Pair device with pairing code*, and type the address and code on the
  Phone page.

## Sharing files with other PCs and phones (LAN Share)
Open **LAN Share** from the app grid. The first time, give this PC a name and a password and pick
the folders to share (each one *Read only* or *Read & write*).
- Other devices can only reach this PC on a **Home** network, and only once you allow it. If
  LAN Share shows a yellow warning, click **How to fix**: it asks for the admin password to mark
  the network as Home, then to allow LAN Share (or use Control Center → **Network** → *LAN Share*).
- **Another PC** (Windows or RudramOS, running LAN Share): click it in the list, enter its
  password, then copy files either way with the buttons or by dragging.
- **A phone** (Android or iPhone, nothing to install): click **Connect a phone**, scan the QR code
  on the same Wi-Fi, tap through the one-time "not private" browser warning, and enter the
  password. The phone can download, and upload into *Read & write* folders.
- On any other network LAN Share closes by itself, and this PC doesn't show up there.

## Updates
Updates download by themselves in the background and are used after the next restart. Control
Center → **Updates** shows whether you're up to date. **Update now** gets the newest one right
away, **Restart** starts using it. Your files, apps and settings stay as they are.

If something stopped working after an update: Updates → **Roll back** starts the previous version
after a restart. The next update brings you forward again.

## Security keys and admin approval
Installing apps and changing system settings needs your admin password (**Standard**, like a Mac).
**Strong** also needs a touch of a USB security key (YubiKey, Nitrokey, Google Titan…), so a
stolen password isn't enough.

To use Strong: Control Center → **Security** → **Register a security key** (do it for **two**
keys: one is a backup kept somewhere safe) → **Test** → **Turn on Strong mode**. Strong mode
won't turn on unless the test passes, so you can't lock yourself out by mistake. If you lose
every key, getting back needs the installer USB, the disk recovery key and some technical steps
([README](../README.md#admin-approval-standard-or-strong)), so keep the backup key safe.

## Disk encryption and the recovery key
If you ticked *Encrypt my data* when installing, nobody can read the drive without unlocking it,
even with the drive taken out of the PC. Control Center → **Disk**:
- **Recovery key:** a long code that always unlocks the drive. **Write it down or print it, and
  keep it away from the PC.** Creating a new one makes the old one stop working.
- **Unlock automatically:** the PC's TPM chip unlocks the drive, only on this PC and only if
  start-up wasn't tampered with. Best for desktops.
- **TPM + PIN:** the same plus a short PIN at start-up. Best for laptops.
- **Security key:** touch your key at start-up.

**After a BIOS/firmware update** the drive may ask for the recovery key once. Type it, then
Control Center → Disk → **Re-seal**.

## Graphics driver
RudramOS checks your graphics card at login and offers the right driver (Control Center →
**Graphics**). It downloads in the background; a notification asks you to restart. On NVIDIA
cards, after that restart a **blue "MOK Manager" screen** appears once: choose **Enroll MOK →
Continue → Yes**, type the password **universalblue** (nothing shows while you type), then
**Reboot**. If the desktop feels slow, check Settings → About: the graphics line should name your
card, not "llvmpipe".

## Keeping the PC tidy and cool
- **PC Cleaner:** removes caches, old logs and browser traces. **Analyze**, then **Run Cleaner**.
  **Schedule** does it automatically.
- **Temp Monitor:** temperatures, fan speeds and fan profiles, with a warning when something gets
  too hot. Click a reading to see its history.
- **Mission Center** (dock): running apps and processes; select one and **End task** to close a
  stuck app.

## Windows on the same PC
If Windows is installed too, the boot menu waits 5 seconds at start-up: RudramOS starts by itself,
or choose **Windows** with the arrow keys and Enter. Turn on **Same clock as Windows** (Control
Center → System) so the time is right in both. If Windows asks for its BitLocker recovery key
when started from this menu, start it with the PC's boot key (often F12) instead.

## When something goes wrong
- **Keyboard or mouse don't work at the login screen:** restart, hold **Shift** (or press
  **Esc**) until the boot menu appears, press ↓ to select the second entry and press **Enter**.
  That starts the previous version. If that doesn't help: in the boot menu press **e**, add
  `systemd.mask=usbguard.service` at the end of the line starting with `linux`, and press
  **Ctrl+X** (USB protection off for one start).
- **The PC doesn't start after an update:** same boot menu, second entry. Then Control Center →
  Updates → **Roll back** to stay on it.
- **The drive asks for the recovery key:** usually after a BIOS update or a Secure Boot change.
  Type the recovery key, then Control Center → Disk → **Re-seal**.
- **Black screen or very slow desktop on NVIDIA:** the MOK screen was probably skipped. Control
  Center → Graphics → install the driver again and look for the blue screen after the restart.
- **An app or device is blocked and you don't know why:** USB devices are on Control Center →
  USB; downloaded programs on Control Center → Apps.
- **Open the BIOS settings:** Control Center → System → **Restart into BIOS / UEFI settings**.
