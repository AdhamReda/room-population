import Autodesk.Revit.DB as DB
from Autodesk.Revit.DB import BuiltInParameter, StorageType, ElementId


SKIP_BIPS = {
    BuiltInParameter.ELEM_FAMILY_AND_TYPE_PARAM,
    BuiltInParameter.ELEM_FAMILY_PARAM,
    BuiltInParameter.ELEM_TYPE_PARAM,
    BuiltInParameter.FAMILY_LEVEL_PARAM,
    BuiltInParameter.SCHEDULE_LEVEL_PARAM,
    BuiltInParameter.INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM,
    BuiltInParameter.INSTANCE_ELEVATION_PARAM,
    BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM,
    BuiltInParameter.HOST_ID_PARAM,
    BuiltInParameter.FAMILY_WORK_PLANE_BASED,
    BuiltInParameter.INSTANCE_MOVES_WITH_GRID_PARAM,
    BuiltInParameter.ELEM_PARTITION_PARAM,       
    BuiltInParameter.PHASE_CREATED,
    BuiltInParameter.PHASE_DEMOLISHED,
    BuiltInParameter.ALL_MODEL_MARK,
}


def _param_key(p):
    """Return a (kind, key) tuple that identifies a parameter unambiguously."""
    defn = p.Definition
    try:
        bip = defn.BuiltInParameter
        if bip != BuiltInParameter.INVALID:
            
            return ("bip", bip)
    except AttributeError:
        pass
    if p.IsShared:
        
        return ("guid", p.GUID)
    
    return ("name", defn.Name)


def capture_parameters(el):
    """Collect writable, non-formula instance parameter values from an element."""
    captured = []
    for p in el.Parameters:
        if p.IsReadOnly or not p.HasValue:
            continue
        kind, key = _param_key(p)
        if kind == "bip" and key in SKIP_BIPS:
            continue
        st = p.StorageType
        if st == StorageType.Double:
            value = p.AsDouble()
        elif st == StorageType.Integer:
            value = p.AsInteger()
        elif st == StorageType.String:
            value = p.AsString()
        elif st == StorageType.ElementId:
            value = p.AsElementId()
        else:
            continue
        captured.append({
            "kind": kind,
            "key": key,
            "name": p.Definition.Name,
            "storage": st,
            "value": value,
        })
    return captured




def _find_param(inst, kind, key):
    if kind == "bip":
        return inst.get_Parameter(key)
    if kind == "guid":
        return inst.get_Parameter(key)
    return inst.LookupParameter(key)




def apply_parameters(inst, captured_params):
    """Write captured values onto a new instance. Returns list of failure messages."""
    failures = []
    for item in captured_params:
        p = _find_param(inst, item["kind"], item["key"])
        if p is None:
            failures.append("missing: {}".format(item["name"]))
            continue
        if p.IsReadOnly or p.StorageType != item["storage"]:
            continue
        value = item["value"]
        if value is None:
            continue
        try:
            p.Set(value)
        except Exception as ex:
            failures.append("{}: {}".format(item["name"], ex))
    return failures