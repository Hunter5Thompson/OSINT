import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { InspectorPanel } from "./InspectorPanel";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("InspectorPanel", () => {
  it("is hidden when nothing is selected", () => {
    const { container } = render(
      <InspectorPanel selected={null} onClose={vi.fn()} viewer={null} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a firms hotspot with coordinates in Martian Mono", () => {
    render(
      <InspectorPanel
        selected={{
          type: "firms",
          data: {
            id: "firms-1",
            latitude: 12.34,
            longitude: 56.78,
            frp: 4.2,
            brightness: 320.5,
            confidence: "nominal",
            acq_date: "2026-04-21",
            acq_time: "1000",
            satellite: "VIIRS",
            bbox_name: "sinjar-ridge",
            possible_explosion: false,
            firms_map_url: "https://firms.modaps.eosdis.nasa.gov/...",
          },
        }}
        onClose={vi.fn()}
        viewer={null}
      />,
    );
    expect(screen.getByRole("region", { name: /Inspector/i })).toBeInTheDocument();
    expect(screen.getByText(/12.340 N, 56.780 E/)).toBeInTheDocument();
    expect(screen.getByText(/FIRMS hotspot · VIIRS/)).toBeInTheDocument();
  });

  it("calls onClose when × is clicked", () => {
    const onClose = vi.fn();
    render(
      <InspectorPanel
        selected={{
          type: "aircraft",
          data: {
            icao24: "abc123",
            callsign: null,
            type_code: null,
            military_branch: null,
            registration: null,
            points: [],
          },
        }}
        onClose={onClose}
        viewer={null}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /close Inspector/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("shows refinery infrastructure photos, specs, coordinates, and source links", () => {
    render(
      <InspectorPanel
        selected={{
          type: "refinery",
          data: {
            name: "Sabine Pass LNG Terminal",
            operator: "Cheniere Energy",
            capacity_bpd: 0,
            country: "US",
            status: "active",
            facility_type: "lng_terminal",
            latitude: 29.7540967,
            longitude: -93.8740512,
            image_url: "https://example.test/sabine-pass.jpg",
            source_url: "https://www.gem.wiki/Sabine_Pass_LNG_Terminal",
            specs: ["Coordinates exact per GEM", "Import/export LNG terminal"],
          },
        }}
        onClose={vi.fn()}
        viewer={null}
      />,
    );

    expect(screen.getByRole("img", { name: /Sabine Pass LNG Terminal/i })).toHaveAttribute(
      "src",
      "https://example.test/sabine-pass.jpg",
    );
    expect(screen.getByText("lng terminal")).toBeInTheDocument();
    expect(screen.getByText(/29.754 N, 93.874 W/)).toBeInTheDocument();
    expect(screen.getByText("Coordinates exact per GEM")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /source/i })).toHaveAttribute(
      "href",
      "https://www.gem.wiki/Sabine_Pass_LNG_Terminal",
    );
  });

  it("renders a Source link for a datacenter with source_url", () => {
    render(
      <InspectorPanel
        selected={{
          type: "datacenter",
          data: {
            name: "AWS US-East-1 (Ashburn)",
            operator: "Amazon Web Services",
            tier: "hyperscaler",
            capacity_mw: 600,
            country: "US",
            city: "Ashburn",
            source_url: "https://baxtel.com/data-center/aws-us-east-1",
            coord_quality: "campus_verified",
            coord_source: "https://baxtel.com/data-center/aws-us-east-1",
          },
        }}
        onClose={vi.fn()}
        viewer={null}
      />,
    );
    const link = screen.getByRole("link", { name: /Source/i });
    expect(link).toHaveAttribute("href", "https://baxtel.com/data-center/aws-us-east-1");
    expect(screen.getByText(/campus_verified/)).toBeInTheDocument();
  });

  it("hides the Source link when datacenter source_url is absent", () => {
    render(
      <InspectorPanel
        selected={{
          type: "datacenter",
          data: {
            name: "Legacy DC",
            operator: "Acme",
            tier: "III",
            capacity_mw: null,
            country: "DE",
            city: "Berlin",
          },
        }}
        onClose={vi.fn()}
        viewer={null}
      />,
    );
    expect(screen.queryByRole("link", { name: /Source/i })).toBeNull();
  });

  it("bounds the panel height to the viewport so a tall country almanac can scroll", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("missing", { status: 404 }));
    render(
      <InspectorPanel
        selected={{
          type: "country",
          data: {
            m49: "276",
            iso3: "DEU",
            name: "Germany",
            geometry: { type: "Polygon", coordinates: [[[0, 0], [0, 1], [1, 1], [0, 0]]] },
            capital: { name: "Berlin", coords: { lon: 13.4, lat: 52.5 } },
          },
        }}
        onClose={vi.fn()}
        viewer={null}
      />,
    );
    const panel = screen.getByRole("region", { name: /Inspector/i });
    // The Inspector is absolutely positioned at top:86 with no document scroll. Without a
    // viewport-bounded max-height the section grows to its content, so its inner scroll
    // region never overflows and a tall almanac's lower rows fall off-screen unreachable.
    expect(panel.style.maxHeight).toMatch(/vh/);
    // Flush the almanac fetch (404 -> error state) so the effect's state update settles.
    await screen.findByText(/unavailable for this country/i);
  });
});
