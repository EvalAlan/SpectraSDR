const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const { migrateLegacyDataRoot, legacyDataRootFor } = require('../src/migrate-data');

const quiet = { log: () => {}, error: () => {} };

function fresh(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'spectrasdr-mig-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const userData = path.join(root, '.config', 'SpectraSDR');
  return {
    userData,
    dataRoot: path.join(userData, 'SpectraSDR'),
    legacy: legacyDataRootFor(userData)
  };
}

test('legacy root is the old productName beside the new one', t => {
  const { userData, legacy } = fresh(t);
  assert.strictEqual(
    legacy,
    path.join(path.dirname(userData), 'evilsdr-electron', 'evilSDR')
  );
});

test('a pre-rename install keeps its settings and recordings', t => {
  const { dataRoot, legacy } = fresh(t);
  fs.mkdirSync(path.join(legacy, 'recordings'), { recursive: true });
  fs.writeFileSync(path.join(legacy, 'bookmarks.json'), '{"marker":"pre-rename"}');
  fs.writeFileSync(path.join(legacy, 'recordings', 'capture.wav'), 'RIFF-fake');

  assert.strictEqual(migrateLegacyDataRoot(dataRoot, legacy, quiet), true);

  const bookmarks = JSON.parse(fs.readFileSync(path.join(dataRoot, 'bookmarks.json')));
  assert.strictEqual(bookmarks.marker, 'pre-rename');
  assert.ok(fs.existsSync(path.join(dataRoot, 'recordings', 'capture.wav')));
  assert.ok(!fs.existsSync(legacy));
});

test('migrating twice is a no-op rather than a second move', t => {
  const { dataRoot, legacy } = fresh(t);
  fs.mkdirSync(legacy, { recursive: true });
  fs.writeFileSync(path.join(legacy, 'bookmarks.json'), '{"marker":"pre-rename"}');

  assert.strictEqual(migrateLegacyDataRoot(dataRoot, legacy, quiet), true);
  assert.strictEqual(migrateLegacyDataRoot(dataRoot, legacy, quiet), false);
  assert.ok(fs.existsSync(path.join(dataRoot, 'bookmarks.json')));
});

test('an existing SpectraSDR install is never overwritten by a stale one', t => {
  const { dataRoot, legacy } = fresh(t);
  fs.mkdirSync(dataRoot, { recursive: true });
  fs.writeFileSync(path.join(dataRoot, 'bookmarks.json'), '{"marker":"current"}');
  fs.mkdirSync(legacy, { recursive: true });
  fs.writeFileSync(path.join(legacy, 'bookmarks.json'), '{"marker":"stale"}');

  assert.strictEqual(migrateLegacyDataRoot(dataRoot, legacy, quiet), false);

  const bookmarks = JSON.parse(fs.readFileSync(path.join(dataRoot, 'bookmarks.json')));
  assert.strictEqual(bookmarks.marker, 'current');
});

test('a clean install migrates nothing and creates nothing', t => {
  const { dataRoot, legacy } = fresh(t);
  assert.strictEqual(migrateLegacyDataRoot(dataRoot, legacy, quiet), false);
  assert.ok(!fs.existsSync(dataRoot));
});
