# Deck Mic Toggle

**Deck Mic Toggle** is a small Decky Loader plugin that adds a Quick Access Menu control for the Steam Deck's built-in microphone.

## Features

- Detects the Steam Deck's internal microphone.
- Mutes/unmutes it through PipeWire/PulseAudio using `pactl`.
- Does not disable the audio hardware.
- Does not modify SteamOS system files.
- Requires no sudo at runtime.
- Does not affect speaker/headphone output.
- Re-detects the microphone if the PipeWire source changes.
- Shows the detected source and current mute state.

## Compatibility

Tested on Steam Deck OLED with SteamOS. The plugin is designed to target the internal microphone and avoid selecting USB/Bluetooth microphone devices.

## Installation

Deck Mic Toggle is intended for distribution through the Decky Plugin Store.

For development/testing, copy the plugin directory to:

```text
/home/deck/homebrew/plugins/DeckMicToggle/
```

Then restart Decky Loader or reload the plugin.

## Development

The frontend uses TypeScript/React with `@decky/api` and `@decky/ui`. The backend is Python and uses `pactl` to control the PipeWire/PulseAudio source.

Build the frontend with:

```bash
pnpm install
pnpm run build
```

The compiled frontend is written to:

```text
dist/index.js
```

## Licence

MIT License.
