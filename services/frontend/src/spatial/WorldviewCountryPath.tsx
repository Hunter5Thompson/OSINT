import type { ReactNode } from "react";

export interface MutuallyExclusiveCountryPathProps {
  readonly spatialEnabled: boolean;
  readonly legacyRenderer: ReactNode;
  readonly legacyClickHandler: ReactNode;
  readonly spatialRenderer: ReactNode;
  readonly spatialClickHandler: ReactNode;
}

export function MutuallyExclusiveCountryPath({
  spatialEnabled,
  legacyRenderer,
  legacyClickHandler,
  spatialRenderer,
  spatialClickHandler,
}: MutuallyExclusiveCountryPathProps) {
  return spatialEnabled
    ? <>{spatialRenderer}{spatialClickHandler}</>
    : <>{legacyRenderer}{legacyClickHandler}</>;
}
