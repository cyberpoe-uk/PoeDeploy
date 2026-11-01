# PenDash embedded source

This directory was imported from PenDash commit
`6601a22ac4dd864be0c5d8df1b9ad3e5ce5c16ad` and is now maintained as part of
PoeDeploy. It contains the dashboard installer, runtime assets, curated BlackArch
security-tool installation, and focused tests. Chromium and Burp launch normally,
with proxy and certificate setup left to the user. The original hardware-specific
laptop installation workflow has been removed.

The system specifications, process list, mounted-share collector, connectivity
details, and MPRIS media player were ported from the bundled PoeDash source
(see `../poedash/LICENSE`). PenDash uses its own artwork cache, pauses collectors
while hidden, and reduces their refresh rate on battery. Quick Launch, CTF
sessions, target editing, and readiness polling have been removed.
