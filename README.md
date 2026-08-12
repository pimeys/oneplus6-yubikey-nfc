# OnePlus 6 YubiKey NFC bridge

Linux NFC-to-PC/SC bridge for using an existing KeePassXC YubiKey HMAC-SHA1 challenge-response factor on a postmarketOS OnePlus 6 (`oneplus-enchilada`).

The bridge is operational. KeePassXC 2.7.12 detects both programmed YubiKey OTP slots over NFC and successfully reopened a throwaway KDBX protected by a password plus YubiKey challenge-response. The production vault was not modified.

## Quick install: bridge + GNOME Secrets

This is the recommended path. It installs the PC/SC bridge, GNOME Secrets,
py3-pyscard, and the touch-friendly YubiKey provider in one deployment.

The supported baseline is the official postmarketOS v26.06
`linux-postmarketos-qcom-sdm845` package. It already contains the OnePlus 6/6T
PN553 device-tree node and the NXP NCI I²C driver; no custom kernel build or
patch is required. The deployment script checks the running kernel and refuses
to install unless `nfc0` is available.

On the phone, install its native build dependencies once:

```sh
sudo apk add build-base pkgconf pcsc-lite-dev libnl3-dev
```

On the workstation, download or clone this repository and ensure a C compiler,
Python 3, pkg-config, pcsc-lite and libnl3 development files, OpenSSL headers,
`wget`, SSH, and SCP are available. Then run:

```sh
PHONE=user@oneplus.home.arpa ./scripts/deploy-phone
```

Set `PHONE` to the phone's SSH target. `REMOTE_DIR` optionally overrides the
home-relative `Projects/oneplus-yubikey-nfc` upload path. The script:

1. Builds and tests the bridge and Secrets provider locally.
2. Uploads the source and repeats the bridge build and tests on the phone.
3. Installs the PC/SC driver, PN553 initializer, and systemd configuration.
4. Simulates, then installs the pinned GNOME Secrets and py3-pyscard packages.
5. Installs the provider overlay and replaces the normal **Secrets** launcher.

It uses the shared SSH ControlMaster path `~/.ssh/cm/%r@%h:%p` and prompts for
the phone's sudo password during installation. After it completes, launch the
normal **Secrets** icon and follow the
[touch workflow](#touch-friendly-secrets-workflow).

## Confirmed environment

This works _for me_ and is mostly written by Kimi K3. USE AT YOUR OWN RISK.

- Phone: OnePlus 6 (`oneplus-enchilada`)
- OS: postmarketOS v26.06 with systemd
- Kernel: `7.1.0-rc1-sdm845`
- NFC controller: NXP PN553 through `nxp-nci_i2c`, exposed as `nfc0`
- KeePassXC: 2.7.12
- YubiKey: YubiKey 5 NFC, firmware 5.7.4
- Programmed legacy OTP challenge-response slots: 1 and 2
- Transport: Linux `AF_NFC`, `NFC_SOCKPROTO_RAW`, ISO-DEP/ISO 14443

This setup uses the official postmarketOS v26.06 kernel package, not a locally
patched kernel. The release
[`sdm845-oneplus-common.dtsi`](https://gitlab.com/sdm845-mainline/linux/-/blob/sdm845-7.1-rc1-r0/arch/arm64/boot/dts/qcom/sdm845-oneplus-common.dtsi)
defines the PN553 at I²C address `0x28`, and the release
[kernel configuration](https://gitlab.postmarketos.org/postmarketOS/pmaports/-/blob/v26.06/device/community/linux-postmarketos-qcom-sdm845/config-postmarketos-qcom-sdm845.aarch64)
enables `CONFIG_NFC_NXP_NCI_I2C`.

## Architecture

```text
KeePassXC
   │ existing PC/SC YubiKey backend and OTP APDUs
   ▼
pcscd (pcscd user, CAP_NET_ADMIN only)
   │ libnlnfc IFD handler
   ▼
Linux generic-netlink + AF_NFC ISO-DEP
   ▼
PN553 → YubiKey OTP applet
```

KeePassXC and the KDBX format are unchanged. The HMAC response is never written to a keyfile. KeePassXC receives no capability; only `pcscd` receives `CAP_NET_ADMIN`, which is required to power and poll the NFC controller.

The GNOME Secrets overlay preserves password, key file, and YubiKey as three
distinct KDBX4 credential contributions. Its process-local PyKeePass adapter
normalizes the selected key file and applies KeePassXC's composite-key order;
the component envelope and HMAC response exist only in memory.

`PrivateUsers=false` is required in the pcscd service override. A capability inside systemd's private user namespace does not satisfy the physical NFC device's host-namespace generic-netlink check.

## Repository contents

- `vendor/ifdnlnfc/`: PC/SC IFD handler based on StarGate01/ifdnlnfc revision `86703e844652ce99bfd5a4d2aa4fceb7c3fb2a5a`
- `src/ykchal_nfc.c`: standalone OTP challenge-response diagnostic probe
- `tests/ifd_contract.c`: synthetic IFD boundary and error-contract checks
- `packaging/reader.conf`: pcsc-lite reader definition for NFC adapter index 0
- `packaging/pcscd.service.d/oneplus-nfc.conf`: constrained systemd capability/address-family override and persistent daemon command
- `packaging/oneplus-nfc-init.service`: root PN553 rebind ordered before each `pcscd.service` start
- `scripts/install-on-phone`: root installation helper
- `scripts/deploy-phone`: workstation-to-phone build and deployment flow
- `scripts/oneplus-nfc-init`: bounded pre-PCSC controller initialization
- `secrets-overlay/gsecrets/provider/`: GNOME Secrets 9.6 PC/SC YubiKey provider overlay
- `scripts/check-kernel-nfc`: non-mutating device, kernel-option, driver, and `nfc0` preflight
- `scripts/install-secrets-on-phone`: pinned Secrets installation with dry-run/apply modes
- `scripts/secrets-nfc`: overlay-aware GNOME Secrets launcher

The vendored IFD handler includes local fixes for adapter lookup, netlink receive failures, cleanup after initialization errors, deterministic power-up failure, uninitialized kernel attributes, APDU types, and PC/SC output-buffer validation.

## Build and test

Install the IFD handler dependencies on postmarketOS:

```sh
sudo apk add build-base pkgconf pcsc-lite-dev libnl3-dev
```

Build the production bridge and run its synthetic contract checks:

```sh
make driver test
```

The diagnostic probe additionally needs OpenSSL headers and `wget`:

```sh
sudo apk add openssl-dev wget
make probe
```

`make all test` builds both binaries. The probe build downloads libfido2 1.16.0 and verifies SHA-256 `7d86088ef4a48f9faad4ff6f41343328157849153a8dc94d88f4b5461cb29474`.

## Manual installation on the phone

Use this path when the project checkout is already on the phone:

```sh
./scripts/check-kernel-nfc
make driver test
sudo ./scripts/install-on-phone
./scripts/install-secrets-on-phone --dry-run
sudo ./scripts/install-secrets-on-phone --apply
```

The bridge installer:

1. Backs up an existing `/usr/local/lib/libnlnfc.so.0.0.0`.
2. Installs the IFD handler and stable soname links under `/usr/local/lib`.
3. Installs `/etc/reader.conf.d/libnlnfc`.
4. Installs the constrained persistent `pcscd.service` override.
5. Installs the PN553 initializer as a required predecessor of `pcscd.service`.
6. Removes obsolete recovery helpers that attempted unsafe live controller resets.
7. Enables `pcscd.socket` and restarts `pcscd.service`.

### If `nfc0` is missing

First update the official release packages and reboot:

```sh
sudo apk update
sudo apk upgrade
sudo reboot
```

After reconnecting, run:

```sh
apk policy linux-postmarketos-qcom-sdm845
./scripts/check-kernel-nfc
```

Do not build or flash a custom kernel merely for this project. If the official
v26.06 package is installed and the preflight still reports no `nfc0`, inspect
the `nxp_nci_i2c` probe failure:

```sh
sudo dmesg | grep -Ei 'nfc|nxp|pn553'
```

Users intentionally running another kernel must provide both the official
OnePlus PN553 device-tree node and the four NFC options checked by the
preflight script. Building and flashing such a kernel is device-recovery work
outside this installer; it is not an automatic or safe fallback.

## Touch-friendly Secrets workflow

Both installation paths install Alpine's GNOME Secrets 9.6 and py3-pyscard at
their tested versions, then place the PC/SC provider only under `/usr/local`.
They do not patch Alpine-owned Python modules, alter the KDBX format, or create
a challenge-response keyfile.

For touch use:

1. Close any running Secrets instance.
2. Hold the YubiKey against the upper rear NFC antenna.
3. Launch the normal **Secrets** icon; its desktop entry now uses
   `/usr/local/bin/secrets-nfc`.
4. Open the KDBX, select its existing key file if it uses one, and type its
   password.
5. Select the database's actual `OnePlus 6 NFC 00 00 — Slot 1` or `— Slot 2`
   credential. Secrets never guesses an unknown database's slot.
6. Tap **Unlock**, then continue holding the key against the phone when
   prompted.
7. Use Secrets' adaptive search, username/password copy buttons, and entry
   editor.

Secrets preserves its native inactivity lock and clipboard-clearing behavior.
Browser-extension autofill is not part of this touch workflow.

## Verify

List the virtual reader:

```sh
pcsc_scan -r
```

Expected:

```text
0: OnePlus 6 NFC 00 00
```

Then hold the YubiKey flat against the upper rear of the phone:

```sh
pcsc_scan -n -t 30
```

The verified card event and ATR were:

```text
Card state: Card inserted
ATR: 3B 8D 80 01 80 73 C0 21 C0 57 59 75 62 69 4B 65 79 F9
```

Open KeePassXC's database credentials dialog while the key is present. The YubiKey challenge-response selector should list the programmed slots.

## Verified transport proof

The diagnostic used this public 64-byte challenge for slot 2:

```text
000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f
```

The NFC YubiKey and an identically programmed workstation key returned the
same 20-byte response. Its value is intentionally omitted because the keys
mirror a production credential.

The probe selects OTP applet AID `A0000005272001`, sends instruction `0x01`, addresses slot 1 as `0x30` or slot 2 as `0x38`, and returns the same 20-byte HMAC-SHA1 response KeePassXC expects. FIDO2 and database rekeying are not involved.

To repeat the diagnostic:

```sh
sudo build/ykchal-nfc 2 \
  000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f
```

Do not assign file capabilities to a binary in a user-writable directory.

## PN553 initialization and recovery

On the tested kernel, the PN553 needs one driver rebind immediately before its first NFC power request. The pcscd override requires `oneplus-nfc-init.service`; because the one-shot does not remain active, it reruns as root before every `pcscd.service` start.

The override removes `pcscd --auto-exit`: pcsc-lite 2.3.3 on this phone otherwise unlinks `/run/pcscd/pcscd.comm` when it exits while `pcscd.socket` remains active, leaving subsequent clients unable to reactivate the daemon. Verify the latest initializer run with:

```sh
systemctl status oneplus-nfc-init.service
```

Reboot the phone if this initializer or `pcsc_scan -r` later fails. Do not use rfkill toggles as a recovery mechanism for this controller.

Do not manually unbind a PN553 after an I²C error: one observed failure put both the unbind process and `irq/176-nxp-nci` into uninterruptible `D` state. A later rfkill reset also left the controller unable to power up.

Relevant timeout evidence from the diagnostic path:

```text
generic-netlink: ETIMEDOUT (110)
nxp-nci_i2c 3-0028: NFC: Read failed with error -121
```

`-121` is `EREMOTEIO`. The long-term fix belongs in the PN553 power/GPIO sequencing in the kernel, not in KeePassXC or the KDBX path.

## Production-use constraints

- Back up the production KDBX before its first NFC open.
- Open a read-only copy first.
- Verify both identically programmed physical YubiKeys independently.
- Keep the original HMAC secret recovery material available.
- Never store the HMAC response as a persistent keyfile.
- Never grant `CAP_NET_ADMIN` to KeePassXC.
- Treat malformed APDUs, truncated responses, unexpected status words, and NFC removal as hard failures.

## License and provenance

Project-owned code and integration scripts are GPL-3.0-or-later; the root
`COPYING` contains the GPLv3 terms. The GNOME Secrets provider overlay is
GPL-3.0-only and adapts the GNOME Secrets 9.6 provider architecture. The
vendored `ifdnlnfc` IFD handler remains GPL-2.0-only; its upstream `COPYING`
and copyright notices are preserved. The diagnostic probe compiles
libfido2's BSD-2-Clause generic-netlink implementation from a
checksum-pinned source archive and follows OTP APDU behavior demonstrated by
GPL-3.0 ykDroid.
