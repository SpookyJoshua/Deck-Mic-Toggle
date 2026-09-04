# Deck Mic Toggle

A small Decky Loader plugin that adds a Quick Access Menu control for the
Steam Deck's built-in microphone.

## What it does

The plugin:

- Detects the Steam Deck's internal microphone.
- Uses `pactl set-source-mute` to mute/unmute it.
- Does not disable the audio hardware or modify SteamOS system files.
- Does not require sudo at runtime.
- Does not change speaker/headphone output.
- Re-detects the microphone if the PipeWire source changes.
- Stores the detected source name in Decky plugin settings.

## Important behaviour

This plugin mutes the microphone rather than removing the device from
PipeWire/WirePlumber.

That is intentional. It is much less invasive and avoids the problems that
can happen when the Steam Deck internal audio node is disabled completely.

## Build

Requirements:

- Steam Deck or another Linux development machine
- Node.js
- pnpm 9

From the plugin directory:

```bash
pnpm install
pnpm run build
```

The compiled frontend is written to:

```text
dist/index.js
```

## Install on the Steam Deck

The easiest development method is to copy the whole plugin directory to:

```text
/home/deck/homebrew/plugins/DeckMicToggle/
```

The directory should contain at least:

```text
DeckMicToggle/
├── dist/
│   └── index.js
├── main.py
├── package.json
├── plugin.json
└── README.md
```

Then restart Decky Loader or reload the plugin from the Decky menu.

## Test the microphone manually

In Desktop Mode, you can inspect sources with:

```bash
pactl list sources short
```

The Steam Deck internal microphone normally has an `alsa_input.pci-...`
source name.

You can inspect its mute state with:

```bash
pactl get-source-mute <source-name>
```

And manually change it with:

```bash
pactl set-source-mute <source-name> 1
```

or:

```bash
pactl set-source-mute <source-name> 0
```

## License

MIT.
