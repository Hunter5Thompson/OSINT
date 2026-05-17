import { useEffect } from "react";
import type { RefObject } from "react";
import type { CameraAxis, SplatRenderHandle } from "./renderer/SplatRenderer";

interface CameraControlsProps {
  canvasRef: RefObject<HTMLCanvasElement | null>;
  handleRef: RefObject<SplatRenderHandle | null>;
}

const KEY_BINDINGS: Record<string, [CameraAxis, 1 | -1]> = {
  KeyW: ["z", -1],
  KeyS: ["z", 1],
  KeyA: ["x", -1],
  KeyD: ["x", 1],
  KeyQ: ["y", -1],
  KeyE: ["y", 1],
};

export function CameraControls({ canvasRef, handleRef }: CameraControlsProps) {
  useEffect(() => {
    const canvas = canvasRef.current;

    const onClick = () => canvas?.requestPointerLock();
    const onKey = (e: KeyboardEvent) => {
      const binding = KEY_BINDINGS[e.code];
      if (!binding) return;
      const handle = handleRef.current;
      if (!handle) return;
      handle.move(binding[0], binding[1]);
    };
    const onMouseMove = (e: MouseEvent) => {
      if (!canvas || document.pointerLockElement !== canvas) return;
      const handle = handleRef.current;
      if (!handle) return;
      handle.look(e.movementX * 0.002, e.movementY * 0.002);
    };

    canvas?.addEventListener("click", onClick);
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousemove", onMouseMove);
    return () => {
      canvas?.removeEventListener("click", onClick);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousemove", onMouseMove);
    };
  }, [canvasRef, handleRef]);

  return null;
}
