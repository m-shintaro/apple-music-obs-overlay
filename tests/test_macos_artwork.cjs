const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/apple_music_obs_overlay/providers/macos_music.py'), 'utf8')
  .match(/ARTWORK_SCRIPT = r'''([\s\S]*?)'''/)[1];

function run({ title = 'A', id = 'ID-A', afterRead, expectedId = 'ID-A' } = {}) {
  let writes = 0, reads = 0;
  const state = { title, id };
  const artwork = {
    rawData() {
      reads++;
      afterRead?.(state);
      return { length: 42, writeToFileAtomically() { writes++; return true; } };
    }
  };
  // JXA references re-evaluate currentTrack's properties; simulate that here.
  const artworks = () => [artwork];
  artworks[0] = artwork;
  const track = { name: () => state.title, artist: () => 'Artist', album: () => 'Album',
    persistentID: () => state.id, artworks };
  const context = vm.createContext({ ObjC: { import() {} }, $: value => value,
    Application: () => ({ running: () => true, playerState: () => 'playing', currentTrack: () => track }) });
  vm.runInContext(source, context);
  const result = context.run(['/tmp/cover.raw', JSON.stringify({
    title: 'A', artist: 'Artist', album: 'Album', trackId: expectedId
  })]);
  return { result, writes, reads };
}

test('JXA rejects artwork from a different metadata snapshot before reading', () => {
  assert.deepEqual(run({title: 'B'}), {result: 'missing:track_changed', writes: 0, reads: 0});
});
test('JXA rejects a currentTrack reference that changes while reading artwork', () => {
  assert.deepEqual(run({afterRead: state => { state.title = 'B'; }}),
    {result: 'missing:track_changed', writes: 0, reads: 1});
});
test('JXA rejects another persistent ID even when all display metadata match', () => {
  assert.deepEqual(run({id: 'ID-B'}), {result: 'missing:track_changed', writes: 0, reads: 0});
});
test('JXA checks persistent ID again after reading', () => {
  assert.deepEqual(run({afterRead: state => { state.id = 'ID-B'; }}),
    {result: 'missing:track_changed', writes: 0, reads: 1});
});
test('JXA exports matching artwork without changing its NSData', () => {
  assert.deepEqual(run(), {result: 'ok:index.rawData', writes: 1, reads: 1});
});
test('JXA supports tracks whose persistent ID is unavailable', () => {
  assert.deepEqual(run({id: '', expectedId: ''}), {result: 'ok:index.rawData', writes: 1, reads: 1});
});
