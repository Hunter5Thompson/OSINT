import * as Cesium from "cesium";

/** Keep a usable geographic reference when configured imagery is unavailable. */
export function createBaseLayer(
  cesiumToken: string,
): Cesium.ImageryLayer | undefined {
  if (cesiumToken) return undefined;
  return Cesium.ImageryLayer.fromProviderAsync(
    Cesium.TileMapServiceImageryProvider.fromUrl(
      Cesium.buildModuleUrl("Assets/Textures/NaturalEarthII"),
    ),
  );
}
