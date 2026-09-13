# Project Context

This document preserves the useful product and engineering context behind Local Voice Flow without including private chat transcripts, credentials, machine logs, or API keys.

## Goal

Build a small personal Windows voice-to-text utility inspired by Wispr Flow. It should remain unobtrusive, work in any focused text field, select an available microphone automatically, transcribe English quickly, and require minimal idle resources.

## Current Experience

- A compact always-on-top voice mark sits above the bottom-right taskbar.
- Press `Ctrl+Windows` once to begin recording.
- Press `Ctrl+Windows` again to stop, transcribe, and paste.
- Listening displays a live waveform based on microphone amplitude.
- Transcription displays a spinner, then a brief success or error state.
- Right-click the overlay for usage/cost information or to quit.
- `Ctrl+Shift+Q` also quits.
- The app starts automatically at Windows sign-in after `install_startup.bat` is run.

## Architecture

- `app.py` owns keyboard handling, microphone selection, recording, silence trimming, OpenAI transcription, clipboard paste, metrics, and single-instance enforcement.
- `overlay.py` owns the transparent Tkinter overlay and its visual states.
- Audio is mono 16-bit PCM at the selected device's native sample rate.
- Recordings remain in memory and are encoded as WAV before upload.
- Only leading and trailing silence are trimmed. There is no filler removal, rewriting, or second cleanup model.
- Transcription is fixed to English using `gpt-4o-mini-transcribe`.
- The OpenAI client starts warming when recording begins and is reused across dictations.

## Microphone Behavior

Devices are rescanned before every recording because Windows device IDs change when hardware is connected or removed.

Selection order:

1. The microphone name configured in local `.env`.
2. Another detected external microphone.
3. The Realtek laptop microphone array.
4. The current Windows/PortAudio default input.

For the same physical microphone, the app tries DirectSound, WASAPI, and MME endpoints. If external endpoints fail, it continues to the laptop microphone. This handles headset disconnection, reconnection, and transient Windows driver failures.

## Shortcut Safety

The `keyboard` package's suppressed modifier-only hotkey registration blocked unrelated Windows shortcuts during an early iteration. The current implementation uses a selective blocking hook: it consumes only a Windows-key event when Ctrl is already held. Normal shortcuts such as `Win+A`, `Win+E`, and `Win+Space` pass through to Windows.

## Performance

Measured on the original development laptop:

- Combined idle working set after optimization: approximately 47 MB.
- Idle CPU: approximately 0.6% of one CPU core in a five-second sample.
- Cold OpenAI metadata request: approximately 1,380 ms.
- Reused connection request: approximately 541 ms.

OpenAI is imported lazily on first recording. The static overlay does not continuously repaint. The microphone stream exists only during recording.

## Pricing And Metrics

The configured model's published estimated rate was `$0.003/minute` when implemented. Actual billing can change and must be verified in the OpenAI dashboard.

Successful usage is stored locally in ignored `usage.json`. It tracks request count, submitted audio duration, and estimated cost. Earlier usage before metrics were added cannot be reconstructed exactly.

## Local-Only Files

These files and directories must never be committed:

- `.env`
- `.venv/`
- `voice-flow.log`
- `usage.json`
- `__pycache__/`

## Known Constraints

- Internet access and a funded OpenAI API account are required.
- The focused destination must remain active until paste occurs.
- The transcription temporarily replaces the clipboard contents.
- A tiny resident process is required for the global shortcut; the application cannot be fully stopped and still respond to a shortcut.
- The current pipeline uploads after recording stops. Realtime streaming could reduce latency further but would increase complexity and API cost.
