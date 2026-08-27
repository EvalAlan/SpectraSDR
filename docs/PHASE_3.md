# Phase 3: Advanced Features & Decoders

**Goal:** Extend functionality beyond basic audio to specialized signal decoding (ADSB, TV) and complete the scanning capabilities.

## 1. Advanced Decoders
### ADSB (Automatic Dependent Surveillance–Broadcast)
- **Status**: Implemented (external integration).
- **Implementation**: `src/backend/decoders/adsb_wrapper.py` spawns `dump1090`
  via `SPECTRASDR_DUMP1090_CMD`, reads its output on a background thread, and
  normalizes AVR / SBS-1 / dump1090-JSON lines into aircraft events.
- **Frontend**: aircraft list panel + `/api/adsb`. Map UI still deferred.
- **To Do**: map UI; richer position/track handling.

### TV (Analog / ATV)
- **Status**: Planned.
- **Challenge**: real-time PAL/NTSC demod is CPU intensive.
- **Approach**: low-framerate snapshots or external tool bridge.

### POCSAG (Pager)
- **Status**: Implemented.
- **Implemented**:
  - Stronger bit slicing + duplicate suppression.
  - Full BCH(31,21) capability: corrects **up to 2 bit errors** per codeword via
    a precomputed syndrome table (496 patterns, collision-free).
  - Parity cross-check rejects corrections implying more than 2 total errors,
    which eliminates 3-bit-error miscorrections (was ~38%, now 0%).
  - Error correction runs *before* IDLE classification, so a repairable hit on
    an IDLE separator no longer latches a phantom address.
  - Known-good fixtures in `tests/test_pocsag_bch.py`, anchored on the
    spec-defined SYNC/IDLE constants plus exhaustive 1- and 2-bit error sweeps.
- **To Do**: inverted-polarity search and DC-offset-tolerant slicing (see below).

## 2. Scanning
- **Frequency Scanning**: implemented (range + bookmarks).
- **Signal Hit Logging**: implemented via SQLite (`scan_hits.sqlite3`).
- **Frontend History**: implemented (mode filter + refresh panel).
- **Time-range filtering + CSV export**: implemented
  (`since_ts`/`until_ts`, `/api/scan_hits/export.csv`).

## 3. Plugin Architecture
- **Status**: Implemented.
- **Implemented**:
  - Auto-discovery from `src/backend/decoders`.
  - Decoder lifecycle hooks (`on_enable`, `on_disable`).
  - Generic decoder event broadcast path.
  - Plugin status surfaced in the UI.

## 4. Current Task Board
- [x] Scanner range sweep
- [x] Connection profile persistence flow
- [x] Scanner hit database logging
- [x] Frontend scan hit panel
- [x] Scan history time-range filters + CSV export
- [x] ADS-B wrapper scaffold
- [x] Full dump1090 subprocess integration
- [x] POCSAG BCH 2-bit correction + known-good fixtures
- [ ] ADS-B map UI
- [ ] POCSAG inverted-polarity + DC-offset-tolerant bit slicing
- [ ] TV/ATV R&D

## 5. Known Gaps

Carried into Phase 4 rather than fixed here:

- **POCSAG polarity**: only one FM discriminator polarity is tried, so an
  inverted receive path decodes nothing. Real decoders sweep both.
- **POCSAG bit slicing**: the slicer thresholds at zero
  (`np.mean(...) > 0`), which assumes a DC-free demod output. Frequency error
  puts a DC offset on the signal and breaks slicing.
- **Sync search cost**: `_try_decode_baud` re-scans the whole 2-second buffer
  for all three baud rates on every audio chunk and never consumes what it
  decoded; duplicate suppression hides the repeated work.
