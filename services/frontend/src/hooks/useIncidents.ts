/**
 * useIncidents — context consumer for IncidentProvider.
 *
 * Returns the shared incident state. When mounted outside an
 * IncidentProvider, returns the inert default value (no SSE work) so
 * tests and isolated component renders behave deterministically.
 */
import { useContext } from "react";
import {
  IncidentContext,
  type IncidentContextValue,
} from "../state/IncidentProvider";

export type { IncidentsStatus } from "../state/IncidentProvider";
export type { IncidentContextValue };

export function useIncidents(): IncidentContextValue {
  return useContext(IncidentContext);
}
