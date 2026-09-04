import asyncio
import json
import os
import re
import subprocess
from typing import Any, Dict, List, Optional

import decky


class Plugin:
    VERSION = "1.0.3"

    SETTINGS_FILE = os.path.join(
        decky.DECKY_PLUGIN_SETTINGS_DIR,
        "settings.json",
    )

    def __init__(self) -> None:
        self._selected_source: Optional[str] = None
        self._lock = asyncio.Lock()

    async def _main(self) -> None:
        decky.logger.info(f"Deck Mic Toggle v{self.VERSION} starting")
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
        environment = os.environ.copy()
        runtime_dir = environment.get("XDG_RUNTIME_DIR", "/run/user/1000")
        pulse_runtime = os.path.join(runtime_dir, "pulse")

        environment["XDG_RUNTIME_DIR"] = runtime_dir
        environment["PULSE_RUNTIME_PATH"] = pulse_runtime

        # If the normal socket exists, explicitly select it. Otherwise let
        # libpulse perform its normal per-user discovery.
        native_socket = os.path.join(pulse_runtime, "native")
        if os.path.exists(native_socket):
            environment["PULSE_SERVER"] = f"unix:{native_socket}"
        else:
            environment.pop("PULSE_SERVER", None)

        return environment

    def _run_pactl(self, *arguments: str) -> str:
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
        sources: List[Dict[str, str]] = []
        for line in output.splitlines():
            parts = line.strip().split()
            if len(parts) < 2 or not parts[0].isdigit():
                continue
            sources.append({"id": parts[0], "name": parts[1]})
        return sources

    def _source_is_candidate(self, name: str) -> bool:
        lower = name.lower()
        if "monitor" in lower:
            return False
        return (
            lower.startswith("alsa_input.")
            or lower.startswith("alsa_input_")
            or "input" in lower
        )

    def _candidate_score(self, name: str) -> int:
        lower = name.lower()
        score = 0

        # Strong indicators for the Steam Deck's internal microphone.
        for keyword, points in (
            ("nau8821", 100),
            ("sof", 60),
            ("pci-", 40),
            ("platform-", 30),
            ("internal", 80),
            ("built-in", 80),
            ("analog", 20),
        ):
            if keyword in lower:
                score += points

        # External devices are deliberately deprioritised.
        for keyword, points in (
            ("usb", -100),
            ("bluez", -100),
            ("bluetooth", -100),
            ("headset", -60),
        ):
            if keyword in lower:
                score += points

        return score

    def _find_internal_microphone(self) -> Optional[str]:
        output = self._run_pactl("list", "sources", "short")
        sources = self._parse_sources(output)

        candidates = [
            source["name"]
            for source in sources
            if self._source_is_candidate(source["name"])
        ]

        if not candidates:
            decky.logger.error(
                "No microphone candidates found. pactl sources: " + output.strip()
            )
            return None

        candidates.sort(key=self._candidate_score, reverse=True)
        selected = candidates[0]

        decky.logger.info(
            f"Microphone candidates: {candidates}; selected: {selected}"
        )
        return selected

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
        async with self._lock:
            try:
                source = self._selected_source
                if source is None or not self._source_exists(source):
                    source = self._find_internal_microphone()

                if source is None:
                    return {
                        "success": False,
                        "error": "Could not find a microphone input. Open Re-detect Microphone and check Decky logs for the available sources.",
                        "source": None,
                        "muted": None,
                        "version": self.VERSION,
                    }

                self._selected_source = source
                self._save_selected_source(source)
                muted = self._get_mute_state(source)

                return {
                    "success": True,
                    "error": None,
                    "source": source,
                    "muted": muted,
                    "version": self.VERSION,
                }
            except Exception as exc:
                decky.logger.error(f"Failed to get microphone status: {exc}")
                return {
                    "success": False,
                    "error": str(exc),
                    "source": self._selected_source,
                    "muted": None,
                    "version": self.VERSION,
                }

    async def set_muted(self, muted: bool) -> Dict[str, Any]:
        async with self._lock:
            try:
                source = self._selected_source
                if source is None or not self._source_exists(source):
                    source = self._find_internal_microphone()

                if source is None:
                    return {
                        "success": False,
                        "error": "Could not find a microphone input.",
                        "source": None,
                        "muted": None,
                        "version": self.VERSION,
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
                    "version": self.VERSION,
                }
            except Exception as exc:
                decky.logger.error(f"Failed to set microphone mute: {exc}")
                return {
                    "success": False,
                    "error": str(exc),
                    "source": self._selected_source,
                    "muted": None,
                    "version": self.VERSION,
                }

    async def refresh(self) -> Dict[str, Any]:
        async with self._lock:
            self._selected_source = None
        return await self.get_status()
