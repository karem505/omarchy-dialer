# Omarchy Dialer — placing and receiving phone calls from the PC

**Date:** 2026-08-30
**Host:** Omarchy / Hyprland (Wayland), Quickshell 0.3.1, PipeWire 1.6.8, WirePlumber 0.5.15, BlueZ 5.87
**Phone:** Example Phone (`AA:BB:CC:DD:EE:FF`), ColorOS
**Status:** Approved design, pending implementation plan

## Problem

Calls arrive on the phone while the user is working at the PC. Answering means
picking up a second device, and dialling means retyping numbers that already
exist in the phone's address book. The goal is a native Omarchy application
that places, answers and ends calls using the phone's cellular radio, with
call audio on the PC's own microphone and speakers, and the phone's contacts
searchable from the keyboard.

## Feasibility — what was proven before this design

This is not speculative. Each claim below was verified live on the target
hardware on 2026-08-30.

**PipeWire ships a complete telephony control API and it is enabled by
default.** `org.pipewire.Telephony` is owned by `wireplumber` on the session
bus with no configuration required. When a phone connects in the Hands-Free
Profile, an object appears at `/org/pipewire/Telephony/ag1`:

```
org.pipewire.Telephony.AudioGateway1
    Dial(s), HangupAll(), SwapCalls(), HoldAndAnswer(),
    ReleaseAndAnswer(), ReleaseAndSwap(), CreateMultiparty(), SendTones(s)
    Address (s), SpeakerVolume (y, rw), MicrophoneVolume (y, rw)
org.pipewire.Telephony.AudioGatewayTransport1
    State (s), Codec (y), RejectSCO (b, rw), Activate()
org.ofono.VoiceCallManager        (compatibility alias, same methods)
    signals: CallAdded(oa{sv}), CallRemoved(o)
```

Per-call objects appear beneath it at `/org/pipewire/Telephony/ag1/callN`:

```
org.pipewire.Telephony.Call1
    Answer(), Hangup()
    LineIdentification (s), IncomingLine (s), Name (s),
    Multiparty (b), State (s)
```

**A real outgoing call was placed and connected.** `Dial("+20…")` returned
success; `CallAdded` fired carrying `LineIdentification` equal to the dialled
number; `Call1.State` reached `active` when the far end answered; transport
`State` moved `idle → active` with `Codec = 2` (mSBC wideband). The PC's
`Speaker__sink` and `Mic2__source` both entered `RUNNING` — PipeWire routes the
SCO stream onto the default devices rather than exposing a separate Bluetooth
node, so no manual routing is needed. `CallRemoved` fired cleanly on teardown.

**The Bluetooth roles line up.** `hfp_hf` is compiled into
`libspa-bluez5.so`; the local adapter advertises `0000111e` (Handsfree unit);
the phone advertises `0000111f` (Handsfree Audio Gateway); the card settles on
`Active Profile: audio-gateway`.

### What is *not* proven

**Contacts over Bluetooth PBAP fails.** `bluez-obex` is installed and obexd
runs, and `CreateSession(…, Target=pbap)` returns a session path, but the
`PhonebookAccess1` interface never materialises on it. obexd logs the phone
answering the OBEX CONNECT with `0xff` and dropping the transport:

```
connect_cb: Timed out waiting for response
Invalid unicode header (0x10) length (31)
CONNECT(0x0), <unknown>(0xff)
DISCONNECT(0x1), Success(0x20)
disconnected: Transport got disconnected
```

**SMS over Bluetooth MAP fails identically** — same OBEX rejection, so this is
ColorOS refusing OBEX wholesale rather than a contacts-specific permission.

**KDE Connect is paired but its data plugins are dormant.** The Example Phone is
paired and reachable over LAN (`192.168.1.x`, device id
`<kdeconnect-device-id>`). The `contacts` D-Bus path exists and
`synchronizeRemoteWithLocal()` is accepted, but produces zero vCards in
`~/.local/share/kpeoplevcard/kdeconnect-<id>/` — the signature of the Android
app lacking the Contacts permission. No `sms` D-Bus path exists for the device
at all, so that plugin is not instantiated. Only
`org.kde.kdeconnect.device.telephony` is live, exposing `callReceived(sss)`.

Both contacts routes and both SMS routes are therefore blocked behind
phone-side permissions that cannot be granted from Linux. **The design must
not assume they work.**

### Quickshell constraint

Quickshell 0.3.1 ships `Quickshell`, `.Bluetooth`, `.DBusMenu`, `.Hyprland`,
`.I3`, `.Io`, `.Networking`, `.Wayland`, `.Widgets`, `.WindowManager`, `.X11`.
There is **no generic D-Bus client**, so QML cannot call
`org.pipewire.Telephony` directly. `Quickshell.Io` does provide `Process`,
`Socket` and `SocketServer`. A helper process is therefore structural, not a
stylistic preference.

## Non-goals

- Routing calls over VoIP, SIP or any carrier-independent transport. The
  phone's radio places every call.
- Replacing the phone's dialer. The phone remains authoritative.
- Call recording, transcription, or contact editing. Read-only address book.
- Multi-phone support. One paired gateway at a time.

## Behaviour

A standalone window, launched from the app grid or a Hyprland bind.

**Idle.** Header shows the connected gateway (`Example Phone`) or a
disconnected state with a Connect action. Left pane is a filter-as-you-type
contact list; right pane is a keypad and a number field. Enter or Call dials
whatever is in the number field, or the selected contact's number.

**Outgoing.** On `Dial`, the view switches to a call card showing the number,
resolved contact name where known, elapsed timer, and Hang Up. Keypad stays
reachable for DTMF via `SendTones`. Mic and speaker volume are bound to
`MicrophoneVolume` / `SpeakerVolume`.

**Incoming.** `CallAdded` with `State = incoming` raises the window and shows
Answer / Reject against the caller ID, name-resolved when contacts are
available. Answer calls `Call1.Answer()`, reject calls `Call1.Hangup()`.

**Degraded.** When no contacts provider is available the list pane is replaced
by a short explanation of which permission is missing and the keypad remains
fully functional. Messaging is hidden entirely rather than shown broken.

## Architecture

Three units with narrow interfaces.

```
   Quickshell QML app  (omarchy-dialer)
            |  newline-delimited JSON over a Unix socket
            v
   omarchy-dialerd  (Python)
            |            |                |
      CallProvider   ContactsProvider  MessageProvider
            |            |                |
   org.pipewire     PBAP -> KDE       MAP -> KDE
    .Telephony      Connect -> none   Connect -> none
```

The daemon owns all D-Bus. The QML app owns all presentation and never learns
a bus name. The socket protocol is the only contract between them, which keeps
the UI testable against a recorded transcript with no Bluetooth present.

### Provider model

`CallProvider` is a hard dependency with exactly one implementation
(PipeWire Telephony). If it is unavailable the app reports the gateway as
disconnected — there is no fallback, and inventing one would be dishonest.

`ContactsProvider` and `MessageProvider` are each resolved at startup by trying
implementations in order and taking the first that yields data:

| Provider | Order | Notes |
|---|---|---|
| Contacts | `pbap` → `kdeconnect` → `null` | `null` yields an empty list plus a reason string |
| Messages | `map` → `kdeconnect` → `null` | `null` causes the UI to hide messaging |

Each provider reports `{available, reason}` so the UI can explain *why*
something is missing rather than silently showing nothing. Re-probing is
triggered by a `refresh` command, so fixing a phone permission does not require
restarting the daemon.

### Boot model

WirePlumber currently auto-connects only `[ a2dp_sink a2dp_source ]`, per
`~/.config/wireplumber/wireplumber.conf.d/bluetooth-a2dp-autoconnect.conf`.
The HFP link was brought up by hand during verification. The install step adds
`hfp_hf` to that list so the gateway appears without intervention. The stale
`11:22:33:44:55:66` bond has been removed and must not be recreated; the live
bond `AA:BB:CC:DD:EE:FF` is marked trusted.

## Components

### `omarchy-dialerd`

Python, `dasbus` or `pydbus` on GLib. Single-threaded event loop. Listens on
`$XDG_RUNTIME_DIR/omarchy-dialer.sock`, accepts multiple clients, broadcasts
state to all of them. No authentication — the socket is user-owned, mode 0600.

Watches `InterfacesAdded` / `InterfacesRemoved` on
`/org/pipewire/Telephony` to track gateway and call lifecycle, and
`PropertiesChanged` on each `Call1` for state transitions. Holds no state the
bus does not already hold; on client connect it replays a full snapshot.

### Socket protocol

Newline-delimited JSON. Client to daemon:

```json
{"cmd":"dial","number":"+201000000001"}
{"cmd":"answer","call":"call1"}
{"cmd":"hangup","call":"call1"}
{"cmd":"tones","digits":"123"}
{"cmd":"set_volume","which":"mic","value":12}
{"cmd":"contacts"}
{"cmd":"refresh"}
```

Daemon to client:

```json
{"ev":"gateway","connected":true,"address":"AA:BB:CC:DD:EE:FF","name":"Example Phone"}
{"ev":"call","id":"call1","state":"active","line":"+20…","name":"Ahmed"}
{"ev":"call_removed","id":"call1"}
{"ev":"transport","state":"active","codec":2}
{"ev":"contacts","available":false,"reason":"pbap refused; kdeconnect returned 0","items":[]}
{"ev":"error","cmd":"dial","message":"no gateway"}
```

Every event is a complete statement of its subject, so a late-joining client
needs no history to render correctly.

### Quickshell app

```
omarchy-dialer/
  shell.qml            FloatingWindow, wires Bridge to views
  Bridge.qml           Socket + JSON framing, exposes a state model
  Theme.qml            singleton, parses Omarchy theme, hot-reloads
  views/
    Idle.qml           contact list + keypad + number field
    ActiveCall.qml     call card, timer, DTMF, volumes
    Incoming.qml       answer / reject
  components/
    Keypad.qml  ContactRow.qml  StatusHeader.qml
```

`Bridge.qml` owns the only `Quickshell.Io.Socket`, reconnecting with backoff if
the daemon restarts. Views are pure functions of the state model, so any view
can be exercised by feeding the model directly.

### Theming

The app is standalone, so it loads the Omarchy theme itself rather than
inheriting `Commons/Color.qml`. `Theme.qml` reads
`~/.local/state/omarchy/current/theme/colors.toml`, which supplies the tokens
this UI needs — `background`, `lighter_background`, `foreground`,
`dark_foreground`, `accent`, `selection`, `muted`, `red` for the hang-up
action, `green` for answer, and `mode` for light/dark. Typography and spacing
come from the `[font]` and `[spacing]` sections of `shell.toml`.

`~/.local/state/omarchy/current` is a symlink that Omarchy repoints on theme
change. A `Quickshell.Io.FileView` on `colors.toml` with `watchChanges` picks
that up, so switching themes restyles a running dialer with no restart. Current
theme at time of writing is `ethereal`.

## Risks

**Contacts and SMS may stay unavailable.** Mitigated structurally: the app is
useful with calls alone, and the provider model turns this into a
configuration state rather than a broken feature. Not mitigated technically —
if ColorOS never grants OBEX and the KDE Connect plugins stay dormant, those
panes stay empty. This is the single largest open risk and it sits outside the
codebase.

**HFP and A2DP contend for the same link.** Selecting `audio-gateway` takes the
phone out of media-playback duty. Acceptable — a phone acting as a call gateway
is not simultaneously a music source. Worth stating so it is not filed as a
bug later.

**SCO audio quality depends on the adapter.** Verification saw `Codec = 2`
(mSBC, wideband). If a future pairing negotiates CVSD the audio will be
noticeably narrower; surface the codec in the UI rather than hiding it.

**PipeWire's telephony API is young.** `org.pipewire.Telephony` is not yet
widely documented and its shape may shift across releases. The `org.ofono.*`
compatibility aliases on the same objects give a second binding target if the
native names churn. Pin behaviour with the contract tests below.

**Quickshell has no D-Bus and may gain it.** If a future Quickshell exposes a
generic D-Bus client the daemon could collapse into the app. The socket
protocol is deliberately thin so that refactor stays cheap; it is not planned.

## Testing

**Contract tests against a fake bus.** Stand up a `python-dbus` mock exporting
the `AudioGateway1` / `Call1` shapes recorded during verification, and assert
the daemon emits the documented events for dial, answer, remote hangup, and
gateway disappearance. Runs in CI with no Bluetooth.

**Protocol tests.** Feed `Bridge.qml` a recorded transcript and assert each
view renders the right state, including the degraded contacts case.

**Manual hardware pass**, which cannot be automated: place a call and confirm
audio on PC mic and speakers; receive a call and answer from the PC; send DTMF
into an IVR; pull the phone out of range mid-call and confirm the UI returns to
idle rather than hanging.

**Regression guard on the boot path.** After install, reboot and assert
`/org/pipewire/Telephony/ag1` appears without manual `bluetoothctl connect`.

## Phased build order

1. **Daemon + calls.** `CallProvider`, socket protocol, contract tests. Drive
   it with `socat` before any UI exists.
2. **Quickshell app, calls only.** Keypad, active call, incoming. Theme
   loading. This is a complete, shippable product.
3. **Contacts provider.** KDE Connect first — it is likelier to be unblocked
   than ColorOS OBEX — then PBAP behind the same interface.
4. **Messaging.** Only if a provider actually returns data. Gated on step 3
   proving one of the transports viable.

Phases 1 and 2 depend on nothing unproven. Phases 3 and 4 depend entirely on
phone-side permissions and should not block release.

## Out of scope

Call history (needs PBAP `cch` or MAP, both currently refused), contact photos,
conference-call UI beyond `CreateMultiparty`, Bluetooth pairing management —
`omarchy-shell`'s existing bluetooth panel already owns that.
