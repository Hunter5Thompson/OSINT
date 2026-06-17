import type { ReportRecord } from "../types";

export interface DeleteState {
  reports: ReportRecord[];
  selectedId: string;
}

/** Pure reducer: remove `deletedId` and return BOTH the next reports list and
 *  the next selection. If the deleted report wasn't selected, selection is
 *  unchanged. Otherwise pick the next report, else the previous, else "". */
export function applyDelete(
  reports: ReportRecord[],
  selectedId: string,
  deletedId: string,
): DeleteState {
  const idx = reports.findIndex((r) => r.id === deletedId);
  const remaining = reports.filter((r) => r.id !== deletedId);
  let nextSelected = selectedId;
  if (selectedId === deletedId) {
    nextSelected =
      remaining.length === 0 ? "" : (remaining[Math.min(idx, remaining.length - 1)]?.id ?? "");
  }
  return { reports: remaining, selectedId: nextSelected };
}

export interface DeleteDeps {
  reports: ReportRecord[];
  selectedId: string;
  report: ReportRecord;
  confirm: (message: string) => boolean;
  deleteReportFn: (id: string) => Promise<void>;
}

export type DeleteOutcome =
  | { status: "cancelled" }
  | { status: "deleted"; reports: ReportRecord[]; selectedId: string; droppedChatId: string }
  | { status: "error"; error: unknown };

/** Confirm → delete via API → compute next state. Removes from state only on
 *  success; on failure returns `error` and the caller keeps its existing state. */
export async function runDeleteDossier(deps: DeleteDeps): Promise<DeleteOutcome> {
  const { reports, selectedId, report, confirm, deleteReportFn } = deps;
  if (!confirm(`Delete dossier "${report.title}"? This cannot be undone.`)) {
    return { status: "cancelled" };
  }
  try {
    await deleteReportFn(report.id); // remove from state only after success
    const next = applyDelete(reports, selectedId, report.id);
    return {
      status: "deleted",
      reports: next.reports,
      selectedId: next.selectedId,
      droppedChatId: report.id,
    };
  } catch (error) {
    return { status: "error", error }; // report stays in state
  }
}
