export const FLIR_SHADER = `
  uniform sampler2D colorTexture;
  in vec2 v_textureCoordinates;

  vec3 thermalPalette(float t) {
    // Cold (dark blue/purple) → warm (yellow/white)
    vec3 c0 = vec3(0.05, 0.0, 0.15);   // cold: deep purple
    vec3 c1 = vec3(0.0, 0.0, 0.6);     // cool: blue
    vec3 c2 = vec3(0.8, 0.0, 0.4);     // warm: magenta/red
    vec3 c3 = vec3(1.0, 0.8, 0.0);     // hot: yellow
    vec3 c4 = vec3(1.0, 1.0, 1.0);     // hottest: white

    if (t < 0.25) return mix(c0, c1, t * 4.0);
    if (t < 0.5)  return mix(c1, c2, (t - 0.25) * 4.0);
    if (t < 0.75) return mix(c2, c3, (t - 0.5) * 4.0);
    return mix(c3, c4, (t - 0.75) * 4.0);
  }

  void main(void) {
    vec2 uv = v_textureCoordinates;
    vec4 color = texture(colorTexture, uv);

    // Convert to luminance (thermal intensity)
    float thermal = dot(color.rgb, vec3(0.299, 0.587, 0.114));

    // Slight contrast enhancement
    thermal = pow(thermal, 0.9);
    thermal = clamp(thermal, 0.0, 1.0);

    // Apply thermal palette
    vec3 flirColor = thermalPalette(thermal);

    // Slight noise for realism
    float noise = fract(sin(dot(uv * 200.0, vec2(12.9898, 78.233))) * 43758.5453);
    flirColor += (noise - 0.5) * 0.02;

    out_FragColor = vec4(flirColor, 1.0);
  }
`;
