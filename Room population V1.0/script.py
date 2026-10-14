#! python3
"""Automated Room Element Distributor (2D Template Matching & 3D Raycasting)

Overview:
    Distributes hosted family instances (elements) from a source room to matching target
    rooms. Fits a hand-drawn k-point 2D template polygon against raw, unsimplified target
    room boundaries (n >= k) to find optimal rigid alignment (translation, rotation, mirror),
    then uses 3D reverse raycasting to locate host face references.

Workflow:
    0. Settings: Choose target selection mode and diagnostic mode in the dialog.
    1. Intersector setup: build the ReferenceIntersector early, so it's available for
        per-instance facing calibration during capture (see step 2).
    2. Capture: Select source room, choose target Elements, and click k boundary corners.
        For each captured element, calibrate which sign of its own BasisZ actually points
        "away from host" by testing both signs against ITS OWN (already correct) host --
        this avoids guessing a sign convention from IsWorkPlaneFlipped, which doesn't map
        to a single universal rule across families.
        NOTE: (important corners only and obvious corners dont click on the middle of a wall).
        This approach is approximation as not all identical rooms are actually identical
    3. Target Resolution: Identify target rooms automatically (by name/area) or manually,
        then (automatic modes) filter them by the chosen levels.
    4. Alignment: Combinatorial search for best k-point subset minimizing boundary RMSE.
    5. Hosting: Raycast along mapped, calibrated Z-basis vectors to obtain DB.Reference
        face targets, rejecting hits that land implausibly far from the search origin.
    6. Execution: Create new family instances (Placement Mode) or output JSON (Diagnostic Mode).

Dependencies:
    - Custom Modules: geometry2d, revit_geometry, diagnostics, distributor_ui
    - Revit API: Autodesk.Revit.DB, Autodesk.Revit.UI
"""
import sys
import json
import importlib
import geometry_engine
import revit_geometry
import diagnostics
import distributor_ui
import parameters_utils


importlib.reload(geometry_engine)
importlib.reload(revit_geometry)
importlib.reload(diagnostics)
importlib.reload(distributor_ui)
importlib.reload(parameters_utils)


from geometry_engine import (
    centroid2d, canonicalize_ccw,
    find_best_alignment, template_frame_vectors,
    template_frame_vectors_by_mirror
    )
from revit_geometry import (
    to_2d, pick_points, ensure_3d_view_open,
    build_target_frame, build_transform,
    pick_linked_room, pick_target_rooms_manually,
    create_target_rooms, get_room_raw_points,
    find_host_face_reference, calibrate_facing_sign,
    pick_excluded_rooms, level_below
    )
from parameters_utils import apply_parameters, capture_parameters
from diagnostics import diagnose_room_placement
from distributor_ui import show_settings_dialog, show_level_dialog

from pyrevit import script
import Autodesk.Revit.Exceptions as RevitExceptions


import Autodesk.Revit.DB as DB
from Autodesk.Revit.UI import UIDocument, TaskDialog

from Autodesk.Revit.UI.Selection import ObjectType
from System.Collections.Generic import List

    
def main():
    uidoc: UIDocument = __revit__.ActiveUIDocument
    doc: DB.Document = uidoc.Document

    # ---------------------------------------------------------------------
    # 0. SETTINGS (UI)
    # ---------------------------------------------------------------------
    settings = show_settings_dialog()
    if settings is None:
        sys.exit("User Cancelled")

    target_selection_mode = settings["mode"]

    DIAGNOSTIC_ONLY = settings["diagnostic"]
    TRANSFER_PARAMETERS=settings['parameters']
    # ---------------------------------------------------------------------
    # 1. INTERSECTOR SETUP (moved up from the old Section 3 location)
    # ---------------------------------------------------------------------
    # Built before capture now, because calibrate_facing_sign() needs a live
    # intersector to test each source element's own BasisZ sign against its
    # own (already correctly hosted) surface, before we ever touch a target
    # room.
    intersector_view = ensure_3d_view_open(uidoc)
    cat_list = List[DB.BuiltInCategory]()
    for cat in (DB.BuiltInCategory.OST_Walls, DB.BuiltInCategory.OST_Ceilings,
                DB.BuiltInCategory.OST_Floors, DB.BuiltInCategory.OST_Roofs,
                DB.BuiltInCategory.OST_StructuralFraming, DB.BuiltInCategory.OST_StructuralFoundation,
                DB.BuiltInCategory.OST_GenericModel):
        cat_list.Add(cat)
    host_filter = DB.ElementMulticategoryFilter(cat_list)
    intersector = DB.ReferenceIntersector(host_filter, DB.FindReferenceTarget.Face, intersector_view)
    intersector.FindReferencesInRevitLinks = True

    # ---------------------------------------------------------------------
    # 2. TEMPLATE + CAPTURE (source room)
    # ---------------------------------------------------------------------
    source_room, source_link_transform, linked_doc = pick_linked_room(uidoc, "Select SOURCE room (in linked model)")
    element_refs = uidoc.Selection.PickObjects(ObjectType.Element, "Select Elements in the source room")
    source_elements = [doc.GetElement(r) for r in element_refs]

    template_pts_xyz = pick_points(uidoc)

    template_pts_2d = to_2d(template_pts_xyz)

    source_raw_pts = get_room_raw_points(source_room, source_link_transform)
    if source_raw_pts is None:
        raise Exception("Could not read source room boundary (for elevation).")
    template_avg_z = sum(p.Z for p in source_raw_pts) / len(source_raw_pts)

    tcx, tcy = centroid2d(template_pts_2d)
    template_local = canonicalize_ccw([(x - tcx, y - tcy) for x, y in template_pts_2d])
    x_dir_t, y_dir_t = template_frame_vectors(template_local)

    source_origin = DB.XYZ(tcx, tcy, template_avg_z)
    source_x_axis = DB.XYZ(x_dir_t[0], x_dir_t[1], 0)
    source_y_axis = DB.XYZ(y_dir_t[0], y_dir_t[1], 0)
    source_z_axis = DB.XYZ.BasisZ
    
    source_cs = build_transform(source_origin, source_x_axis, source_y_axis, source_z_axis)
    source_cs_inv = source_cs.Inverse

    captured = []
    for el in source_elements:
        if not hasattr(el, "GetTransform"):
            print(f"Skipping element {el.Id}: no GetTransform().")
            continue
        fam_transform = el.GetTransform()
        source_work_plane_flipped = bool(el.IsWorkPlaneFlipped)

        rel_origin = source_cs_inv.OfPoint(fam_transform.Origin)
        rel_x = source_cs_inv.OfVector(fam_transform.BasisX)
        rel_y = source_cs_inv.OfVector(fam_transform.BasisY)
        rel_z = source_cs_inv.OfVector(fam_transform.BasisZ)
        parameters=capture_parameters(el)
        planar=False
        on_floor=False
        if abs(1-abs(rel_z.Z))<=1e-6:
            planar=True
            offset_param=el.LookupParameter("Offset_FFL")
            elev_param=el.get_Parameter(DB.BuiltInParameter.INSTANCE_ELEVATION_PARAM)
            if offset_param and elev_param:
                if offset_param.AsDouble()<=300/304.8 and elev_param.AsDouble() <=300/304.8:
                    on_floor=True
            # else:
            #     print(f"WARNING: {el.Id} is planar but missing Offset_FFL or Elevation param; defaulting on_floor=False")


            

        
        sign = calibrate_facing_sign(fam_transform.Origin, fam_transform.BasisZ, intersector)
        if sign is None:
            print(f"WARNING: couldn't calibrate host-facing direction for {el.Id}; using raw BasisZ")
            sign = 1.0
        rel_z_calibrated = rel_z.Multiply(sign)

        captured.append({
            "source_unique_id": el.UniqueId, "symbol_id": el.Symbol.Id, "rel_origin": rel_origin,
            "rel_x": rel_x, "rel_y": rel_y, "rel_z": rel_z_calibrated,
            "source_element_id": str(el.Id),
            "source_origin": fam_transform.Origin,
            "source_mirrored": bool(el.Mirrored),
            "source_work_plane_flipped": source_work_plane_flipped,
            "planar": planar,
            "on_floor": on_floor,
            "parameters": parameters
        })

    print(f"Captured {len(captured)} element(s) from source room {source_room.Id}.")
    print(f"Template has k={len(template_pts_2d)} vertices.")

    # Frame vectors for BOTH mirror hypotheses, computed once, reused for
    # every target room -- which one applies depends on which hypothesis
    # won that specific room's alignment search (see find_best_alignment).
    frame_vectors_by_mirror = template_frame_vectors_by_mirror(template_pts_2d)

    # ---------------------------------------------------------------------
    # 3. TARGET ROOMS
    # ---------------------------------------------------------------------
    if target_selection_mode == "automatic":
        target_rooms = create_target_rooms(source_room, linked_doc, source_link_transform)
    elif target_selection_mode == "automatic_except":
        excluded_room_ids = pick_excluded_rooms(uidoc, linked_doc)
        target_rooms = create_target_rooms(
            source_room, linked_doc, source_link_transform,
            excluded_room_ids=excluded_room_ids
        )
    else:
        target_rooms = pick_target_rooms_manually(doc, uidoc)

    # Level filter (skipped in manual mode, since the user already picked rooms)
    if target_selection_mode != "manual":
        level_elev = {}
        for room, _ in target_rooms:
            if room.Level:
                level_elev[room.Level.Name] = room.Level.Elevation
        level_names = sorted(level_elev, key=level_elev.get)  # bottom to top

        chosen = show_level_dialog(level_names)
        if chosen is None:
            sys.exit("User Cancelled")
        if not chosen:
            sys.exit("No levels selected")

        target_rooms = [(r, t) for r, t in target_rooms
                        if r.Level and r.Level.Name in chosen]
        print(f"{len(target_rooms)} target room(s) on selected levels.")

    # ---------------------------------------------------------------------
    # 4. DISTRIBUTE
    # ---------------------------------------------------------------------
    # (3D view + intersector were already built in step 1, before capture.)
    levels = list(DB.FilteredElementCollector(doc)
                  .OfCategory(DB.BuiltInCategory.OST_Levels)
                  .WhereElementIsNotElementType())

    if DIAGNOSTIC_ONLY:
        report = diagnose_room_placement(
            template_pts_2d, source_cs, template_avg_z,
            captured, target_rooms, frame_vectors_by_mirror, intersector)
        report["source_room_id"] = str(source_room.Id)
        print("ROOM_DISTRIBUTOR_DIAGNOSTIC_JSON_BEGIN")
        print(json.dumps(report, indent=2, ensure_ascii=True))
        print("ROOM_DISTRIBUTOR_DIAGNOSTIC_JSON_END")
        print("Diagnostic mode: no Elements were created. Copy the JSON report above.")
    else:
        results = []
        t = DB.Transaction(doc, "Distribute Captured Elements (Template Match)")
        t.Start()

       
        for room, link_transform in target_rooms:
            raw_pts = get_room_raw_points(room, link_transform)
            if raw_pts is None:
                results.append(f"SKIPPED (no boundary): room id {room.Id}")
                continue
            candidate_2d = to_2d(raw_pts)
            avg_z = sum(p.Z for p in raw_pts) / len(raw_pts)

            alignment = find_best_alignment(template_pts_2d, candidate_2d)
            if alignment is None:
                results.append(f"SKIPPED (fewer raw points than template k): room id {room.Id}")
                continue

            print(f"Room {room.Id},{room.Name}: rmse={alignment['rmse']:.4f} mirrored={alignment['mirrored']} "
              #f"chosen_indices={alignment['indices']} (of {len(candidate_2d)} raw points)")
                )

            o, x, y, z = build_target_frame(frame_vectors_by_mirror, alignment, avg_z)
            target_cs = build_transform(o, x, y, z)

            for item in captured:
                symbol = doc.GetElement(item["symbol_id"])
                if symbol is None:
                    results.append(f"SKIPPED (symbol not found): {item['symbol_id']}")
                    continue
                if not symbol.IsActive:
                    symbol.Activate()
                    doc.Regenerate()

                g_origin = target_cs.OfPoint(item["rel_origin"])
                g_x = target_cs.OfVector(item["rel_x"])
                facing = target_cs.OfVector(item["rel_z"]).Normalize()

                face_ref, hit_point = find_host_face_reference(g_origin, facing, intersector)
                if face_ref is None:
                    results.append(f"NO HOST SURFACE FOUND near room {room.Id} at {g_origin}")
                    continue
                lvl = level_below(hit_point.Z, levels)
                try:
                    new_inst = doc.Create.NewFamilyInstance(face_ref, hit_point, g_x, symbol)
                    if TRANSFER_PARAMETERS:
                        param_failures = apply_parameters(new_inst, item["parameters"])
                        if param_failures:
                            results.append(
                                "PARAM ISSUES on {}: {}".format(new_inst.Id, "; ".join(param_failures))
                            )

                    if new_inst.CanFlipWorkPlane:
                        new_inst.IsWorkPlaneFlipped=item['source_work_plane_flipped']
                    offset=new_inst.LookupParameter("Offset_FFL")
                    if offset:  
                        offset.Set(0.0)
    
                    lvl = level_below(hit_point.Z, levels)
                    level_param = new_inst.get_Parameter(DB.BuiltInParameter.INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM)
                    if lvl and level_param and not level_param.IsReadOnly:
                        level_param.Set(lvl.Id)

                    results.append(new_inst.Id)
                except Exception as e:
                    results.append(f"FAILED room {room.Id}, {room.Name}: {e}")

        t.Commit()
        for r in results:
            print(r)
        print("Done.")

        created = sum(1 for r in results if isinstance(r, DB.ElementId))
        TaskDialog.Show(
            "Done",
            f"Created {created} element(s).\n"
            f"{len(results) - created} issue(s), see output window."
        )


output = script.get_output()

try:
    main()
except (RevitExceptions.OperationCanceledException, SystemExit):

    output.close()
except Exception as ex:

    output.close()
    TaskDialog.Show("Room Element Distributor - Error", str(ex))

