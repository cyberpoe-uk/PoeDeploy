# Bundled dashboard applications

PoeDash and PenDash are shipped with PoeDeploy so their installation does not
depend on separate websites or GitHub repositories. These directories contain
the program files, assets and focused tests required by each installer.

`poedash/` is the general dashboard with system, process, power, VPN, and
mounted-share monitoring. `pendash/` is the laptop-specific pentesting
dashboard. PenDash supports a dashboard-only mode that skips BlackArch, Burp
Suite, NVIDIA configuration and laptop power configuration.

Dashboard updates are delivered by updating and rerunning PoeDeploy.

PenDash installs Chromium, NSS (`certutil`), and OpenSSL automatically. There is
no browser selection or separate CTF profile. Existing browser data is preserved;
PenDash does not change the system default browser.

Chromium's persistent `~/.config/chromium-flags.conf` routes HTTP and HTTPS through
Burp at `127.0.0.1:8080`, including loopback targets. Existing unrelated flags are
retained and replaced configuration files are backed up. This affects every
normal Chromium launch, so Chromium requires Burp's listener for browsing. Restart
Chromium after installation; the CTF launcher refuses to reuse an existing process
with incompatible proxy settings. Sandbox, certificate checks and web security
remain enabled.

Quick Launch provides BURP, CTF CHROMIUM, TERMINAL, CODE, and WIRESHARK. Save an IP,
hostname or HTTP(S) URL with the existing TARGET control, then click START WEB CTF.
It opens the existing native Burp installation, waits up to 30 seconds for the
listener, and opens Chromium with the saved target (bare hosts use HTTP). Target
arguments are validated and shell-quoted. Burp at `~/BurpSuite/BurpSuite` is reused.

CA trust requires user consent and is never configured unattended. Export your own
Burp CA from `http://burpsuite` through the proxy, normally to
`~/Downloads/cacert.der`, then run:

```sh
pendash setup-burp-ca --certificate ~/Downloads/cacert.der
pendash setup-burp-ca --action status
pendash setup-burp-ca --action remove
```

The command validates CA basic constraints and expiration with OpenSSL, displays
subject, issuer and SHA-256 fingerprint, then asks before importing or replacing
`PenDash Burp CA` with `C,,` trust. Repeat imports skip an identical trusted CA.
Removal requires confirmation and touches only that nickname. Compare the shown
fingerprint with your Burp instance before consenting. If import fails during
replacement, the previous entry is restored.

The NSS database is shared across Chromium profiles and may be used by other
applications: there is no CA trust isolation. System trust stores are untouched.
Following Chromium's Linux certificate documentation, an existing `~/.pki/nssdb`
is preferred; otherwise Chromium M146+ uses `~/.local/share/pki/nssdb` and older
versions use the legacy path. An unknown version fails rather than guessing.
Missing Burp/listener/CA is optional during installation. A real browser/Burp HTTPS
interception test still requires a desktop session and the user's own trusted CA.
