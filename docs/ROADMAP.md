# SpectraSDR roadmap

This file tracks current engineering gaps. It intentionally avoids phase
numbers and completion dates so it stays useful as priorities change.

## Multi-source runtime

The source abstraction, RTL-TCP adapter, sample-format conversion, and
synthetic source exist under `src/backend/sources/`. The running server still
uses the legacy `RTLTCPClient` directly.

Remaining integration work:

- Construct the selected source driver from connection profiles.
- Route reading, tuning, gain, sample-rate, and disconnect operations through
  `BaseSDRSource`.
- Convert each source's native sample format in the DSP worker.
- Rebuild DSP state from the sample rate actually applied by the device.
- Broadcast capabilities and make the frontend controls device-aware.
- Add the synthetic source as a selectable no-hardware demo path.
- Add native radio drivers only after the common runtime path is stable.

## POCSAG robustness

- Try both discriminator polarities during synchronization.
- Replace the zero threshold with DC-offset-tolerant or adaptive bit slicing.
- Consume decoded input instead of repeatedly scanning the same two-second
  buffer at every supported baud rate.

## Plugin runtime

- Pass source and RF sample-rate metadata to IQ plugins.
- Evict or reload changed Python modules during decoder hot reload.
- Preserve enabled state only after lifecycle teardown has captured it.
- Define when the server invokes each decoder's `reset()` operation.

## Experimental decoders

- Evaluate a low-frame-rate analog TV/ATV path or an external-tool bridge.
- Keep experimental decoders isolated behind the existing plugin lifecycle and
  health-reporting interfaces.
