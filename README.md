# Local Voice Flow

A small Windows dictation utility for personal use. Press a global shortcut to start recording, then press it again to transcribe and paste into the currently focused app.

Audio is held in memory while it is uploaded to OpenAI for transcription. This app has no server, database, or saved recordings.

## Setup

1. Double-click `setup.bat`.
2. Open the newly created `.env` file and set `OPENAI_API_KEY` to your key.
3. Double-click `install_startup.bat` once. It starts the app and makes it launch automatically when you sign in to Windows.

Do not paste your API key into chat or commit `.env` to source control.

### Another Windows PC

1. Install Python 3.11 or newer and Git.
2. Clone this repository.
3. Double-click `setup.bat`.
4. Add that computer's OpenAI API key to its local `.env` file.
5. Leave `MICROPHONE` blank for automatic selection, or enter part of a preferred microphone name.
6. Double-click `install_startup.bat`.

## Use

1. Put the cursor in any text field.
2. Press `Ctrl+Windows` once and speak.
3. Press `Ctrl+Windows` again to stop and transcribe.
4. Keep the destination text field focused until the transcription is pasted.

Press `Ctrl+Shift+Q` to close the app.

The small microphone icon stays above the bottom-right taskbar. It expands into a live waveform while listening and shows transcription status after release. Right-click it to quit. Use `run.bat` to launch it again without a console window. Only one copy can run at a time.

Right-click the icon and choose `Usage & cost` to see locally tracked audio time and estimated API cost. Tracking starts after this feature is installed; the OpenAI dashboard remains the billing source of truth.

The transcription replaces the current clipboard contents.

The app rescans microphones every time recording starts. It prefers the named `MICROPHONE` in `.env`, then another available external input, and otherwise uses the Realtek laptop microphone array. If one Windows audio endpoint fails, it tries the microphone's other DirectSound, WASAPI, and MME endpoints before falling back to the laptop. Reconnecting a headset does not require an app restart.

Transcription uses `gpt-4o-mini-transcribe` with English fixed. The OpenAI connection begins warming when recording starts and is reused between dictations. Only leading and trailing silence are removed before upload; speech is not rewritten or passed through a separate cleanup model.

The resident process is required to detect a global shortcut. Between dictations it keeps only the small UI and hotkey listener active. The microphone closes immediately after recording stops. The OpenAI connection is created on first use and retained to reduce later latency. Double-click `remove_startup.bat` if you no longer want it to launch when signing in.

## Privacy and cost

Recordings are sent directly from this computer to OpenAI's transcription API. API usage is billed to the OpenAI account associated with the key. Review OpenAI's current API pricing and data policies before use.
