import { describe, it, expect } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { ReconProvider, useRecon } from "../ReconContext";

function Probe() {
  const { activeSceneId, isOpen, openScene, closeScene } = useRecon();
  return (
    <div>
      <span data-testid="id">{activeSceneId ?? ""}</span>
      <span data-testid="open">{String(isOpen)}</span>
      <button onClick={() => openScene("jax_068")}>open</button>
      <button onClick={() => closeScene()}>close</button>
    </div>
  );
}

describe("ReconContext", () => {
  it("starts closed", () => {
    render(<ReconProvider><Probe /></ReconProvider>);
    expect(screen.getByTestId("id").textContent).toBe("");
    expect(screen.getByTestId("open").textContent).toBe("false");
  });

  it("openScene updates activeSceneId and isOpen", () => {
    render(<ReconProvider><Probe /></ReconProvider>);
    act(() => { screen.getByText("open").click(); });
    expect(screen.getByTestId("id").textContent).toBe("jax_068");
    expect(screen.getByTestId("open").textContent).toBe("true");
  });

  it("closeScene resets state", () => {
    render(<ReconProvider><Probe /></ReconProvider>);
    act(() => { screen.getByText("open").click(); });
    act(() => { screen.getByText("close").click(); });
    expect(screen.getByTestId("id").textContent).toBe("");
    expect(screen.getByTestId("open").textContent).toBe("false");
  });
});
