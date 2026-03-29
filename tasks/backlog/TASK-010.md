# TASK-010: GLSL Post-Processing (CRT / Night Vision / FLIR)

## Service/Modul
services/frontend/src/components/shaders/

## Akzeptanzkriterien
- [x] CRT Shader: Scanlines (horizontal, 2px pitch), vignette, slight barrel distortion, animated sweep line, green phosphor tint, contrast boost
- [x] Night Vision Shader: Green phosphor colorization, noise/grain overlay (procedural), brightness amplification, tube vignette (circular darkening)
- [x] FLIR Shader: Thermal palette mapping (blue→green→yellow→red→white), based on luminance, slight blur for thermal diffusion effect
- [x] Alle 3 als CesiumJS PostProcessStage implementiert
- [x] Shader-Uniforms: u_time (für Animationen), u_intensity (einstellbar)
- [x] UI Toggle: 4 Modi (Standard, CRT, NV, FLIR) über OperationsPanel
- [x] Performance: Framerate-Drop <5% gegenüber Standard-Rendering

## Tests (VOR Implementierung schreiben)
- [x] tests/e2e/test_shader_toggle.spec.ts (Playwright: Mode-Switch ohne Crash)
- [x] Manueller Visueller Test: Screenshots pro Modus für Regression

## Dependencies
- Blocked by: TASK-009 (Globe muss rendern)
- Blocks: -

## Documentation
- Context7: `/cesiumgs/cesium` → "PostProcessStage, CustomShader, GLSL fragment shader"
- CesiumJS PostProcessStage: https://cesium.com/learn/cesiumjs/ref-doc/PostProcessStage.html
- GLSL Reference: https://www.khronos.org/opengl/wiki/Core_Language_(GLSL)
- Referenz-Implementierung: https://github.com/kevtoe/worldview (CRT/NV/FLIR Shaders)

## GLSL Skeleton (Referenz)

```glsl
// CRT PostProcessStage
uniform sampler2D colorTexture;
uniform float u_time;
in vec2 v_textureCoordinates;

void main() {
    vec2 uv = v_textureCoordinates;
    vec4 color = texture(colorTexture, uv);
    
    // Scanlines
    float scanline = sin(uv.y * 800.0) * 0.04;
    color.rgb -= scanline;
    
    // Vignette
    float vig = length(uv - 0.5) * 1.4;
    color.rgb *= 1.0 - vig * vig;
    
    // Green phosphor tint
    color.rgb = vec3(color.r * 0.3, color.g * 1.0, color.b * 0.3);
    
    // Animated sweep
    float sweep = smoothstep(0.0, 0.02, abs(uv.y - fract(u_time * 0.1)));
    color.rgb += (1.0 - sweep) * 0.05;
    
    out_FragColor = color;
}
```

## Session-Notes
(noch keine Sessions)
