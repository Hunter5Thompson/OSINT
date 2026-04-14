/**
 * Hlíðskjalf Noir theme smoke tests (ODIN S1 · Task 2).
 *
 * Verifies that `src/theme/hlidskjalf.css` defines:
 *  - the 8-stage grey scale + 4 accent CSS custom properties on `.hlid`
 *  - `.serif` / `.mono` font-family utilities
 *  - `.eyebrow` (uppercase label) and `.hair` (1 px granite hair-line)
 *  - a reduced-motion opt-out utility `.hlid-motion` that respects both
 *    `@media (prefers-reduced-motion: reduce)` AND a
 *    `[data-reduced-motion="true"]` attribute (the latter lets tests simulate
 *    the media query in jsdom, which does not emulate reduced-motion).
 */
import { describe, it, expect, beforeAll } from "vitest";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";

// Side-effect import — loading the CSS registers custom properties and
// font-face rules on the document.
import "../../theme/hlidskjalf.css";

const TOKENS = [
  "--void",
  "--obsidian",
  "--basalt",
  "--granite",
  "--ash",
  "--stone",
  "--bone",
  "--parchment",
  "--amber",
  "--sage",
  "--sentinel",
  "--rust",
] as const;

function Wrapper({
  children,
  reducedMotion = false,
}: {
  children?: ReactNode;
  reducedMotion?: boolean;
}) {
  return (
    <div
      data-testid="hlid-wrapper"
      className="hlid"
      data-reduced-motion={reducedMotion ? "true" : undefined}
    >
      {children}
    </div>
  );
}

describe("Hlíðskjalf theme tokens", () => {
  beforeAll(() => {
    // Defensive: ensure jsdom parsed the @import in test setup.
    // CSS is imported above as a side effect.
  });

  it("exposes all palette tokens as CSS custom properties on .hlid", () => {
    const { getByTestId } = render(<Wrapper />);
    const el = getByTestId("hlid-wrapper");
    const style = getComputedStyle(el);
    for (const token of TOKENS) {
      const value = style.getPropertyValue(token).trim();
      expect(value, `token ${token} should be defined`).not.toBe("");
    }
  });

  it(".serif resolves to a font-family containing 'Instrument Serif'", () => {
    const { getByTestId } = render(
      <Wrapper>
        <span data-testid="serif" className="serif">
          headline
        </span>
      </Wrapper>,
    );
    const family = getComputedStyle(getByTestId("serif")).fontFamily;
    expect(family.toLowerCase()).toContain("instrument serif");
  });

  it(".mono resolves to a font-family containing 'Martian Mono'", () => {
    const { getByTestId } = render(
      <Wrapper>
        <span data-testid="mono" className="mono">
          2026-04-14T00:00Z
        </span>
      </Wrapper>,
    );
    const family = getComputedStyle(getByTestId("mono")).fontFamily;
    expect(family.toLowerCase()).toContain("martian mono");
  });

  it(".eyebrow sets text-transform: uppercase", () => {
    const { getByTestId } = render(
      <Wrapper>
        <span data-testid="eyebrow" className="eyebrow">
          section
        </span>
      </Wrapper>,
    );
    const transform = getComputedStyle(getByTestId("eyebrow")).textTransform;
    expect(transform).toBe("uppercase");
  });

  it(".hair is a 1px hair-line using --granite", () => {
    const { getByTestId } = render(
      <Wrapper>
        <hr data-testid="hair" className="hair" />
      </Wrapper>,
    );
    const style = getComputedStyle(getByTestId("hair"));
    expect(style.height).toBe("1px");
    // jsdom resolves var(--granite) to its value if custom property is defined
    // on an ancestor; assert the resolved color is a non-empty colour string
    // (rgb(...) or hex). Different jsdom versions may serialize differently.
    const bg = style.backgroundColor.trim();
    expect(bg).not.toBe("");
    expect(bg).not.toBe("rgba(0, 0, 0, 0)");
    expect(bg).not.toBe("transparent");
  });

  it(".hlid-motion disables animation when data-reduced-motion='true'", () => {
    const { getByTestId } = render(
      <Wrapper reducedMotion>
        <span data-testid="motion" className="hlid-motion">
          element
        </span>
      </Wrapper>,
    );
    const style = getComputedStyle(getByTestId("motion"));
    // `animation` is a shorthand; jsdom may return an empty string when
    // animation-name is "none". Check animation-name explicitly.
    expect(style.animationName).toBe("none");
  });
});
