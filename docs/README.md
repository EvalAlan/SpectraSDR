# SpectraSDR documentation

Start with the repository [README](../README.md) for installation, basic
configuration, and common development commands.

## Current documentation

- [Architecture](ARCHITECTURE.md) — runtime components, data flow, concurrency,
  persistence, and network interfaces.
- [Roadmap](ROADMAP.md) — current limitations and planned engineering work.
- [Runbook](RUNBOOK.md) — smoke tests, environment overrides, migration notes,
  ADS-B setup, and AppImage verification.
- [Plugin authoring guide](PLUGIN_AUTHORING.md) — tutorial for building and
  testing a decoder.
- [Plugin interface](PLUGIN_INTERFACE.md) — concise decoder API and WebSocket
  protocol reference.
- [Electron shell](../electron-app/README.md) — desktop development and Linux
  packaging.

The thread-safety change record in
[`src/backend/THREAD_SAFETY.md`](../src/backend/THREAD_SAFETY.md) is also a
historical implementation note.
