import { useEffect, useRef } from "react";
import { geoOrthographic, geoPath, geoGraticule10 } from "d3-geo";
import type { GeoPermissibleObjects } from "d3-geo";
import { feature } from "topojson-client";
import type { Topology } from "topojson-specification";
import type { FeatureCollection } from "geojson";
import "./muninLoader.css";

const NS = "http://www.w3.org/2000/svg";
const TARGET: [number, number] = [51.5, 25.3];
const MARKERS: Array<[number, number]> = [
  [-74, 40],
  [139, 35],
  [-58, -34],
  [37, 55],
  [18, -33],
  [103, 1],
  [-122, 37],
  [77, 28],
];

let cachedLand: FeatureCollection | null = null;
let cachedLandPromise: Promise<FeatureCollection> | null = null;

async function loadLand(): Promise<FeatureCollection> {
  if (cachedLand) return cachedLand;
  if (cachedLandPromise) return cachedLandPromise;
  cachedLandPromise = fetch("/countries-110m.json")
    .then((r) => r.json() as Promise<Topology>)
    .then((topo) => {
      const countries = topo.objects.countries;
      if (!countries) throw new Error("missing countries object");
      cachedLand = feature(topo, countries) as unknown as FeatureCollection;
      return cachedLand;
    });
  return cachedLandPromise;
}

export function MuninLoader() {
  const rootRef = useRef<SVGSVGElement | null>(null);
  const tickRailRef = useRef<SVGGElement | null>(null);
  const graticuleRef = useRef<SVGGElement | null>(null);
  const landStrokeRef = useRef<SVGGElement | null>(null);
  const landFillRef = useRef<SVGGElement | null>(null);
  const markersRef = useRef<SVGGElement | null>(null);
  const targetRef = useRef<SVGGElement | null>(null);
  const targetReticleRef = useRef<SVGGElement | null>(null);
  const targetPulseRef = useRef<SVGCircleElement | null>(null);
  const leaderRef = useRef<SVGPathElement | null>(null);
  const tagBoxRef = useRef<SVGRectElement | null>(null);
  const targetTagRef = useRef<SVGGElement | null>(null);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const rail = tickRailRef.current;
    if (rail) {
      rail.innerHTML = "";
      const railR = 78;
      for (let i = 0; i < 60; i++) {
        const a = (i / 60) * Math.PI * 2;
        const long = i % 5 === 0;
        const r1 = railR;
        const r2 = railR + (long ? 4 : 2);
        const l = document.createElementNS(NS, "line");
        l.setAttribute("x1", String(100 + Math.cos(a) * r1));
        l.setAttribute("y1", String(100 + Math.sin(a) * r1));
        l.setAttribute("x2", String(100 + Math.cos(a) * r2));
        l.setAttribute("y2", String(100 + Math.sin(a) * r2));
        l.setAttribute(
          "stroke",
          long ? "rgba(210,222,232,0.65)" : "rgba(210,222,232,0.30)",
        );
        l.setAttribute("stroke-width", long ? "0.8" : "0.5");
        rail.appendChild(l);
      }
    }

    let cancelled = false;
    void (async () => {
      const land = await loadLand().catch(() => null);
      if (cancelled || !land) return;

      const projection = geoOrthographic()
        .scale(70)
        .translate([100, 100])
        .clipAngle(90)
        .rotate([0, -18, 0]);
      const path = geoPath(projection);
      const graticule = geoGraticule10();

      const graticuleG = graticuleRef.current;
      const landStrokeG = landStrokeRef.current;
      const landFillG = landFillRef.current;
      const markersG = markersRef.current;
      const targetG = targetRef.current;
      if (
        !graticuleG ||
        !landStrokeG ||
        !landFillG ||
        !markersG ||
        !targetG
      ) {
        return;
      }

      graticuleG.innerHTML = "";
      landStrokeG.innerHTML = "";
      landFillG.innerHTML = "";
      markersG.innerHTML = "";

      const gratEl = document.createElementNS(NS, "path");
      graticuleG.appendChild(gratEl);

      const strokeEls: Array<{ feat: GeoPermissibleObjects; el: SVGPathElement }> = [];
      const fillEls: Array<{ feat: GeoPermissibleObjects; el: SVGPathElement }> = [];
      for (const feat of land.features) {
        const s = document.createElementNS(NS, "path");
        landStrokeG.appendChild(s);
        strokeEls.push({ feat: feat as GeoPermissibleObjects, el: s });
        const f = document.createElementNS(NS, "path");
        landFillG.appendChild(f);
        fillEls.push({ feat: feat as GeoPermissibleObjects, el: f });
      }

      const markerEls: SVGRectElement[] = MARKERS.map(() => {
        const r = document.createElementNS(NS, "rect");
        r.setAttribute("width", "3.2");
        r.setAttribute("height", "3.2");
        r.setAttribute("fill", "none");
        r.setAttribute("stroke", "rgba(210,222,232,0.55)");
        r.setAttribute("stroke-width", "0.6");
        markersG.appendChild(r);
        return r;
      });

      let lambda = 0;
      const phi = -18;
      const speed = 18;
      let last = performance.now();

      const frame = (now: number) => {
        if (cancelled) return;
        const dt = Math.min(0.05, (now - last) / 1000);
        last = now;
        lambda = (lambda + speed * dt) % 360;

        projection.rotate([lambda, phi, 0]);
        gratEl.setAttribute("d", path(graticule) ?? "");
        for (const { feat, el } of strokeEls) el.setAttribute("d", path(feat) ?? "");
        for (const { feat, el } of fillEls) el.setAttribute("d", path(feat) ?? "");

        MARKERS.forEach(([lon, lat], i) => {
          const el = markerEls[i];
          if (!el) return;
          const rotLon = lon + lambda;
          const cosC =
            Math.sin((phi * Math.PI) / 180) * Math.sin((lat * Math.PI) / 180) +
            Math.cos((phi * Math.PI) / 180) *
              Math.cos((lat * Math.PI) / 180) *
              Math.cos((rotLon * Math.PI) / 180);
          if (cosC > 0.05) {
            const p = projection([lon, lat]);
            if (p) {
              el.setAttribute("x", String(p[0] - 1.6));
              el.setAttribute("y", String(p[1] - 1.6));
              el.setAttribute("opacity", Math.min(1, cosC * 1.2).toFixed(2));
            }
          } else {
            el.setAttribute("opacity", "0");
          }
        });

        const [tlon, tlat] = TARGET;
        const rotLon = tlon + lambda;
        const cosC =
          Math.sin((phi * Math.PI) / 180) * Math.sin((tlat * Math.PI) / 180) +
          Math.cos((phi * Math.PI) / 180) *
            Math.cos((tlat * Math.PI) / 180) *
            Math.cos((rotLon * Math.PI) / 180);
        if (cosC > 0.02) {
          const p = projection(TARGET);
          const reticle = targetReticleRef.current;
          const pulse = targetPulseRef.current;
          const leader = leaderRef.current;
          const tag = targetTagRef.current;
          const box = tagBoxRef.current;
          if (p && reticle && pulse && leader && tag && box) {
            reticle.setAttribute("transform", `translate(${p[0]} ${p[1]})`);
            pulse.setAttribute("transform", `translate(${p[0]} ${p[1]})`);
            const tagX = 148;
            const tagY = 38;
            leader.setAttribute(
              "d",
              `M ${p[0].toFixed(2)} ${p[1].toFixed(2)} L ${(p[0] + 6).toFixed(2)} ${(p[1] - 6).toFixed(2)} L ${tagX - 2} ${tagY + 2} L ${tagX + 22} ${tagY + 2}`,
            );
            box.setAttribute("x", String(tagX));
            box.setAttribute("y", String(tagY));
            tag.setAttribute("opacity", "1");
            targetG.setAttribute(
              "opacity",
              Math.min(1, cosC * 1.5).toFixed(2),
            );
          }
        } else {
          targetG.setAttribute("opacity", "0");
        }

        rafRef.current = requestAnimationFrame(frame);
      };
      rafRef.current = requestAnimationFrame(frame);
    })();

    return () => {
      cancelled = true;
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  return (
    <div
      className="munin-loader"
      role="status"
      aria-label="Munin is thinking"
      data-testid="munin-loader"
    >
      <div className="munin-loader-layer">
        <svg viewBox="0 0 200 200">
          <g stroke="var(--munin-hud-faint)" strokeWidth="0.5">
            <line x1="0" y1="100" x2="200" y2="100" />
            <line x1="100" y1="0" x2="100" y2="200" />
          </g>
          <g stroke="var(--munin-hud-faint)" strokeWidth="0.5" fill="none">
            <path d="M 6 6 L 18 6 M 6 6 L 6 18" />
            <path d="M 194 6 L 182 6 M 194 6 L 194 18" />
            <path d="M 6 194 L 18 194 M 6 194 L 6 182" />
            <path d="M 194 194 L 182 194 M 194 194 L 194 182" />
          </g>
        </svg>
      </div>

      <div className="munin-loader-ring munin-loader-spin-cw munin-loader-r3 munin-loader-layer">
        <svg viewBox="0 0 200 200">
          <ellipse
            cx="100"
            cy="100"
            rx="95"
            ry="30"
            fill="none"
            stroke="var(--munin-hud-dim)"
            strokeWidth="0.6"
            strokeDasharray="1 3"
            transform="rotate(-18 100 100)"
          />
        </svg>
      </div>
      <div className="munin-loader-ring munin-loader-spin-ccw munin-loader-r4 munin-loader-layer">
        <svg viewBox="0 0 200 200">
          <ellipse
            cx="100"
            cy="100"
            rx="92"
            ry="38"
            fill="none"
            stroke="var(--munin-hud-dim)"
            strokeWidth="0.6"
            strokeDasharray="2 6"
            transform="rotate(22 100 100)"
          />
        </svg>
      </div>
      <div className="munin-loader-ring munin-loader-spin-cw munin-loader-r2 munin-loader-layer">
        <svg viewBox="0 0 200 200">
          <g ref={tickRailRef} />
        </svg>
      </div>
      <div className="munin-loader-ring munin-loader-spin-ccw munin-loader-r1 munin-loader-layer">
        <svg viewBox="0 0 200 200">
          <circle
            cx="100"
            cy="100"
            r="88"
            fill="none"
            stroke="var(--munin-hud)"
            strokeWidth="0.6"
            strokeDasharray="0.5 5"
            strokeLinecap="round"
            opacity="0.85"
          />
        </svg>
      </div>

      <div className="munin-loader-layer">
        <svg ref={rootRef} viewBox="0 0 200 200">
          <defs>
            <clipPath id="muninLoaderGlobeClip">
              <circle cx="100" cy="100" r="70" />
            </clipPath>
            <radialGradient id="muninLoaderSphere" cx="38%" cy="32%" r="75%">
              <stop offset="0%" stopColor="#2A3138" />
              <stop offset="55%" stopColor="#14181C" />
              <stop offset="100%" stopColor="#07090B" />
            </radialGradient>
            <radialGradient id="muninLoaderRim" cx="50%" cy="50%" r="50%">
              <stop offset="80%" stopColor="rgba(0,0,0,0)" />
              <stop offset="100%" stopColor="rgba(0,0,0,0.85)" />
            </radialGradient>
            <radialGradient id="muninLoaderSpec" cx="32%" cy="28%" r="30%">
              <stop offset="0%" stopColor="rgba(220,230,240,0.35)" />
              <stop offset="70%" stopColor="rgba(220,230,240,0)" />
            </radialGradient>
            <linearGradient id="muninLoaderSweep" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="rgba(180,210,240,0)" />
              <stop offset="85%" stopColor="rgba(180,210,240,0.28)" />
              <stop offset="100%" stopColor="rgba(180,210,240,0.45)" />
            </linearGradient>
          </defs>

          <circle cx="100" cy="100" r="70" fill="url(#muninLoaderSphere)" />

          <g clipPath="url(#muninLoaderGlobeClip)">
            <g
              ref={graticuleRef}
              fill="none"
              stroke="rgba(210,222,232,0.18)"
              strokeWidth="0.3"
            />
            <g
              ref={landStrokeRef}
              fill="none"
              stroke="rgba(220,228,236,0.85)"
              strokeWidth="0.45"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            <g
              ref={landFillRef}
              fill="rgba(190,200,210,0.10)"
              stroke="none"
            />

            <g className="munin-loader-sweep">
              <path
                d="M 100 100 L 170 100 A 70 70 0 0 0 100 30 Z"
                fill="url(#muninLoaderSweep)"
              />
            </g>

            <circle cx="100" cy="100" r="70" fill="url(#muninLoaderRim)" />
            <circle cx="100" cy="100" r="70" fill="url(#muninLoaderSpec)" />
          </g>

          <circle
            cx="100"
            cy="100"
            r="70"
            fill="none"
            stroke="rgba(230,236,242,0.65)"
            strokeWidth="0.7"
          />
          <circle
            cx="100"
            cy="100"
            r="68"
            fill="none"
            stroke="rgba(230,236,242,0.12)"
            strokeWidth="0.4"
          />
        </svg>
      </div>

      <div className="munin-loader-layer">
        <svg viewBox="0 0 200 200">
          <g stroke="var(--munin-hud)" strokeWidth="0.8" fill="none">
            <path d="M 18 40 L 18 22 L 36 22" />
            <path d="M 182 40 L 182 22 L 164 22" />
            <path d="M 18 160 L 18 178 L 36 178" />
            <path d="M 182 160 L 182 178 L 164 178" />
          </g>
          <g fill="var(--munin-hud)">
            <rect x="17" y="99" width="3" height="2" />
            <rect x="180" y="99" width="3" height="2" />
            <rect x="99" y="17" width="2" height="3" />
            <rect x="99" y="180" width="2" height="3" />
          </g>
          <g stroke="var(--munin-hud)" strokeWidth="0.7">
            <line x1="100" y1="24" x2="100" y2="30" />
            <line x1="100" y1="170" x2="100" y2="176" />
            <line x1="24" y1="100" x2="30" y2="100" />
            <line x1="170" y1="100" x2="176" y2="100" />
          </g>

          <g ref={targetRef}>
            <circle
              ref={targetPulseRef}
              className="munin-loader-pulse"
              cx="0"
              cy="0"
              r="3"
              fill="none"
              stroke="var(--munin-accent)"
              strokeWidth="0.8"
            />
            <g ref={targetReticleRef} className="munin-loader-blink">
              <circle
                cx="0"
                cy="0"
                r="4.5"
                fill="none"
                stroke="var(--munin-accent)"
                strokeWidth="0.9"
              />
              <circle cx="0" cy="0" r="1.2" fill="var(--munin-accent)" />
              <line
                x1="-8"
                y1="0"
                x2="-5.5"
                y2="0"
                stroke="var(--munin-accent)"
                strokeWidth="0.8"
              />
              <line
                x1="5.5"
                y1="0"
                x2="8"
                y2="0"
                stroke="var(--munin-accent)"
                strokeWidth="0.8"
              />
              <line
                x1="0"
                y1="-8"
                x2="0"
                y2="-5.5"
                stroke="var(--munin-accent)"
                strokeWidth="0.8"
              />
              <line
                x1="0"
                y1="5.5"
                x2="0"
                y2="8"
                stroke="var(--munin-accent)"
                strokeWidth="0.8"
              />
            </g>
            <g
              stroke="var(--munin-accent)"
              strokeWidth="0.7"
              fill="none"
              opacity="0.9"
            >
              <path ref={leaderRef} d="" />
            </g>
            <g
              ref={targetTagRef}
              fill="none"
              stroke="var(--munin-accent)"
              strokeWidth="0.7"
            >
              <rect ref={tagBoxRef} x="0" y="0" width="22" height="4" />
            </g>
          </g>

          <g ref={markersRef} fill="none" stroke="var(--munin-hud)" strokeWidth="0.6" />
        </svg>
      </div>

      <div className="munin-loader-vignette" />
    </div>
  );
}
