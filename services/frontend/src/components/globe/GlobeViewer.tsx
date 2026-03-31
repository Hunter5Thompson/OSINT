import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";
import type { ShaderType } from "../../types";
import { applyCRTShader, applyNightVisionShader, applyFLIRShader, clearShaders } from "../shaders/shaderUtils";

interface GlobeViewerProps {
  onViewerReady: (viewer: Cesium.Viewer) => void;
  cesiumToken: string;
  activeShader: ShaderType;
}

export function GlobeViewer({ onViewerReady, cesiumToken, activeShader }: GlobeViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Cesium.Viewer | null>(null);
  const nightLayerRef = useRef<Cesium.ImageryLayer | null>(null);

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

    // Google Photorealistic 3D Tiles with night-side darkening
    void Cesium.createGooglePhotorealistic3DTileset().then((tileset) => {
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
      viewer.scene.primitives.add(tileset);
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
      if (viewerRef.current && !viewerRef.current.isDestroyed()) {
        viewerRef.current.destroy();
        viewerRef.current = null;
      }
    };
  }, [cesiumToken, onViewerReady]);

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
