import { renderHook, act } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useReactRouterScopeNavigation } from "../react";
import { parseScopeKeyCandidate } from "../contracts";

const { navigate } = vi.hoisted(() => ({ navigate: vi.fn() }));
vi.mock("react-router-dom", () => ({
  useNavigate: () => navigate,
  useLocation: () => ({ pathname: "/worldview", search: "", hash: "", state: null, key: "initial" }),
}));

it("commits scope navigation synchronously so live Cesium updates cannot starve its acknowledgement", async () => {
  const { result } = renderHook(() => useReactRouterScopeNavigation());
  let pending: Promise<void>;
  act(() => {
    pending = result.current.writeScope({
      scopeKey: parseScopeKeyCandidate("country:DEU"),
      catalogRevision: "spatial-v1-001122334455",
      mode: "push",
      navigationId: "test-country",
    });
  });
  const cancelled = pending!.catch(() => undefined);
  result.current.cancelPending();
  await cancelled;
  expect(navigate).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ flushSync: true }));
});
