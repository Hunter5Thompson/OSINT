import * as Cesium from "cesium";
import { CRT_SHADER } from "./CRTShader.glsl";
import { NIGHT_VISION_SHADER } from "./NightVisionShader.glsl";
import { FLIR_SHADER } from "./FLIRShader.glsl";

const SHADER_STAGE_NAME = "worldview_postprocess";

export function clearShaders(viewer: Cesium.Viewer): void {
  const stages = viewer.scene.postProcessStages;
  // Remove all custom stages
  for (let i = stages.length - 1; i >= 0; i--) {
    const stage = stages.get(i);
    if (stage.name?.startsWith(SHADER_STAGE_NAME)) {
      stages.remove(stage);
    }
  }
}

export function applyCRTShader(viewer: Cesium.Viewer): void {
  const stage = new Cesium.PostProcessStage({
    name: `${SHADER_STAGE_NAME}_crt`,
    fragmentShader: CRT_SHADER,
  });
  viewer.scene.postProcessStages.add(stage);
}

export function applyNightVisionShader(viewer: Cesium.Viewer): void {
  const stage = new Cesium.PostProcessStage({
    name: `${SHADER_STAGE_NAME}_nv`,
    fragmentShader: NIGHT_VISION_SHADER,
  });
  viewer.scene.postProcessStages.add(stage);
}

export function applyFLIRShader(viewer: Cesium.Viewer): void {
  const stage = new Cesium.PostProcessStage({
    name: `${SHADER_STAGE_NAME}_flir`,
    fragmentShader: FLIR_SHADER,
  });
  viewer.scene.postProcessStages.add(stage);
}
