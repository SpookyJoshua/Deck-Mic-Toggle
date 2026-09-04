import asyncio
import json
import os
import re
import subprocess
from typing import Any, Dict, List, Optional

import decky


class Plugin:
    """Decky backend for muting/unmuting the Steam Deck's internal microphone."""

    SETTINGS_FILE = os.path.join(
        decky.DECKY_PLUGIN_SETTINGS_DIR,
        "settings.json",
    )

    # Steam Deck models expose their internal microphone through different
    # ALSA/UCM device names. In particular, OLED devices commonly expose a
    # nau8821 source that does NOT end in .analog-stereo.
    INTERNAL_NAME_PATTERNS = (
        re.compile(r"^alsa_input\.pci-.*source$", re.IGNORECASE),
        re.compile(r"^alsa_input\.pci-.*\.analog-stereo$", re.IGNORECASE),
    )

    INTERNAL_DESCRIPTION_TERMS = (
        "internal microphone",
        "internal mic",
        "headset microphone + internal microphone",
        "headset mic + internal microphone",
    )

    INTERNAL_DEVICE_TERMS = (
        "nau8821",
        "acp5x",
        "acp3x",
        "acp6x",
        "acp_mach",
    )

    def __init__(self) -> None:
        self._selected_source: Optional[str] = None
        self._lock = asyncio.Lock()

    async def _main(self) -> None:
        decky.logger.info("Deck Mic Toggle starting")
        self._selected_source = self._load_selected_source()

    async def _unload(self) -> None:
        decky.logger.info("Deck Mic Toggle unloading")

    async def _uninstall(self) -> None:
        decky.logger.info("Deck Mic Toggle uninstalling")

    def _load_selected_source(self) -> Optional[str]:
        try:
            if not os.path.exists(self.SETTINGS_FILE):
                return None

            with open(self.SETTINGS_FILE, "r", encoding="utf-8") as file:
                data = json.load(file)

            source = data.get("selected_source")
            return source if isinstance(source, str) and source else None
        except Exception as exc:
            decky.logger.warning(f"Could not load settings: {exc}")
            return None

    def _save_selected_source(self, source: str) -> None:
        try:
            os.makedirs(os.path.dirname(self.SETTINGS_FILE), exist_ok=True)

            with open(self.SETTINGS_FILE, "w", encoding="utf-8") as file:
                json.dump({"selected_source": source}, file, indent=2)
        except Exception as exc:
            decky.logger.warning(f"Could not save settings: {exc}")

    def _pactl_environment(self) -> Dict[str, str]:
        """Build a PipeWire PulseAudio environment for the Deck user."""
        environment = os.environ.copy()

        # Decky normally runs as the deck user. Derive the UID where possible
        # rather than assuming a particular username, while retaining 1000 as
        # the normal Steam Deck fallback.
        uid = str(os.getuid())
        if uid == "0":
            uid = "1000"

        runtime_dir = f"/run/user/{uid}"
        environment["XDG_RUNTIME_DIR"] = runtime_dir
        environment["PULSE_RUNTIME_PATH"] = f"{runtime_dir}/pulse"
        environment["PULSE_SERVER"] = f"unix:{runtime_dir}/pulse/native"

        return environment

    def _run_pactl(self, *arguments: str) -> str:
        """Run pactl without invoking a shell."""
        result = subprocess.run(
            ["pactl", *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=5,
            env=self._pactl_environment(),
        )

        if result.returncode != 0:
            error = result.stderr.strip() or "pactl returned a non-zero exit code"
            raise RuntimeError(error)

        return result.stdout

    def _parse_sources_short(self, output: str) -> List[Dict[str, str]]:
        """Parse `pactl list sources short` output."""
        sources: List[Dict[str, str]] = []

        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue

            parts = line.split()
            if len(parts) < 2 or not parts[0].isdigit():
                continue

            sources.append({
                "id": parts[0],
                "name": parts[1],
            })

        return sources

    def _parse_sources_json(self, output: str) -> List[Dict[str, Any]]:
        """Parse PipeWire's PulseAudio-compatible JSON source listing."""
        try:
            data = json.loads(output)
        except json.JSONDecodeError as exc:
            decky.logger.warning(f"Could not parse pactl JSON: {exc}")
            return []

        if isinstance(data, dict):
            items = data.get("sources", [])
        else:
            items = []

        return items if isinstance(items, list) else []

    def _looks_like_internal_mic(self, source: Dict[str, Any]) -> bool:
        name = str(source.get("name", ""))
        description = str(source.get("description", ""))
        properties = source.get("properties", {})

        if not isinstance(properties, dict):
            properties = {}

        device_name = str(properties.get("device.name", ""))
        device_description = str(properties.get("device.description", ""))
        media_class = str(properties.get("media.class", ""))

        combined = " ".join(
            value.lower()
            for value in (
                name,
                description,
                device_name,
                device_description,
            )
        )

        # Never select a monitor source: it represents output audio, not a mic.
        if "monitor" in name.lower() or "monitor" in media_class.lower():
            return False

        # The strongest signal is an explicit description containing
        # "Internal Microphone". This covers both OLED and LCD configurations.
        if any(term in combined for term in self.INTERNAL_DESCRIPTION_TERMS):
            return True

        # The Steam Deck's physical internal mic source is an ALSA PCI input.
        if self.INTERNAL_NAME_PATTERNS[0].match(name) or self.INTERNAL_NAME_PATTERNS[1].match(name):
            if any(term in combined for term in self.INTERNAL_DEVICE_TERMS):
                return True

        return False

    def _find_internal_microphone(self) -> Optional[str]:
        # Use JSON because it exposes the human-readable source/device
        # descriptions that distinguish the Deck's internal mic from other
        # inputs and virtual PipeWire sources.
        try:
            output = self._run_pactl("-f", "json", "list", "sources")
            sources = self._parse_sources_json(output)

            for source in sources:
                if self._looks_like_internal_mic(source):
                    name = source.get("name")
                    if isinstance(name, str) and name:
                        decky.logger.info(
                            f"Detected Steam Deck internal microphone: {name}"
                        )
                        return name
        except Exception as exc:
            decky.logger.warning(f"JSON microphone detection failed: {exc}")

        # Fallback for older pactl builds without JSON support.
        output = self._run_pactl("list", "sources", "short")
        sources = self._parse_sources_short(output)

        for source in sources:
            name = source["name"]
            if any(pattern.match(name) for pattern in self.INTERNAL_NAME_PATTERNS):
                lowered = name.lower()
                if any(term in lowered for term in self.INTERNAL_DEVICE_TERMS):
                    decky.logger.info(
                        f"Detected Steam Deck internal microphone (fallback): {name}"
                    )
                    return name

        return None

    def _source_exists(self, source: str) -> bool:
        output = self._run_pactl("list", "sources", "short")
        return any(
            entry["name"] == source
            for entry in self._parse_sources_short(output)
        )

    def _get_mute_state(self, source: str) -> bool:
        output = self._run_pactl("get-source-mute", source).strip().lower()

        if output.endswith("yes"):
            return True

        if output.endswith("no"):
            return False

        raise RuntimeError(f"Unexpected pactl mute response: {output}")

    async def get_status(self) -> Dict[str, Any]:
        """Return the current internal microphone and mute state."""
        async with self._lock:
            try:
                source = self._selected_source

                if source is None or not self._source_exists(source):
                    source = self._find_internal_microphone()

                if source is None:
                    return {
                        "success": False,
                        "error": "Could not find the Steam Deck internal microphone.",
                        "source": None,
                        "muted": None,
                    }

                self._selected_source = source
                self._save_selected_source(source)

                muted = self._get_mute_state(source)

                return {
                    "success": True,
                    "error": None,
                    "source": source,
                    "muted": muted,
                }
            except Exception as exc:
                decky.logger.error(f"Failed to get microphone status: {exc}")
                return {
                    "success": False,
                    "error": str(exc),
                    "source": self._selected_source,
                    "muted": None,
                }

    async def set_muted(self, muted: bool) -> Dict[str, Any]:
        """Set the mute state of the Steam Deck's internal microphone."""
        async with self._lock:
            try:
                source = self._selected_source

                if source is None or not self._source_exists(source):
                    source = self._find_internal_microphone()

                if source is None:
                    return {
                        "success": False,
                        "error": "Could not find the Steam Deck internal microphone.",
                        "source": None,
                        "muted": None,
                    }

                self._selected_source = source
                self._save_selected_source(source)

                self._run_pactl(
                    "set-source-mute",
                    source,
                    "1" if muted else "0",
                )

                actual_state = self._get_mute_state(source)

                return {
                    "success": True,
                    "error": None,
                    "source": source,
                    "muted": actual_state,
                }
            except Exception as exc:
                decky.logger.error(f"Failed to set microphone mute: {exc}")
                return {
                    "success": False,
                    "error": str(exc),
                    "source": self._selected_source,
                    "muted": None,
                }

    async def refresh(self) -> Dict[str, Any]:
        """Forget the cached source and detect the internal microphone again."""
        # Do not hold the lock while calling get_status(), because get_status()
        # acquires the same asyncio.Lock.
        async with self._lock:
            self._selected_source = None

        return await self.get_status()
