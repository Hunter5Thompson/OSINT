export const NIGHT_VISION_SHADER = `
  uniform sampler2D colorTexture;
  in vec2 v_textureCoordinates;

  // Simple hash function for noise
  float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
  }

  void main(void) {
    vec2 uv = v_textureCoordinates;
    vec4 color = texture(colorTexture, uv);

    // Convert to luminance
    float lum = dot(color.rgb, vec3(0.299, 0.587, 0.114));

    // Amplify brightness (night vision amplification)
    lum = pow(lum, 0.6) * 1.5;
    lum = clamp(lum, 0.0, 1.0);

    // Green phosphor color
    vec3 nvColor = vec3(0.1, lum, 0.1);

    // Film grain noise
    float noise = hash(uv * 500.0 + fract(czm_frameNumber * 0.01)) * 0.1;
    nvColor += noise;

    // Scanlines (subtle)
    float scanline = sin(uv.y * 400.0) * 0.03;
    nvColor -= scanline;

    // Vignette (circular, like looking through NV goggles)
    vec2 centered = uv - 0.5;
    float dist = length(centered);
    float vignette = 1.0 - smoothstep(0.35, 0.5, dist);
    nvColor *= vignette;

    // Edge brightness
    nvColor += vec3(0.0, 0.02, 0.0);

    out_FragColor = vec4(nvColor, 1.0);
  }
`;
