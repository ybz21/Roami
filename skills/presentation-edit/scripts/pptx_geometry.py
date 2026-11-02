"""Project explicit DrawingML geometry into slide coordinates without rendering."""

import math

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
IDENTITY = (1, 0, 0, 1, 0, 0)


def compose(parent, child):
    a, b, c, d, e, f = parent
    g, h, i, j, k, l = child
    return (
        a * g + c * h,
        b * g + d * h,
        a * i + c * j,
        b * i + d * j,
        a * k + c * l + e,
        b * k + d * l + f,
    )


def coordinates(transform, tag, keys):
    node = transform.find(A + tag)
    if node is None or any(key not in node.attrib for key in keys):
        return None
    values = tuple(int(node.get(key)) for key in keys)
    return values if all(abs(value) <= 2**63 - 1 for value in values) else None


def placement(transform, parent, *, group=False):
    if transform is None or parent is None:
        return None
    offset = coordinates(transform, "off", ("x", "y"))
    extent = coordinates(transform, "ext", ("cx", "cy"))
    if offset is None or extent is None or min(extent) <= 0:
        return None
    x, y = offset
    width, height = extent
    angle = math.radians((int(transform.get("rot", "0")) % 21600000) / 60000)
    cosine, sine = math.cos(angle), math.sin(angle)
    horizontal = -1 if transform.get("flipH") in {"1", "true"} else 1
    vertical = -1 if transform.get("flipV") in {"1", "true"} else 1
    rotation = (
        cosine * horizontal,
        sine * horizontal,
        -sine * vertical,
        cosine * vertical,
        0,
        0,
    )
    centered = compose(
        (1, 0, 0, 1, x + width / 2, y + height / 2),
        compose(rotation, (1, 0, 0, 1, -width / 2, -height / 2)),
    )
    if group:
        child_offset = coordinates(transform, "chOff", ("x", "y"))
        child_extent = coordinates(transform, "chExt", ("cx", "cy"))
        if child_offset is None or child_extent is None or min(child_extent) <= 0:
            return None
        sx, sy = width / child_extent[0], height / child_extent[1]
        centered = compose(
            centered, (sx, 0, 0, sy, -child_offset[0] * sx, -child_offset[1] * sy)
        )
    matrix = compose(parent, centered)
    return matrix if all(math.isfinite(value) for value in matrix) else None


def slide_bounds(transform, parent):
    matrix = placement(transform, parent)
    if matrix is None:
        return None
    width, height = coordinates(transform, "ext", ("cx", "cy"))
    a, b, c, d, e, f = matrix
    points = [
        (a * x + c * y + e, b * x + d * y + f)
        for x, y in [(0, 0), (width, 0), (0, height), (width, height)]
    ]
    if not all(math.isfinite(value) for point in points for value in point):
        return None
    xs, ys = zip(*points)
    values = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    return {
        key: round(value, 6)
        for key, value in zip(("x", "y", "width", "height"), values, strict=True)
    }
