import asyncio
import json
import os
import re
import subprocess
from typing import Any, Dict, List, Optional

import decky


class Plugin:
    """
    Decky backend for muting/unmuting the Steam Deck's built-in microphone.

    SteamOS uses PipeWire's PulseAudio compatibility server for pactl. Decky
    can be launched with an environment that does not contain the user's
    PulseAudio/PipeWire socket variables, so pactl must be pointed explicitly
    at the Steam Deck user's runtime socket.
    """

    SETTINGS_FILE = os.path.join(
        decky.DECKY_PLUGIN_SETTINGS_DIR,
        "settings.json",
    )

    # Steam Deck internal microphones are exposed as ALSA PCI input sources.
    # These patterns intentionally prefer PCI sources over USB/Bluetooth inputs.
    INTERNAL_SOURCE_PATTERNS = (
        re.compile(r"^alsa_input\.pci-.*\.analog-stereo$"),
        re.compile(r"^alsa_input\.pci-.*source$"),
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
        """
        Return an environment that reliably points pactl at SteamOS's
        per-user PipeWire PulseAudio compatibility socket.

        Decky normally runs as the `deck` user (UID 1000), but using UID 1000
        explicitly also handles cases where the parent process has a stripped
        environment.
        """
        environment = os.environ.copy()
        environment["XDG_RUNTIME_DIR"] = "/run/user/1000"
        environment["PULSE_RUNTIME_PATH"] = "/run/user/1000/pulse"
        environment["PULSE_SERVER"] = "unix:/run/user/1000/pulse/native"
        return environment

    def _run_pactl(self, *arguments: str) -> str:
        """
        Run pactl against the Steam Deck user's PipeWire PulseAudio socket.

        No shell is used, so source names are passed as literal arguments.
        """
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

    def _parse_sources(self, output: str) -> List[Dict[str, str]]:
        """
        Parse `pactl list sources short` output.

        Expected format:
            ID NAME DRIVER FORMAT STATE
        """
        sources: List[Dict[str, str]] = []

        for line in output.splitlines():
            line = line.strip()

            if not line:
                continue

            parts = line.split()
            if len(parts) < 2:
                continue

            source_id = parts[0]
            name = parts[1]

            if not source_id.isdigit():
                continue

            sources.append({
                "id": source_id,
                "name": name,
            })

        return sources

    def _looks_like_internal_mic(self, source_name: str) -> bool:
        return any(
            pattern.match(source_name)
            for pattern in self.INTERNAL_SOURCE_PATTERNS
        )

    def _find_internal_microphone(self) -> Optional[str]:
        output = self._run_pactl("list", "sources", "short")
        sources = self._parse_sources(output)

        # Prefer the normal Steam Deck internal ALSA PCI input.
        for source in sources:
            name = source["name"]
            if self._looks_like_internal_mic(name):
                return name

        return None

    def _source_exists(self, source: str) -> bool:
        output = self._run_pactl("list", "sources", "short")
        return any(
            entry["name"] == source
            for entry in self._parse_sources(output)
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
        async with self._lock:
            self._selected_source = None

        return await self.get_status()
