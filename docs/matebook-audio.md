# Huawei MateBook 14s audio routing (optional)

Select **Huawei MateBook 14s audio workaround** in PoeDeploy's section chooser.
Full setup also visits this section, but installation always requires an explicit
`y` and both hardware identities below. Other machines are skipped without
installing audio dependencies or changing their configuration.

The affected laptop has working SOF firmware, PipeWire and WirePlumber, and an
unmuted output receiving streams, but silent internal speakers. It also supports
PulseAudio: the listener uses kernel ALSA controls and HDA verbs, independent of
the audio server. Neither server is installed, replaced, restarted or configured. Its internal
speaker follows the headphone connection selector. This workaround changes only
the confirmed routing verbs. It does not install a replacement driver, disable
microphones, select PulseAudio/PipeWire profiles/ports, or change power-saving settings.

## Hardware restriction and installation

Both must match:

- `/sys/class/dmi/id/product_name` is exactly `HKF-WXX`.
- A `/proc/asound/card*/codec#*` entry has `Subsystem Id: 0x19e53285`.

The confirmed codec is Conexant SN6140 with `sof-audio-pci-intel-tgl`.
PoeDeploy reads the card number and the codec's `Address:` field, then constructs
`/dev/snd/hwC<card>D<address>`. Card 0 is never assumed. Ambiguous matches are
rejected. A read-only preflight checks these identities before installation.
If the codec has not appeared yet, rerun this section once it is available.
Chroot installations are skipped until first boot.

PoeDeploy's existing dependency helper installs Arch's `alsa-tools` (`hda-verb`)
and Python when missing. `libasound.so.2` is supplied by alsa-tools' `alsa-lib`
dependency. No AUR or additional Python modules are used.

Root-owned files:

- `/usr/local/lib/poedeploy/matebook-audio.py`: routing/event listener.
- `/etc/systemd/system/poedeploy-matebook-audio.service`: system service.
- `/usr/lib/systemd/system-sleep/poedeploy-matebook-audio`: post-resume hook.

Repeated installation replaces these files, reloads systemd and restarts the one
service, so updates take effect immediately. There is no desktop autostart entry,
second listener, timer, or per-user dependency. Do not run the upstream monitor
at the same time. Disable any separately installed workaround before enabling
this one.

## Event handling and battery use

The listener subscribes directly to **ALSA control events** through libasound,
using a read-only, nonblocking control handle and blocking `poll()` between
events. The kernel reports jack changes through ALSA controls. This does **not**
assume udev sends headphone insertion events. At connection time the service
checks for a Headphone/Headset Jack control and warns if none is exported.
It then cannot guarantee automatic jack switching. Investigate driver support
rather than adding a polling loop.

Kernel sound-device uevents trigger discovery/reconnection after device arrival,
removal, or reported resets. Once the card is identified, events on unrelated
cards are ignored. A systemd sleep hook signals only the existing
listener after resume, without depending on a user D-Bus session. Startup and
resume rediscover the codec. Every routing batch rechecks both identities.
ALSA jack, speaker/headphone playback-switch, auto-mute and output-route changes
trigger routing. Volume, microphone and meter events are ignored.

A burst is coalesced with a 400 ms settling delay, followed by **one** check two
seconds later. The follow-up reapplies routing after normal WirePlumber/driver
output-switch writes. Later relevant ALSA route changes also schedule a batch.
This preserves normal PulseAudio or PipeWire/WirePlumber profile, port, mute and volume policy.
The service never invokes `pacmd`, `wpctl`, or `pactl` to change those settings.

There is no periodic polling or periodic codec writing. After these bounded
checks the listener waits indefinitely. It never opens a playback/capture PCM
or keeps the hwdep open: each short `hda-verb` process exits after its command.
The idle ALSA control subscription does not request an active audio stream.
Routing may briefly wake the codec on a real event, but there are no idle verbs
or changes to runtime power management. This still needs power-saving validation
on the affected hardware.

Physical presence is read using `0x16 0xf09 0`, parsing the returned hexadecimal
`value` and testing bit 31 (`0x80000000`). Failed commands, malformed reads and
missing devices are explicit errors, never interpreted as “unplugged.” No route
is written after a failed presence read. A partial write failure is logged and
retried only by the bounded follow-up or another event. Errors and route-state
changes are logged. Repeated successful states and idle events are silent.

Completely silent codec resets that emit neither an ALSA route event nor a
sound-device event are not observable without polling. If runtime audio power
saving exposes such a reset, restart the service and collect logs. Do not disable
SOF or power saving to hide it. On-device testing must determine whether a
further kernel-specific event source is needed.

## Verification on the laptop

```bash
# Read-only identity check (does not invoke hda-verb):
python3 installer/matebook-audio/routing.py --check
systemctl status poedeploy-matebook-audio.service
journalctl -u poedeploy-matebook-audio.service -b
```

To inspect actual jack events, install/use Arch's `alsa-utils` and run
`alsactl monitor hw:<discovered-card>` while inserting/removing headphones.
The expected events contain a Headphone/Headset Jack control. Output-switch
control events can follow as WirePlumber changes ports. This diagnostic command
is not required or launched by the installed service.

Only the three speaker commands have been physically confirmed on the affected
laptop. Automated tests use fixture identities, fake codecs and mocked event
sources, not this PC's hardware. Remaining tests:

1. Speakers with headphones absent. Normal volume/mute and microphones.
2. With the installed server (PulseAudio or PipeWire/WirePlumber), test wired
   headphone insertion/removal repeatedly and during playback. Verify
   headphone sound, speaker silence when plugged, and normal server port switching.
3. Reboot, including initially plugged headphones and late device availability.
4. Suspend/resume with and without headphones, then insert/remove again.
5. Audio runtime power saving: let audio go idle, then resume playback repeatedly.
   Verify routing survives, no continuous codec access, and no unexpected wakeups.
6. Reinstall the section. Verify only one service/listener and new files active.

## Disable or remove

```bash
sudo systemctl disable --now poedeploy-matebook-audio.service
```

The resume hook only signals an active listener, so disabling the service is
sufficient. To remove its files:

```bash
sudo rm -f /etc/systemd/system/poedeploy-matebook-audio.service \
  /usr/local/lib/poedeploy/matebook-audio.py \
  /usr/lib/systemd/system-sleep/poedeploy-matebook-audio
sudo systemctl daemon-reload
```

Reboot to restore the driver's original volatile codec state. Do not blindly
uninstall `alsa-tools`, Python or `alsa-lib`: other applications may need them.

References: [original hardware routing explanation](https://github.com/Smoren/huawei-ubuntu-sound-fix),
[ALSA control interface and events](https://www.alsa-project.org/alsa-doc/alsa-lib/control.html),
[ALSA jack reporting in the kernel](https://github.com/torvalds/linux/blob/master/sound/core/jack.c),
[ALSA event-monitor implementation](https://github.com/alsa-project/alsa-utils/blob/master/alsactl/monitor.c).
The upstream timed monitor and obsolete PulseAudio commands are not installed.
