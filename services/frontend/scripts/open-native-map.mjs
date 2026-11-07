import { chromium } from 'playwright';
import { nativeLaunchOptions, validateNativeRuntime, prepareNativeProfile } from './native-browser.mjs';

const options = nativeLaunchOptions(process.env);
prepareNativeProfile(options.profile);
// A dedicated browser process is required: an existing Chrome process would
// ignore graphics flags passed to a second invocation. Keep normal profiles intact.
const context = await chromium.launchPersistentContext(options.profile, {
  headless: false, channel: 'chromium', args: options.args, viewport: null,
});
try {
  const page = context.pages()[0] ?? await context.newPage();
  const cdp = await context.newCDPSession(page);
  const { product } = await cdp.send('Browser.getVersion');
  await page.setContent('<canvas width="16" height="16"></canvas>');
  const renderer = await page.evaluate(() => {
    const canvas = document.querySelector('canvas');
    const gl = canvas.getContext('webgl2');
    if (!gl) return null;
    const debug = gl.getExtension('WEBGL_debug_renderer_info');
    const renderer = String(gl.getParameter(debug ? debug.UNMASKED_RENDERER_WEBGL : gl.RENDERER));
    gl.getExtension('WEBGL_lose_context')?.loseContext();
    return renderer;
  });
  validateNativeRuntime(product.replace(/^[^/]+\//, ''), renderer);
  console.log(JSON.stringify({ browser: product, renderer, url: options.url }));
  await cdp.detach();
  await page.goto(options.url);
  if (process.argv.includes('--check')) {
    await page.locator('.cesium-widget canvas').waitFor({ timeout: 30000 });
    const appRenderer = await page.evaluate(() => {
      const gl = document.querySelector('.cesium-widget canvas')?.getContext('webgl2');
      if (!gl) return null;
      const debug = gl.getExtension('WEBGL_debug_renderer_info');
      return String(gl.getParameter(debug ? debug.UNMASKED_RENDERER_WEBGL : gl.RENDERER));
    });
    validateNativeRuntime(product.replace(/^[^/]+\//, ''), appRenderer);
    console.log(JSON.stringify({ applicationRenderer: appRenderer, checked: true }));
    await context.close();
  } else await new Promise(resolve => context.once('close', resolve));
} catch (error) {
  await context.close();
  throw error;
}
