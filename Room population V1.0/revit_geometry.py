import Autodesk.Revit.DB as DB
from geometry2d import rotate2d
from Autodesk.Revit.DB.Architecture import Room
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException


def pick_points(uidoc,tolerance=0.5):
    doc=uidoc.Document
    pts=[]
    i=1

    tg=DB.TransactionGroup(doc,"Temp Polygon")
    tg.Start()
    try:
        while True:
            try:

                p = uidoc.Selection.PickPoint(f"Select Room Corner #{i} Escape/Cancel when done")
                #print((p.X,p.Y,p.Z))
                pts.append(p)

                is_closing=False

                if len(pts)>=3 and p.DistanceTo(pts[0])<=tolerance:
                    p=pts[0]
                    is_closing=True
                if len(pts)>1:
                    draw_temp_polygon(pts[-2],p,doc)
                if is_closing:
                    pts.pop() 
                    break
                i+=1
            except OperationCanceledException:        
                break
    finally:
        tg.RollBack()
    return pts

def draw_temp_polygon(p1,p2,doc):
    t=DB.Transaction(doc,"Temnp Line")
    t.Start()
    geom_line=DB.Line.CreateBound(p1,p2)
    detail_line = doc.Create.NewDetailCurve(doc.ActiveView, geom_line)
    
    t.Commit()


def get_room_name(room):
    """Retrieves the name string of a Revit Room.

    Args:
        room (DB.Architecture.Room): The Revit room element.

    Returns:
        str or None: The room name, or None if parameter is missing.
    """
    name_param = room.get_Parameter(DB.BuiltInParameter.ROOM_NAME)
    return name_param.AsString() if name_param else None

def get_room_area(room):
    """Retrieves the area of a Revit Room in internal units (sq ft).

    Args:
        room (DB.Architecture.Room): The Revit room element.

    Returns:
        float or None: Area in square feet, or None if parameter is missing.
    """
    area_param = room.get_Parameter(DB.BuiltInParameter.ROOM_AREA)
    return area_param.AsDouble() if area_param else None



def create_target_rooms(source_room, linked_doc, link_transform, excluded_room_ids=None,tolerance=53):
    """Finds matching target rooms in a linked document by name and area.

    Filters rooms in the linked document whose trimmed name matches the 
    source room's name and whose area falls within the specified tolerance.

    Args:
        source_room (DB.Architecture.Room): Source room from host document.
        linked_doc (DB.Document): Target linked Revit document.
        link_transform (DB.Transform): Coordinate transform of the Revit Link instance.
        tolerance (float): Max allowed area difference in internal units / ft² (default:53 or 5m²).

    Returns:
        list of tuple: List of (DB.Architecture.Room, DB.Transform) tuples for matching rooms.
    """
    target_rooms = []

    source_name = get_room_name(source_room)
    source_area=get_room_area(source_room)
    if not source_name:
        return target_rooms
    rooms = (DB.FilteredElementCollector(linked_doc)
             .OfCategory(DB.BuiltInCategory.OST_Rooms)
             .WhereElementIsNotElementType()
             .ToElements())

    for room in rooms:
        if room.Id == source_room.Id:
            continue
        if excluded_room_ids is not None:
            if room.Id in excluded_room_ids:
                continue
        target_name = get_room_name(room)
        target_area=get_room_area(room)

        if not target_name or not target_area:
            continue
        names_match = source_name.strip() == target_name.strip()
        areas_match = abs(target_area - source_area) < tolerance
        if names_match and areas_match:
            target_rooms.append((room, link_transform))

    return target_rooms


def pick_excluded_rooms(uidoc,linked_doc):
    """Let the user click linked rooms to exclude from automatic
    name-matching. Mirrors pick_target_rooms_manually's picking style
    but only needs the linked Room elements, not (room, link_transform)
    tuples, since exclusion is checked before target_rooms is built."""
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.LinkedElement,
            "Select room(s) to EXCLUDE from automatic matching, then click Finish"
        )
    except Exception:
        return set()
    excluded_ids=set()
    for r in refs:
        linked_el=linked_doc.GetElement(r.LinkedElementId)
        if linked_el is not None:
            excluded_ids.add(linked_el.Id)
    print(excluded_ids)
    return excluded_ids


    
def get_valid_3d_view(doc, user_view=None):
    if user_view is not None and isinstance(user_view, DB.View3D) and not user_view.IsTemplate:
        return user_view
    if isinstance(doc.ActiveView, DB.View3D) and not doc.ActiveView.IsTemplate:
        return doc.ActiveView
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View3D):
        if not v.IsTemplate:
            return v
    raise Exception("No valid 3D View found in document for raycasting.")


def _first_3d_view_family_type(doc):
    """
    Helper function that searches the doc for view family type. It is needed to create a 3d view
    """
    for vft in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType):
        if vft.ViewFamily==DB.ViewFamily.ThreeDimensional:
            return vft
    return None



def ensure_3d_view_open(uidoc, user_view=None):
    """
    Open a 3D view ONCE, up front, with its section box disabled, and
    make it the active view.

    Returns the View3D to hand to ReferenceIntersector.
    """
    doc = uidoc.Document

    try:
        view3d = get_valid_3d_view(doc, user_view)
    except Exception:
        vft = _first_3d_view_family_type(doc)
        if vft is None:
            raise Exception("No 3D view exists and no 3D ViewFamilyType is available to create one.")
        t = DB.Transaction(doc, "Create 3D View")
        t.Start()
        view3d = DB.View3D.CreateIsometric(doc, vft.Id)
        t.Commit()

    # Turn the section box off if it is on (needs a transaction).
    if view3d.IsSectionBoxActive:
        t = DB.Transaction(doc, "Disable 3D Section Box")
        t.Start()
        view3d.IsSectionBoxActive = False
        t.Commit()

    # Make it the active view so Revit generates its graphics now,
    # instead of mid-raycast. Must have no open transaction here.
    if doc.ActiveView.Id != view3d.Id:
        uidoc.ActiveView = view3d
        uidoc.RefreshActiveView()

    return view3d



def to_2d(pts):
    return[(p.X,p.Y) for p in pts]

def build_target_frame(frame_vectors_by_mirror, alignment, avg_z):
    x_dir_t, y_dir_t = frame_vectors_by_mirror[alignment["mirrored"]]
    theta = alignment["theta"]
    cx, cy = alignment["centroid"]

    x2d = rotate2d(x_dir_t, theta)
    y2d = rotate2d(y_dir_t, theta)

    x_axis = DB.XYZ(x2d[0], x2d[1], 0).Normalize()
    y_axis = DB.XYZ(y2d[0], y2d[1], 0).Normalize()

    z_axis = DB.XYZ.BasisZ
    origin = DB.XYZ(cx, cy, avg_z)
    return origin, x_axis, y_axis, z_axis

def build_transform(origin,x,y,z):
    t=DB.Transform.Identity
    t.Origin=origin
    t.BasisX=x
    t.BasisY=y
    t.BasisZ=z
    return t

def resolve_linked_room(doc, reference):
    link_instance = doc.GetElement(reference.ElementId)
    if not isinstance(link_instance, DB.RevitLinkInstance):
        raise Exception(
            f"Picked element {reference.ElementId} is not a RevitLinkInstance. "
            "Make sure you're clicking a room inside a linked model."
        )
    link_doc = link_instance.GetLinkDocument()
    if link_doc is None:
        raise Exception("The link's document is not loaded. Load the link and try again.")
    room = link_doc.GetElement(reference.LinkedElementId)
    if not isinstance(room, Room):
        raise Exception(f"Linked element {reference.LinkedElementId} is not a Room.")
    return room, link_instance.GetTotalTransform()


def pick_linked_room(uidoc, prompt):
    ref = uidoc.Selection.PickObject(ObjectType.LinkedElement, prompt)
    room, transform = resolve_linked_room(uidoc.Document, ref)
    linked_doc = room.Document

    return room, transform, linked_doc


def pick_target_rooms_manually(doc, uidoc):
    """Manual path: user clicks each target room one by one in the
    linked model."""
    target_room_refs = uidoc.Selection.PickObjects(
        ObjectType.LinkedElement, "Select TARGET room(s) (in linked model)"
    )
    return [resolve_linked_room(doc, r) for r in target_room_refs]
def get_room_raw_points(room, link_transform):
    opt = DB.SpatialElementBoundaryOptions()
    opt.SpatialElementBoundaryLocation = DB.SpatialElementBoundaryLocation.Finish
    loops = room.GetBoundarySegments(opt)
    if not loops or len(loops) == 0:
        return None
    outer = loops[0]
    pts = []
    for seg in outer:
        c = seg.GetCurve()
        pts.append(link_transform.OfPoint(c.GetEndPoint(0)))
    return pts





def xyz_values(point):
    if point is None:
        return None
    return [point.X, point.Y, point.Z]


def level_below(z, levels, tolerance=0.01):
    # tolerance in feet (Revit internal units) to treat "equal" as below/on
    candidates = [lvl for lvl in levels if lvl.Elevation <= z + tolerance]
    if not candidates:
        # point is below every level in the model — fall back to lowest level
        return min(levels, key=lambda lvl: lvl.Elevation)
    #General rule of thumb: any time you see key=lambda x: x.something, 
    # read it as "sort/compare/pick based on this attribute,
    #  but still hand me back the whole object."
    return max(candidates, key=lambda lvl: lvl.Elevation)







def calibrate_facing_sign(point, raw_facing, intersector_obj,
                           search_dist=6.0, max_proximity=50):
    """
    Determine which sign of raw_facing actually points "away from host"
    for THIS instance, by testing both directions against its own,
    already-correctly-hosted surface.

    """
    best_sign, best_dist = None, None
    for sign in (1.0, -1.0):
        d = raw_facing.Multiply(sign)
        start = point.Add(d.Multiply(search_dist))
        ray_dir = d.Negate()
        ref_with_ctx = intersector_obj.FindNearest(start, ray_dir)
        if ref_with_ctx is None:
            continue
        dist_from_point = abs(ref_with_ctx.Proximity - search_dist)
        if dist_from_point <= max_proximity and (best_dist is None or dist_from_point < best_dist):
            best_sign, best_dist = sign, dist_from_point
    return best_sign
 
 
def find_host_face_reference(point, facing_dir, intersector_obj,
                              search_dist=6.0, max_proximity=50):
    """
    Raycast to find the host face nearest `point`, along facing_dir first
    and the opposite direction as a fallback.

    """
    for sign in (1.0, -1.0):
        d = facing_dir.Multiply(sign)
        start = point.Add(d.Multiply(search_dist))
        ray_dir = d.Negate()
        ref_with_ctx = intersector_obj.FindNearest(start, ray_dir)
        if ref_with_ctx is None:
            continue
        dist_from_point = abs(ref_with_ctx.Proximity - search_dist)
        if dist_from_point <= max_proximity:
            hit_point = start.Add(ray_dir.Multiply(ref_with_ctx.Proximity))
            return ref_with_ctx.GetReference(), hit_point
    return None, None