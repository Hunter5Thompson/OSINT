import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { useRef } from "react";
import { CameraControls } from "../CameraControls";
import type { SplatRenderHandle } from "../renderer/SplatRenderer";

function makeHandle(): SplatRenderHandle {
  return {
    dispose: vi.fn(),
    captureScreenshot: vi.fn(async () => new Blob()),
    getCanvas: () => document.createElement("canvas"),
    move: vi.fn(),
    look: vi.fn(),
  };
}

function Probe({ handle }: { handle: SplatRenderHandle | null }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const handleRef = useRef<SplatRenderHandle | null>(handle);
  handleRef.current = handle;
  return (
    <>
      <canvas ref={canvasRef} data-testid="canvas" />
      <CameraControls canvasRef={canvasRef} handleRef={handleRef} />
    </>
  );
}

describe("CameraControls", () => {
  it("calls handle.move on WASD keydown", () => {
    const handle = makeHandle();
    render(<Probe handle={handle} />);
    fireEvent.keyDown(window, { code: "KeyW" });
    fireEvent.keyDown(window, { code: "KeyA" });
    fireEvent.keyDown(window, { code: "KeyS" });
    fireEvent.keyDown(window, { code: "KeyD" });
    fireEvent.keyDown(window, { code: "KeyQ" });
    fireEvent.keyDown(window, { code: "KeyE" });
    expect(handle.move).toHaveBeenCalledTimes(6);
    expect(handle.move).toHaveBeenNthCalledWith(1, "z", -1);
    expect(handle.move).toHaveBeenNthCalledWith(2, "x", -1);
    expect(handle.move).toHaveBeenNthCalledWith(3, "z", 1);
    expect(handle.move).toHaveBeenNthCalledWith(4, "x", 1);
    expect(handle.move).toHaveBeenNthCalledWith(5, "y", -1);
    expect(handle.move).toHaveBeenNthCalledWith(6, "y", 1);
  });

  it("ignores keys when handle is null", () => {
    render(<Probe handle={null} />);
    fireEvent.keyDown(window, { code: "KeyW" });
    // Nothing to assert beyond "no exception thrown"
  });

  it("ignores unmapped keys", () => {
    const handle = makeHandle();
    render(<Probe handle={handle} />);
    fireEvent.keyDown(window, { code: "Space" });
    expect(handle.move).not.toHaveBeenCalled();
  });
});
