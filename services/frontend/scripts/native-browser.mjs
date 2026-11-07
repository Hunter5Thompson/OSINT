import { readFileSync, readdirSync, existsSync, lstatSync, mkdirSync, writeFileSync } from 'node:fs';
import { isAbsolute, dirname, normalize, join } from 'node:path';

export const nativeProfile = JSON.parse(readFileSync(new URL('./native-browser-profile.json', import.meta.url), 'utf8'));

export function nativeLaunchOptions(env) {
  const url = new URL(env.ODIN_NATIVE_URL ?? '');
  if (!['http:', 'https:'].includes(url.protocol) || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
    || url.username || url.password) throw new Error('ODIN_NATIVE_URL must be a configured loopback HTTP(S) URL without credentials');
  const profile = env.ODIN_NATIVE_PROFILE ?? '';
  if (!isAbsolute(profile) || dirname(normalize(profile)) === '/' || normalize(profile) === '/') {
    throw new Error('ODIN_NATIVE_PROFILE must name an absolute dedicated profile directory');
  }
  return { url: url.href, profile, args: [...nativeProfile.args] };
}

export function validateNativeRuntime(version, renderer) {
  if (version !== nativeProfile.chromiumVersion || typeof renderer !== 'string'
    || !nativeProfile.rendererTokens.every(token => renderer.includes(token))) {
    throw new Error('Unqualified native browser/renderer; requalify before changing the pinned profile');
  }
}

export function prepareNativeProfile(profile) {
  const marker = join(profile, '.odin-native-vulkan-profile');
  if (existsSync(profile)) {
    if (!lstatSync(profile).isDirectory() || lstatSync(profile).isSymbolicLink()
      || (readdirSync(profile).length && !existsSync(marker))) {
      throw new Error('Refusing to use an existing non-ODIN browser profile');
    }
  } else mkdirSync(profile, { recursive: true, mode: 0o700 });
  if (!existsSync(marker)) writeFileSync(marker, 'ODIN dedicated native Vulkan browser profile\n', { mode: 0o600, flag: 'wx' });
}
