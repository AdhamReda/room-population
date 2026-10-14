import math
import itertools

def centroid2d(points):
    n = len(points)
    return (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n)


def best_fit_rotation(source_local,target_local):
    """
    This function calculates the angle between vectors.
    tan(theta)=determinant of cp divided by dot product
    """
    num = sum(s[0] * t[1] - s[1] * t[0] for s, t in zip(source_local, target_local))
    den = sum(s[0] * t[0] + s[1] * t[1] for s, t in zip(source_local, target_local))
    return math.atan2(num, den)

def rotate2d(v, theta):
    """
    Resolution of two rotated axis x' and y'
    into x and y axis
    """
    c, s = math.cos(theta), math.sin(theta)
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c)

def mirror2d(v):
    return(-v[0],v[1])

def signed_area(pts_2d):
    n = len(pts_2d)
    area = 0.0
    for i in range(n):
        x1, y1 = pts_2d[i]
        x2, y2 = pts_2d[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return area / 2.0
def canonicalize_ccw(pts_2d):
    """
    Force the point list order into a ccw order 
    no matter which diretion the user drew the polygon
    problems:
        -doubling the time to fint best candidate 
        -causes wrong placement 
    """
    if signed_area(pts_2d) < 0:
        return pts_2d[::-1]
    return pts_2d

def rmse_for_fit(template_local,candidate_local):
    """
    calculates RMSE
    Args:
        template_local (list of tuple): List of 2D source coordinates (x, y).
        candidate_local (list of tuple): List of 2D target coordinates (x, y).

    Returns:
    tuple: (rmse, theta)
        - rmse (float): Root Mean Square Error after applying optimal rotation.
        - theta (float): Optimal rotation angle in radians
    """
    theta = best_fit_rotation(template_local, candidate_local)
    total = 0.0
    for (x, y), (tx, ty) in zip(template_local, candidate_local):
        rx, ry = rotate2d((x, y), theta)
        total += (rx - tx) ** 2 + (ry - ty) ** 2
    return math.sqrt(total / len(template_local)), theta


def find_best_alignment(template_pts_2d, candidate_pts_2d):

    """
    Returns:
        {rmse, indices, theta, mirrored, centroid}.

    """
    k = len(template_pts_2d)
    n = len(candidate_pts_2d)
    if n < k:
        return None

    tcx, tcy = centroid2d(template_pts_2d)
    template_local = canonicalize_ccw([(x - tcx, y - tcy) for x, y in template_pts_2d])
    # Mirroring any simple polygon always flips its winding sign, so
    # canonicalize_ccw here always ends up reversing it -- that reversal
    # is exactly what correctly restores a CCW-comparable description
    # of what the mirrored shape looks like, instead of leaving it CW.
    template_local_mirrored = canonicalize_ccw([mirror2d(p) for p in template_local])

    best = None
    for start in range(n):
        rotated_idx = [(start + i) % n for i in range(n)]
        for combo in itertools.combinations(range(n), k):
            original_indices = [rotated_idx[i] for i in combo]
            subset_pts = [candidate_pts_2d[i] for i in original_indices]
            ccx, ccy = centroid2d(subset_pts)
            candidate_local = canonicalize_ccw([(x - ccx, y - ccy) for x, y in subset_pts])

            for mirrored, t_local in ((False, template_local), (True, template_local_mirrored)):
                rmse, theta = rmse_for_fit(t_local, candidate_local)
                if best is None or rmse < best["rmse"]:
                    best = {
                        "rmse": rmse,
                        "indices": original_indices,
                        "theta": theta,
                        "mirrored": mirrored,
                        "centroid": (ccx, ccy),
                    }
    return best

def template_frame_vectors(template_local):
    """
    Normalizes the first point to establish a local 2D coordinate frame.
    Args:
        template_local (list of tuple): A list of 2D coordinates (x, y), typically 
            centered at the origin. The first point is used to define the axes.
    Returns:
        tuple: (x_dir, y_dir)
            - x_dir (tuple of float): A 2D unit vector pointing to the first vertex.
            - y_dir (tuple of float): A 2D unit vector perpendicular (CCW) to x_dir.
    """
    x0,y0=template_local[0]
    L=math.hypot(x0,y0)
    x_dir=(x0/L,y0/L)
    y_dir=(-x_dir[1],x_dir[0])
    return x_dir,y_dir

def template_frame_vectors_by_mirror(template_pts_2d):
    """Generates standard and mirrored local coordinate frames for a 2D shape.
       Args:
        template_pts_2d (list of tuple): A list of raw 2D coordinates (x, y) 
            defining the shape's vertices.

    Returns:
        dict: A mapping representing the unmirrored and mirrored coordinate frames:
            - False (tuple): The standard local axes (x_dir, y_dir).
            - True (tuple): The mirrored local axes (mirror2d(x_dir), mirror2d(y_dir)).

    """
    tcx, tcy = centroid2d(template_pts_2d)
    template_local = canonicalize_ccw([(x - tcx, y - tcy) for x, y in template_pts_2d])
    x_dir, y_dir = template_frame_vectors(template_local)
    return {
        False: (x_dir, y_dir),
        True: (mirror2d(x_dir), mirror2d(y_dir)),
    }