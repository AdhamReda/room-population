import Autodesk.Revit.DB as DB
import importlib
import geometry2d
import revit_geometry
importlib.reload(geometry2d)
importlib.reload(revit_geometry)
from geometry2d import ( 
    centroid2d, mirror2d, rotate2d,
    find_best_alignment,
    )
from revit_geometry import (
    to_2d, xyz_values,
    build_target_frame, build_transform,
     get_room_raw_points, 
    find_host_face_reference
    )
import Autodesk.Revit.DB as DB





def diagnose_room_placement(template_xy, source_frame, source_floor_z,
                            captured_items, rooms, frames, ray_intersector):
    """Report the existing calculation and host search without placement.

    No matching or ray-selection rules are changed. The report separates
    the predicted point from the hit point that normal mode actually uses.
    Coordinates and lengths are Revit internal feet; angles are radians.
    """
    source_inverse = source_frame.Inverse
    tcx, tcy = centroid2d(template_xy)
    report = {
        "diagnostic_version": 1,
        "length_unit": "Revit internal feet",
        "angle_unit": "radians",
        "source_template_xy": template_xy,
        "source_floor_z": source_floor_z,
        "source_fixtures": [],
        "targets": [],
    }
    for item in captured_items:
        report["source_fixtures"].append({
            "element_id": item["source_element_id"],
            "symbol_id": str(item["symbol_id"]),
            "origin_xyz": xyz_values(item["source_origin"]),
            "basis_x": xyz_values(source_frame.OfVector(item["rel_x"])),
            "basis_y": xyz_values(source_frame.OfVector(item["rel_y"])),
            "basis_z": xyz_values(source_frame.OfVector(item["rel_z"])),
            "mirrored": item["source_mirrored"],
        })

    for room, link_transform in rooms:
        target = {"room_id": str(room.Id), "fixture_probes": []}
        report["targets"].append(target)
        try:
            raw = get_room_raw_points(room, link_transform)
            if not raw:
                target["status"] = "NO_BOUNDARY"
                continue
            target["boundary_host_xyz"] = [xyz_values(p) for p in raw]
            alignment = find_best_alignment(template_xy, to_2d(raw))
            target["alignment"] = alignment
            if alignment is None:
                target["status"] = "NO_ALIGNMENT"
                continue
            avg_z = sum(p.Z for p in raw) / len(raw)
            origin, x, y, z = build_target_frame(frames, alignment, avg_z)
            target_frame = build_transform(origin, x, y, z)
            target["frame"] = {
                "origin": xyz_values(origin),
                "x": xyz_values(x), "y": xyz_values(y), "z": xyz_values(z),
                "xy_determinant": x.X * y.Y - x.Y * y.X,
            }
            target["mapped_template_xyz"] = [
                xyz_values(target_frame.OfPoint(source_inverse.OfPoint(
                    DB.XYZ(px, py, source_floor_z)))) for px, py in template_xy
            ]
            target["status"] = "PROBED"
            for item in captured_items:
                probe = {"source_element_id": item["source_element_id"]}
                target["fixture_probes"].append(probe)
                try:
                    predicted = target_frame.OfPoint(item["rel_origin"])
                    direction = target_frame.OfVector(item["rel_z"]).Normalize()
                    probe["predicted_xyz"] = xyz_values(predicted)
                    probe["ray_facing_vector"] = xyz_values(direction)
                    probe["requested_x_direction"] = xyz_values(
                        target_frame.OfVector(item["rel_x"]))
                    probe["requested_y_direction"] = xyz_values(
                        target_frame.OfVector(item["rel_y"]))

                    # Compare the Revit frame mapping with the direct 2D formula.
                    p = item["source_origin"]
                    local = (p.X - tcx, p.Y - tcy)
                    if alignment["mirrored"]:
                        local = mirror2d(local)
                    rx, ry = rotate2d(local, alignment["theta"])
                    cx, cy = alignment["centroid"]
                    direct = DB.XYZ(cx + rx, cy + ry,
                                    avg_z + p.Z - source_floor_z)
                    probe["direct_formula_xyz"] = xyz_values(direct)
                    probe["frame_vs_formula_distance"] = predicted.DistanceTo(direct)

                    reference, hit = find_host_face_reference(
                        predicted, direction, ray_intersector)
                    probe["ray_hit_xyz"] = xyz_values(hit)
                    if reference is None:
                        probe["status"] = "NO_HOST"
                    else:
                        probe["status"] = "HOST_FOUND_NOT_PLACED"
                        probe["predicted_to_hit_distance"] = predicted.DistanceTo(hit)
                        probe["host_element_id"] = str(reference.ElementId)
                        probe["linked_host_element_id"] = str(reference.LinkedElementId)
                except Exception as error:
                    probe["status"] = "ERROR"
                    probe["error"] = str(error)
        except Exception as error:
            target["status"] = "ERROR"
            target["error"] = str(error)
    return report