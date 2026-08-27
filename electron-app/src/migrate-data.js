const fs = require('fs');
const path = require('path');

// Carries settings, bookmarks, connections and recordings across the
// evilSDR -> SpectraSDR rename. The rename changed productName, which moves
// Electron's userData directory, so without this an existing install comes up
// factory-fresh and its recordings are stranded in the old location.
//
// Kept free of electron imports so it can be exercised directly in tests.
function migrateLegacyDataRoot(dataRoot, legacyRoot, log = console) {
  if (fs.existsSync(dataRoot) || !fs.existsSync(legacyRoot)) return false;

  fs.mkdirSync(path.dirname(dataRoot), { recursive: true });
  try {
    fs.renameSync(legacyRoot, dataRoot);
    log.log(`migrated data from ${legacyRoot} to ${dataRoot}`);
    return true;
  } catch (err) {
    // rename() fails across filesystems. Copy instead, and leave the original
    // in place rather than risk a half-moved directory.
    try {
      fs.cpSync(legacyRoot, dataRoot, { recursive: true });
      log.log(`copied data from ${legacyRoot} to ${dataRoot}`);
      return true;
    } catch (copyErr) {
      log.error(`could not migrate ${legacyRoot}: ${copyErr.message}`);
      return false;
    }
  }
}

// userData is <appData>/<productName>, so swapping the final segment for the
// old productName reconstructs the pre-rename location on every platform.
function legacyDataRootFor(userDataPath) {
  return path.join(path.dirname(userDataPath), 'evilsdr-electron', 'evilSDR');
}

module.exports = { migrateLegacyDataRoot, legacyDataRootFor };
