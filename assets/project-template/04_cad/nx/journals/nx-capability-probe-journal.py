# -*- coding: utf-8 -*-
"""Disposable NX Modeling, Drafting, PDF, save, and reopen capability probe."""

from __future__ import annotations

import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path

import NXOpen
import NXOpen.Drawings
import NXOpen.Features


def collection_count(collection) -> int:
    return sum(1 for _ in collection)


def main() -> None:
    run_dir = os.environ.get("THESIS_NX_RUN_DIR", "")
    if not run_dir:
        raise RuntimeError("THESIS_NX_RUN_DIR is required; use nx_stage_run.py")
    output_dir = Path(run_dir) / "capability"
    result_path = output_dir / "capability-result.json"
    part_file = "capability/nx-capability-probe.prt"
    pdf_file = "capability/nx-capability-probe.pdf"
    part_path = Path(run_dir) / part_file
    pdf_path = Path(run_dir) / pdf_file
    result = {
        "schema_version": "1.0",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "journal": Path(__file__).name,
        "stage": "initializing",
        "success": False,
        "part_file": part_file,
        "pdf_file": pdf_file,
        "test_geometry_mm": {"length": 40.0, "width": 30.0, "height": 20.0},
        "scope": "diagnostic_modeling_drafting_pdf_save_reopen",
        "limitations": [
            "Outputs are disposable diagnostics, not thesis CAD deliverables.",
            "Does not verify Mold Wizard or production-model quality."
        ]
    }
    block_builder = None
    base_view_builder = None
    pdf_builder = None
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        session = NXOpen.Session.GetSession()
        result["nx_full_version"] = session.GetEnvironmentVariableValue("NX_FULL_VERSION")

        result["stage"] = "create_part"
        work_part = session.Parts.NewDisplay(str(part_path), NXOpen.Part.Units.Millimeters)
        result["part_created"] = work_part is not None

        result["stage"] = "create_block"
        block_builder = work_part.Features.CreateBlockFeatureBuilder(None)
        block_builder.Type = NXOpen.Features.BlockFeatureBuilder.Types.OriginAndEdgeLengths
        block_builder.SetOriginAndLengths(NXOpen.Point3d(0.0, 0.0, 0.0), "40", "30", "20")
        feature = block_builder.CommitFeature()
        block_builder.Destroy()
        block_builder = None
        result["block_feature_created"] = feature is not None
        result["body_count_after_modeling"] = collection_count(work_part.Bodies)

        result["stage"] = "create_drawing"
        model_view = work_part.ModelingViews.WorkView
        sheet = work_part.DrawingSheets.InsertSheet(
            "NX_CAPABILITY_SHEET",
            NXOpen.Drawings.DrawingSheet.Unit.Millimeters,
            297.0,
            210.0,
            1.0,
            1.0,
            NXOpen.Drawings.DrawingSheet.ProjectionAngleType.ThirdAngle,
        )
        sheet.Open()
        base_view_builder = work_part.DraftingViews.CreateBaseViewBuilder(None)
        base_view_builder.SelectModelView.SelectedView = model_view
        base_view_builder.Scale.Numerator = 1.0
        base_view_builder.Scale.Denominator = 1.0
        base_view_builder.Placement.Placement.SetValue(
            None, sheet.View, NXOpen.Point3d(148.5, 105.0, 0.0)
        )
        base_view = base_view_builder.Commit()
        base_view_builder.Destroy()
        base_view_builder = None
        work_part.DraftingViews.UpdateViews(
            NXOpen.Drawings.DraftingViewCollection.ViewUpdateOption.All, sheet
        )
        result["drawing_sheet_created"] = sheet is not None
        result["base_view_created"] = base_view is not None
        result["drawing_view_count"] = len(sheet.GetDraftingViews())

        result["stage"] = "save_and_export"
        save_status = work_part.Save(
            NXOpen.BasePart.SaveComponents.TrueValue,
            NXOpen.BasePart.CloseAfterSave.FalseValue,
        )
        if hasattr(save_status, "Dispose"):
            save_status.Dispose()
        result["part_saved"] = part_path.is_file()
        result["part_size_bytes"] = part_path.stat().st_size if part_path.is_file() else 0

        pdf_builder = work_part.PlotManager.CreatePrintPdfbuilder()
        pdf_builder.SourceBuilder.SetSheets([sheet])
        pdf_builder.Filename = str(pdf_path)
        pdf_builder.Commit()
        pdf_builder.Destroy()
        pdf_builder = None
        result["pdf_exported"] = pdf_path.is_file()
        result["pdf_size_bytes"] = pdf_path.stat().st_size if pdf_path.is_file() else 0

        result["stage"] = "reopen"
        responses = session.Parts.NewPartCloseResponses()
        session.Parts.CloseAll(NXOpen.BasePart.CloseModified.CloseModified, responses)
        if hasattr(responses, "Dispose"):
            responses.Dispose()
        reopened, load_status = session.Parts.OpenDisplay(str(part_path))
        if hasattr(load_status, "Dispose"):
            load_status.Dispose()
        reopened_sheets = list(reopened.DrawingSheets)
        result["reopen_succeeded"] = reopened is not None
        result["body_count_after_reopen"] = collection_count(reopened.Bodies)
        result["drawing_sheet_count_after_reopen"] = len(reopened_sheets)
        result["drawing_view_count_after_reopen"] = (
            len(reopened_sheets[0].GetDraftingViews()) if reopened_sheets else 0
        )
        result["stage"] = "verified"
        result["success"] = all(
            (
                result.get("part_created"),
                result.get("block_feature_created"),
                result.get("body_count_after_modeling", 0) >= 1,
                result.get("drawing_sheet_created"),
                result.get("base_view_created"),
                result.get("drawing_view_count", 0) >= 1,
                result.get("part_saved"),
                result.get("part_size_bytes", 0) > 0,
                result.get("pdf_exported"),
                result.get("pdf_size_bytes", 0) > 0,
                result.get("reopen_succeeded"),
                result.get("body_count_after_reopen", 0) >= 1,
                result.get("drawing_sheet_count_after_reopen", 0) >= 1,
                result.get("drawing_view_count_after_reopen", 0) >= 1,
            )
        )
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
        result["traceback"] = traceback.format_exc()
    finally:
        for builder in (pdf_builder, base_view_builder, block_builder):
            if builder is not None:
                try:
                    builder.Destroy()
                except Exception:
                    pass
        output_dir.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
    if not result["success"]:
        raise RuntimeError(
            f"NX capability probe failed at {result.get('stage')}: "
            f"{result.get('error', 'verification condition was not met')}"
        )


if __name__ == "__main__":
    main()
