export const CRT_SHADER = `
  uniform sampler2D colorTexture;
  in vec2 v_textureCoordinates;

  void main(void) {
    vec2 uv = v_textureCoordinates;

    // Barrel distortion (CRT curvature)
    vec2 centered = uv - 0.5;
    float r2 = dot(centered, centered);
    uv = uv + centered * r2 * 0.15;

    vec4 color = texture(colorTexture, uv);

    // Scanlines
    float scanline = sin(uv.y * 800.0) * 0.08;
    color.rgb -= scanline;

    // Phosphor glow (slight RGB offset)
    float r = texture(colorTexture, uv + vec2(0.001, 0.0)).r;
    float g = texture(colorTexture, uv).g;
    float b = texture(colorTexture, uv - vec2(0.001, 0.0)).b;
    color.rgb = mix(color.rgb, vec3(r, g, b), 0.5);

    // Green tint
    color.rgb *= vec3(0.85, 1.0, 0.85);

    // Vignette
    float vignette = 1.0 - r2 * 2.0;
    color.rgb *= clamp(vignette, 0.3, 1.0);

    // Brightness boost
    color.rgb *= 1.1;

    out_FragColor = color;
  }
`;
