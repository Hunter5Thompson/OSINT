import type { ReactNode } from "react";

interface WebGLCheckProps {
  fallback: ReactNode;
  children: ReactNode;
}

function hasWebGL2(): boolean {
  if (typeof window === "undefined") return false;
  const canvas = document.createElement("canvas");
  try {
    return canvas.getContext("webgl2") !== null;
  } catch {
    return false;
  }
}

export function WebGLCheck({ fallback, children }: WebGLCheckProps) {
  if (!hasWebGL2()) return <>{fallback}</>;
  return <>{children}</>;
}
