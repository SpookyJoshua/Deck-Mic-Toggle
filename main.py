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

    We deliberately use pactl's source mute operation instead of disabling the
    kernel device. This keeps the audio hardware intact and only changes the
    microphone's current PipeWire/PulseAudio mute state.
    """

    SETTINGS_FILE = os.path.join(
        decky.DECKY_PLUGIN_SETTINGS_DIR,
        "settings.json",
    )

    # Steam Deck internal microphones normally appear as an ALSA PCI source.
    # We require "pci" + "input" and prefer the known Deck audio naming.
    INTERNAL_SOURCE_PATTERNS = (
        re.compile(r"^alsa_input\.pci-.*\.analog-stereo$"),
        re.compile(r"^alsa_input\.pci-.*acp5x.*source$"),
        re.compile(r"^alsa_input\.pci-.*HiFi__Mic__source$"),
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

    def _run_pactl(self, *arguments: str) -> str:
        """
        Run pactl without invoking a shell.

        This avoids shell interpretation and means source names are passed as
        literal arguments.
        """
        result = subprocess.run(
            ["pactl", *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=5,
        )

        if result.returncode != 0:
            error = result.stderr.strip() or "pactl returned a non-zero exit code"
            raise RuntimeError(error)

        return result.stdout

    def _parse_sources(self, output: str) -> List[Dict[str, str]]:
        """
        Parse:
            pactl list sources short

        Expected format:
            ID NAME DRIVER FORMAT STATE

        The NAME field is the second whitespace-delimited field.
        """
        sources: List[Dict[str, str]] = []

        for line in output.splitlines():
            line = line.strip()

            if not line:
                continue

            parts = line.split()
            if len(parts) < 2:
                continue

            try:
                source_id = parts[0]
                name = parts[1]
            except IndexError:
                continue

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

        # First pass: known Steam Deck internal ALSA/PCI source patterns.
        for source in sources:
            if self._looks_like_internal_mic(source["name"]):
                return source["name"]

        # Second pass: the source used by recent Steam Deck PipeWire setups.
        for source in sources:
            name = source["name"].lower()
            if (
                name.startswith("alsa_input.pci-")
                and "input" in name
                and "monitor" not in name
            ):
                return source["name"]

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
        """
        Return the current internal microphone and mute state.
        """
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
        """
        Set the mute state of the Steam Deck's internal microphone.
        """
        async with self._lock:
            try:
                source = self._selected_source

                if source is None or not self._source_exists(source):
                    source = self._find_internal_microphone()

                if source is None:
                    return {
                        "success": False,
                        "error": "Could not find the Steam Deck internal microphone.",
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
                    "muted": None,
                }

    async def refresh(self) -> Dict[str, Any]:
        """
        Forget the cached source and detect the internal microphone again.
        """
        async with self._lock:
            self._selected_source = None

        return await self.get_status()
