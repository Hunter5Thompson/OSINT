import { describe, it, expect, vi } from "vitest";
import type { ReportRecord } from "../../types";
import { applyDelete, runDeleteDossier } from "../briefingDelete";

const mk = (id: string, title = id.toUpperCase()) =>
  ({ id, title }) as unknown as ReportRecord;
const reports = [mk("a"), mk("b"), mk("c")];

describe("applyDelete (reducer)", () => {
  it("keeps the current selection when a different report is deleted", () => {
    const r = applyDelete(reports, "a", "c");
    expect(r.reports.map((x) => x.id)).toEqual(["a", "b"]);
    expect(r.selectedId).toBe("a");
  });
  it("moves to the next report when the selected one is deleted", () => {
    expect(applyDelete(reports, "b", "b").selectedId).toBe("c");
  });
  it("falls back to the previous when deleting the last selected", () => {
    expect(applyDelete(reports, "c", "c").selectedId).toBe("b");
  });
  it("returns empty selection when the only report is deleted", () => {
    const r = applyDelete([mk("a")], "a", "a");
    expect(r.reports).toEqual([]);
    expect(r.selectedId).toBe("");
  });
});

describe("runDeleteDossier (orchestrator)", () => {
  it("does nothing when the confirm dialog is declined", async () => {
    const deleteReportFn = vi.fn().mockResolvedValue(undefined);
    const out = await runDeleteDossier({ report: mk("b"), confirm: () => false, deleteReportFn });
    expect(out.status).toBe("cancelled");
    expect(deleteReportFn).not.toHaveBeenCalled();
  });
  it("calls the API and reports the dropped id on success", async () => {
    const deleteReportFn = vi.fn().mockResolvedValue(undefined);
    const out = await runDeleteDossier({ report: mk("b"), confirm: () => true, deleteReportFn });
    expect(deleteReportFn).toHaveBeenCalledWith("b");
    expect(out.status).toBe("deleted");
    if (out.status === "deleted") expect(out.droppedId).toBe("b");
  });
  it("keeps the report (no state change) when the API call fails", async () => {
    const deleteReportFn = vi.fn().mockRejectedValue(new Error("500"));
    const out = await runDeleteDossier({ report: mk("b"), confirm: () => true, deleteReportFn });
    expect(out.status).toBe("error");
  });
});
