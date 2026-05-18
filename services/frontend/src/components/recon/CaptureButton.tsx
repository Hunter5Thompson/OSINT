import type { RefObject } from "react";
import type { SplatRenderHandle } from "./renderer";

interface CaptureButtonProps {
  handleRef: RefObject<SplatRenderHandle | null>;
  sceneId: string;
}

export function CaptureButton({ handleRef, sceneId }: CaptureButtonProps) {
  async function onClick() {
    const handle = handleRef.current;
    if (!handle) return;
    const blob = await handle.captureScreenshot();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `recon-${sceneId}-${Date.now()}.png`;
    a.click();
    URL.revokeObjectURL(url);
  }
  return <button onClick={onClick}>Capture PNG</button>;
}
