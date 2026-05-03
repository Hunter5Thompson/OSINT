import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";
import type { ShaderType } from "../../types";
import { applyCRTShader, applyNightVisionShader, applyFLIRShader, clearShaders } from "../shaders/shaderUtils";

interface GlobeViewerProps {
  onViewerReady: (viewer: Cesium.Viewer) => void;
  cesiumToken: string;
  activeShader: ShaderType;
  showCountryBorders: boolean;
  showCityBuildings: boolean;
}

export function GlobeViewer({
  onViewerReady,
  cesiumToken,
  activeShader,
  showCountryBorders,
  showCityBuildings,
}: GlobeViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Cesium.Viewer | null>(null);
  const nightLayerRef = useRef<Cesium.ImageryLayer | null>(null);
  const borderLayerRef = useRef<Cesium.ImageryLayer | null>(null);
  const buildingsTilesetRef = useRef<Cesium.Cesium3DTileset | null>(null);
  const showBordersRef = useRef(showCountryBorders);
  const showBuildingsRef = useRef(showCityBuildings);
  showBordersRef.current = showCountryBorders;
  showBuildingsRef.current = showCityBuildings;

  useEffect(() => {
    if (!containerRef.current || viewerRef.current) return;

    Cesium.Ion.defaultAccessToken = cesiumToken;

    const viewer = new Cesium.Viewer(containerRef.current, {
      timeline: false,
      animation: false,
      baseLayerPicker: false,
      geocoder: false,
      homeButton: false,
      sceneModePicker: false,
      navigationHelpButton: false,
      fullscreenButton: false,
      selectionIndicator: false,
      infoBox: false,
      scene3DOnly: true,
      msaaSamples: 4,
    });

    // Dark atmosphere
    viewer.scene.globe.enableLighting = true;
    if (viewer.scene.skyAtmosphere) {
      viewer.scene.skyAtmosphere.brightnessShift = -0.3;
    }
    viewer.scene.fog.enabled = true;
    viewer.scene.fog.density = 0.0002;
    viewer.scene.backgroundColor = Cesium.Color.fromCssColorString("#0a0a0a");

    // Cesium World Terrain — relief + bathymetry
    try {
      viewer.scene.setTerrain(
        Cesium.Terrain.fromWorldTerrain({
          requestWaterMask: true,
          requestVertexNormals: true,
        }),
      );
      viewer.scene.verticalExaggeration = 1.5;
    } catch {
      // Terrain unavailable — continue without relief
    }

    // Google Photorealistic 3D Tiles with night-side darkening
    const addBuildingsTileset = (tileset: Cesium.Cesium3DTileset) => {
      if (viewer.isDestroyed()) return;
      tileset.maximumScreenSpaceError = 2;
      tileset.show = showBuildingsRef.current;
      viewer.scene.primitives.add(tileset);
      buildingsTilesetRef.current = tileset;
    };

    void Cesium.createGooglePhotorealistic3DTileset()
      .then((tileset) => {
        tileset.customShader = new Cesium.CustomShader({
          fragmentShaderText: /* glsl */ `
            void fragmentMain(FragmentInput fsInput, inout czm_modelMaterial material) {
              // Darken fragments on the night side of the Earth
              vec3 normalEC = fsInput.attributes.normalEC;
              float NdotL = dot(normalEC, czm_sunDirectionEC);
              // Smooth day-to-night transition at the terminator
              float nightFactor = smoothstep(-0.05, 0.15, -NdotL);
              material.diffuse *= mix(1.0, 0.03, nightFactor);
            }
          `,
        });
        addBuildingsTileset(tileset);
      })
      .catch(() => {
        // Fallback: OpenStreetMap buildings if Google Photorealistic is unavailable.
        void Cesium.createOsmBuildingsAsync()
          .then((tileset) => {
            tileset.style = new Cesium.Cesium3DTileStyle({
              color: "color('rgb(146,158,175)', 0.55)",
            });
            addBuildingsTileset(tileset);
          })
          .catch(() => {
            // No 3D buildings available — continue with terrain-only.
          });
      });

    // Country borders + place labels overlay.
    void Cesium.createWorldImageryAsync({ style: Cesium.IonWorldImageryStyle.ROAD })
      .then((provider) => {
        if (viewer.isDestroyed()) return;
        const bordersLayer = viewer.imageryLayers.addImageryProvider(provider);
        bordersLayer.show = showBordersRef.current;
        bordersLayer.alpha = 0.45;
        bordersLayer.brightness = 0.9;
        bordersLayer.contrast = 1.15;
        borderLayerRef.current = bordersLayer;
      })
      .catch(() => {
        // Overlay unavailable (token/access) — keep globe running without borders.
      });

    // NASA Black Marble (VIIRS) for night side city lights
    // Cesium ion asset id: 3812
    void Cesium.IonImageryProvider.fromAssetId(3812)
      .then((provider) => {
        if (viewer.isDestroyed()) return;
        const nightLayer = new Cesium.ImageryLayer(provider, {
          dayAlpha: 0.0,
          nightAlpha: 0.9,
          brightness: 1.2,
          gamma: 1.05,
        });
        viewer.imageryLayers.add(nightLayer);
        nightLayerRef.current = nightLayer;
      })
      .catch(() => {
        // Graceful fallback if token/asset access fails.
      });

    // Initial camera position (Europe overview)
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(15.0, 45.0, 15_000_000),
    });

    viewerRef.current = viewer;
    onViewerReady(viewer);

    return () => {
      if (nightLayerRef.current && viewerRef.current && !viewerRef.current.isDestroyed()) {
        viewerRef.current.imageryLayers.remove(nightLayerRef.current, false);
        nightLayerRef.current = null;
      }
      if (borderLayerRef.current && viewerRef.current && !viewerRef.current.isDestroyed()) {
        viewerRef.current.imageryLayers.remove(borderLayerRef.current, false);
        borderLayerRef.current = null;
      }
      if (buildingsTilesetRef.current && viewerRef.current && !viewerRef.current.isDestroyed()) {
        viewerRef.current.scene.primitives.remove(buildingsTilesetRef.current);
        buildingsTilesetRef.current = null;
      }
      if (viewerRef.current && !viewerRef.current.isDestroyed()) {
        // Cesium walks scene.primitives on destroy and re-destroys each child.
        // If any layer's PolylineCollection has a stale already-destroyed
        // polyline in its internal _polylines array (a known Cesium quirk
        // around removeAll/destroy ordering), this throws on the way out.
        // The viewer is being torn down regardless — swallow so we don't
        // leak a half-destroyed viewer into the React error boundary on
        // route changes.
        try {
          viewerRef.current.destroy();
        } catch {
          /* viewer was tearing down primitives in a corrupt state */
        }
        viewerRef.current = null;
      }
    };
  }, [cesiumToken, onViewerReady]);

  useEffect(() => {
    if (borderLayerRef.current) {
      borderLayerRef.current.show = showCountryBorders;
    }
  }, [showCountryBorders]);

  useEffect(() => {
    if (buildingsTilesetRef.current) {
      buildingsTilesetRef.current.show = showCityBuildings;
    }
  }, [showCityBuildings]);

  // Handle shader changes
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;

    clearShaders(viewer);

    switch (activeShader) {
      case "crt":
        applyCRTShader(viewer);
        break;
      case "nightvision":
        applyNightVisionShader(viewer);
        break;
      case "flir":
        applyFLIRShader(viewer);
        break;
      case "none":
      default:
        break;
    }
  }, [activeShader]);

  return (
    <div
      ref={containerRef}
      style={{ width: "100%", height: "100%", position: "absolute", top: 0, left: 0 }}
    />
  );
}
