import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { nativeLaunchOptions, validateNativeRuntime, prepareNativeProfile } from './native-browser.mjs';

test('a dedicated profile and configured loopback application URL are required', () => {
  const valid = { ODIN_NATIVE_URL: 'http://127.0.0.1:5173/worldview', ODIN_NATIVE_PROFILE: '/data/odin-native-review' };
  assert.equal(nativeLaunchOptions(valid).url, valid.ODIN_NATIVE_URL);
  assert.equal(nativeLaunchOptions(valid).profile, valid.ODIN_NATIVE_PROFILE);
  for (const url of ['', 'https://example.com', 'file:///etc/passwd', 'http://user:password@127.0.0.1:5173']) {
    assert.throws(() => nativeLaunchOptions({ ...valid, ODIN_NATIVE_URL: url }));
  }
  for (const profile of ['', './profile', '/data', '/']) {
    assert.throws(() => nativeLaunchOptions({ ...valid, ODIN_NATIVE_PROFILE: profile }));
  }
});

test('the native profile cannot silently fall back to OpenGL or software rendering', () => {
  assert.doesNotThrow(() => validateNativeRuntime('156.0.8078.4', 'ANGLE (NVIDIA, Vulkan 1.4.329 (NVIDIA NVIDIA GeForce RTX 5090 (0x00002B85)), NVIDIA)'));
  for (const renderer of ['ANGLE (NVIDIA GeForce RTX 5090, OpenGL ES 3.2)', 'Vulkan SwiftShader', 'ANGLE (AMD, Vulkan 1.4.329)', null]) {
    assert.throws(() => validateNativeRuntime('156.0.8078.4', renderer));
  }
  assert.throws(() => validateNativeRuntime('157.0.0.0', 'NVIDIA GeForce RTX 5090 Vulkan'));
});


test('opening the map preserves unrelated browser profiles', () => {
  const root = mkdtempSync(join(tmpdir(), 'odin-native-profile-'));
  try {
    const foreign = join(root, 'foreign');
    mkdirSync(foreign);
    writeFileSync(join(foreign, 'Preferences'), 'existing user state');
    assert.throws(() => prepareNativeProfile(foreign));
    assert.equal(readFileSync(join(foreign, 'Preferences'), 'utf8'), 'existing user state');
    const own = join(root, 'dedicated');
    prepareNativeProfile(own);
    assert.doesNotThrow(() => prepareNativeProfile(own));
  } finally { rmSync(root, { recursive: true, force: true }); }
});
