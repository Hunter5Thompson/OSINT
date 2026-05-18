import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

interface ReconContextValue {
  activeSceneId: string | null;
  isOpen: boolean;
  openScene: (sceneId: string) => void;
  closeScene: () => void;
}

const ReconContext = createContext<ReconContextValue | null>(null);

export function ReconProvider({ children }: { children: ReactNode }) {
  const [activeSceneId, setActiveSceneId] = useState<string | null>(null);

  const openScene = useCallback((sceneId: string) => setActiveSceneId(sceneId), []);
  const closeScene = useCallback(() => setActiveSceneId(null), []);

  const value = useMemo<ReconContextValue>(
    () => ({
      activeSceneId,
      isOpen: activeSceneId !== null,
      openScene,
      closeScene,
    }),
    [activeSceneId, openScene, closeScene]
  );

  return <ReconContext.Provider value={value}>{children}</ReconContext.Provider>;
}

export function useRecon(): ReconContextValue {
  const ctx = useContext(ReconContext);
  if (ctx === null) {
    throw new Error("useRecon must be used inside <ReconProvider>");
  }
  return ctx;
}
