from __future__ import annotations

import ctypes
import io
import json
import logging
import math
import os
import sys
import threading
import time
import wave
from array import array
from collections.abc import Callable
from pathlib import Path

import keyboard
import pyperclip
import sounddevice as sd
from dotenv import load_dotenv

from overlay import VoiceOverlay


CHANNELS = 1
SAMPLE_WIDTH = 2
MIN_RECORDING_SECONDS = 0.25
SILENCE_RMS_THRESHOLD = 180
SILENCE_PADDING_SECONDS = 0.12
TRANSCRIPTION_MODEL = "gpt-4o-mini-transcribe"
TRANSCRIPTION_LANGUAGE = "en"
INPUT_TOKEN_PRICE = 1.25 / 1_000_000
OUTPUT_TOKEN_PRICE = 5.00 / 1_000_000
ESTIMATED_MINUTE_PRICE = 0.003
WINDOWS_KEYS = {"windows", "left windows", "right windows"}

_mutex_handle = None


def acquire_single_instance() -> bool:
    global _mutex_handle
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, "Local\\LocalVoiceFlow")
    if not handle:
        return False
    if kernel32.GetLastError() == 183:
        kernel32.CloseHandle(handle)
        return False
    _mutex_handle = handle
    return True


class UsageTracker:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.data = {
            "requests": 0,
            "audio_seconds": 0.0,
            "estimated_cost_usd": 0.0,
        }
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.data.update(loaded)
        except FileNotFoundError:
            pass
        except Exception:
            logging.exception("Could not read usage metrics")

    def record(self, duration: float, usage) -> None:
        cost = duration / 60 * ESTIMATED_MINUTE_PRICE
        if getattr(usage, "type", None) == "tokens":
            cost = (
                usage.input_tokens * INPUT_TOKEN_PRICE
                + usage.output_tokens * OUTPUT_TOKEN_PRICE
            )

        with self.lock:
            self.data["requests"] += 1
            self.data["audio_seconds"] += duration
            self.data["estimated_cost_usd"] += cost
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def summary(self) -> str:
        with self.lock:
            requests = self.data["requests"]
            minutes = self.data["audio_seconds"] / 60
            cost = self.data["estimated_cost_usd"]
        return (
            f"Model: {TRANSCRIPTION_MODEL}\n"
            f"Language: English\n"
            f"Official estimated rate: ${ESTIMATED_MINUTE_PRICE:.4f} per minute\n\n"
            f"Tracked dictations: {requests}\n"
            f"Tracked audio: {minutes:.2f} minutes\n"
            f"Estimated API cost: ${cost:.6f}\n\n"
            "Metrics are tracked locally from this update onward. "
            "Your OpenAI dashboard is the billing source of truth."
        )


class VoiceFlow:
    def __init__(
        self,
        api_key: str,
        input_device: int,
        input_name: str,
        sample_rate: int,
        preferred_microphone: str,
        status_callback: Callable[[str, str], None],
        level_callback: Callable[[float], None],
        usage_tracker: UsageTracker,
    ):
        self.api_key = api_key
        self.input_device = input_device
        self.input_name = input_name
        self.sample_rate = sample_rate
        self.preferred_microphone = preferred_microphone
        self.status_callback = status_callback
        self.level_callback = level_callback
        self.usage_tracker = usage_tracker
        self.stream: sd.RawInputStream | None = None
        self.frames: list[bytes] = []
        self.recording_started_at = 0.0
        self.recording = False
        self.transcribing = False
        self.hotkey_down = False
        self.lock = threading.Lock()
        self.client = None
        self.client_lock = threading.Lock()
        self.client_ready = threading.Event()
        self.client_warmup: threading.Thread | None = None

    def audio_callback(self, indata, frames, time_info, status) -> None:
        if status:
            logging.warning("Audio warning: %s", status)
        if self.recording:
            chunk = bytes(indata)
            self.frames.append(chunk)
            samples = array("h")
            samples.frombytes(chunk)
            step = max(1, len(samples) // 200)
            sampled = samples[::step]
            if sampled:
                rms = math.sqrt(sum(value * value for value in sampled) / len(sampled))
                self.level_callback(rms / 32768)

    def toggle_recording(self) -> None:
        with self.lock:
            if self.hotkey_down:
                return
            self.hotkey_down = True
            if self.transcribing:
                return
            if self.recording:
                self._stop_recording()
            else:
                self._start_recording()

    def release_hotkey(self) -> None:
        with self.lock:
            self.hotkey_down = False

    def _start_recording(self) -> None:
        self._start_client_warmup()
        try:
            self.frames = []
            failures = []
            for input_device, input_name, sample_rate in input_device_candidates(
                self.preferred_microphone
            ):
                stream = None
                try:
                    stream = sd.RawInputStream(
                        device=input_device,
                        samplerate=sample_rate,
                        channels=CHANNELS,
                        dtype="int16",
                        callback=self.audio_callback,
                    )
                    stream.start()
                except Exception as exc:
                    failures.append(f"{input_name}: {exc}")
                    if stream is not None:
                        try:
                            stream.close()
                        except Exception:
                            pass
                    continue

                if input_device != self.input_device:
                    logging.info("Switched microphone to %s at %s Hz", input_name, sample_rate)
                self.input_device = input_device
                self.input_name = input_name
                self.sample_rate = sample_rate
                self.stream = stream
                break
            else:
                raise RuntimeError("; ".join(failures))
        except Exception as exc:
            stream = self.stream
            self.stream = None
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    logging.exception("Could not close the failed microphone stream")
            logging.exception("Could not start the microphone")
            self.status_callback("error", f"Microphone: {exc}")
            return

        self.recording_started_at = time.monotonic()
        self.recording = True
        self.status_callback("listening", "")

    def _stop_recording(self) -> None:
        self.recording = False
        duration = time.monotonic() - self.recording_started_at
        stream = self.stream
        self.stream = None

        if stream is not None:
            stream.stop()
            stream.close()

        if duration < MIN_RECORDING_SECONDS or not self.frames:
            self.status_callback("idle", "")
            return

        audio = trim_silence(b"".join(self.frames), self.sample_rate)
        self.frames = []
        if not audio:
            self.status_callback("error", "No speech detected")
            return

        upload_duration = len(audio) / (self.sample_rate * SAMPLE_WIDTH * CHANNELS)
        self.transcribing = True
        self.status_callback("transcribing", "")
        threading.Thread(
            target=self._transcribe_and_paste,
            args=(audio, upload_duration),
            daemon=True,
        ).start()

    def _transcribe_and_paste(self, audio: bytes, duration: float) -> None:
        try:
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, "wb") as wav_file:
                wav_file.setnchannels(CHANNELS)
                wav_file.setsampwidth(SAMPLE_WIDTH)
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(audio)

            request: dict[str, object] = {
                "model": TRANSCRIPTION_MODEL,
                "file": ("recording.wav", wav_buffer.getvalue(), "audio/wav"),
                "language": TRANSCRIPTION_LANGUAGE,
            }

            self.client_ready.wait(timeout=10)
            with self.client_lock:
                client = self.client
            if client is None:
                from openai import OpenAI

                client = OpenAI(api_key=self.api_key, timeout=60.0)
                with self.client_lock:
                    self.client = client
            result = client.audio.transcriptions.create(**request)
            self.usage_tracker.record(duration, getattr(result, "usage", None))

            text = result if isinstance(result, str) else result.text
            text = text.strip()
            if not text:
                self.status_callback("error", "No speech detected")
                return

            pyperclip.copy(text)
            keyboard.send("ctrl+v")
            logging.info("Transcription pasted")
            self.status_callback("success", "")
        except Exception as exc:
            logging.exception("Transcription failed")
            self.status_callback("error", str(exc))
        finally:
            with self.lock:
                self.transcribing = False

    def _start_client_warmup(self) -> None:
        with self.client_lock:
            if self.client is not None:
                self.client_ready.set()
                return
            if self.client_warmup is not None and self.client_warmup.is_alive():
                return
            self.client_ready.clear()
            self.client_warmup = threading.Thread(target=self._warm_client, daemon=True)
            self.client_warmup.start()

    def _warm_client(self) -> None:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key, timeout=60.0)
            try:
                client.models.retrieve(TRANSCRIPTION_MODEL)
                logging.info("OpenAI connection warmed")
            except Exception:
                logging.warning("OpenAI connection warm-up failed", exc_info=True)
            with self.client_lock:
                self.client = client
        except Exception:
            logging.exception("Could not create the OpenAI client")
        finally:
            self.client_ready.set()

    def close(self) -> None:
        with self.lock:
            self.recording = False
            if self.stream is not None:
                self.stream.stop()
                self.stream.close()
                self.stream = None
        with self.client_lock:
            client = self.client
            self.client = None
        if client is not None:
            client.close()


def trim_silence(audio: bytes, sample_rate: int) -> bytes:
    samples = array("h")
    samples.frombytes(audio)
    if not samples:
        return b""

    window_size = max(1, sample_rate // 50)
    first_active = None
    last_active = None
    for start in range(0, len(samples), window_size):
        window = samples[start : start + window_size]
        rms = math.sqrt(sum(value * value for value in window) / len(window))
        if rms >= SILENCE_RMS_THRESHOLD:
            if first_active is None:
                first_active = start
            last_active = start + len(window)

    if first_active is None or last_active is None:
        return b""

    padding = int(sample_rate * SILENCE_PADDING_SECONDS)
    first_active = max(0, first_active - padding)
    last_active = min(len(samples), last_active + padding)
    return samples[first_active:last_active].tobytes()


def resolve_input_device(query: str) -> tuple[int, str, int]:
    return input_device_candidates(query)[0]


def input_device_candidates(query: str) -> list[tuple[int, str, int]]:
    devices = list(sd.query_devices())
    input_devices = [device for device in devices if device["max_input_channels"] > 0]
    if not input_devices:
        raise ValueError("No input devices are available")

    host_apis = sd.query_hostapis()
    api_priority = {"Windows DirectSound": 0, "Windows WASAPI": 1, "MME": 2}
    supported_devices = [
        device
        for device in input_devices
        if host_apis[device["hostapi"]]["name"] in api_priority
    ]
    normalized_query = query.casefold()
    preferred_devices = [
        device
        for device in supported_devices
        if normalized_query and normalized_query in device["name"].casefold()
    ]
    built_in_markers = (
        "microphone array",
        "realtek",
        "stereo mix",
        "pc speaker",
        "front panel",
        "microsoft sound mapper",
        "primary sound capture",
    )
    external_devices = [
        device
        for device in supported_devices
        if not any(marker in device["name"].casefold() for marker in built_in_markers)
    ]
    laptop_devices = [
        device
        for device in supported_devices
        if "microphone array" in device["name"].casefold()
    ]
    default_device = sd.query_devices(kind="input")

    ordered = []
    seen = set()
    for group in (preferred_devices, external_devices, laptop_devices, [default_device]):
        for device in sorted(
            group,
            key=lambda item: api_priority.get(host_apis[item["hostapi"]]["name"], 3),
        ):
            if device["index"] not in seen:
                seen.add(device["index"])
                ordered.append(
                    (
                        device["index"],
                        device["name"],
                        int(device["default_samplerate"]),
                    )
                )

    return ordered


def handle_keyboard_event(app: VoiceFlow, event) -> bool:
    if event.name not in WINDOWS_KEYS:
        return True

    if event.event_type == keyboard.KEY_DOWN and keyboard.is_pressed("ctrl"):
        app.toggle_recording()
        return False

    if event.event_type == keyboard.KEY_UP and app.hotkey_down:
        app.release_hotkey()
        return False

    return True


def main() -> int:
    load_dotenv()
    logging.basicConfig(
        filename=Path(__file__).with_name("voice-flow.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if not acquire_single_instance():
        logging.info("Local Voice Flow is already running")
        return 0

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        logging.error("OPENAI_API_KEY is missing")
        ctypes.windll.user32.MessageBoxW(
            None,
            "Add OPENAI_API_KEY to the Local Voice Flow .env file.",
            "Local Voice Flow",
            0x10,
        )
        return 1

    microphone = os.getenv("MICROPHONE", "").strip()

    try:
        input_device, input_name, sample_rate = resolve_input_device(microphone)
    except Exception as exc:
        logging.exception("Could not select the microphone")
        ctypes.windll.user32.MessageBoxW(
            None,
            f"Could not select the microphone:\n\n{exc}",
            "Local Voice Flow",
            0x10,
        )
        return 1

    usage_tracker = UsageTracker(Path(__file__).with_name("usage.json"))
    app: VoiceFlow | None = None

    def close_app() -> None:
        keyboard.unhook_all_hotkeys()
        if app is not None:
            app.close()

    overlay = VoiceOverlay(close_app, usage_tracker.summary)
    app = VoiceFlow(
        api_key,
        input_device,
        input_name,
        sample_rate,
        microphone,
        overlay.set_state,
        overlay.set_audio_level,
        usage_tracker,
    )

    logging.info("Started with microphone %s at %s Hz", input_name, sample_rate)

    keyboard.hook(lambda event: handle_keyboard_event(app, event), suppress=True)
    keyboard.add_hotkey("ctrl+shift+q", overlay.request_quit)
    overlay.run()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
