"""Window layout and frame hit-testing (pure functions, no Qt objects).

Window, top to bottom: HALO margin, the frame, the toolbar zone. The capture area is
strictly inside the frame stroke.
"""
HALO = 8                 # transparent margin around the frame (room for the glow)
TOOLBAR_H = 48           # zone below the frame that holds the pill
PILL_TOP = 6             # pill starts this far below the frame
CAPTURE_INSET = 7        # frame centre line -> capture rect (stroke edge + inner stroke + gap)
MIN_CAPTURE = (290, 160)
MIN_WINDOW = (MIN_CAPTURE[0] + 2 * (HALO + CAPTURE_INSET),
              MIN_CAPTURE[1] + 2 * CAPTURE_INSET + HALO + TOOLBAR_H)

OUT_ZONE = 6             # resize band outside the stroke
IN_ZONE = 6              # move band inside the stroke
CORNER = 18              # resize corner extent along an edge


def frame_rect(w, h):
    """Centre line of the frame stroke: (x, y, w, h)."""
    return (HALO, HALO, w - 2 * HALO, h - HALO - TOOLBAR_H)


def capture_rect(w, h):
    x, y, fw, fh = frame_rect(w, h)
    return (x + CAPTURE_INSET, y + CAPTURE_INSET, fw - 2 * CAPTURE_INSET, fh - 2 * CAPTURE_INSET)


def pill_top(h):
    return h - TOOLBAR_H + PILL_TOP


def hit_test(x, y, w, h):
    """Classify a point on the window: (kind, edges).

    kind: 'resize' (halo band outside the stroke), 'move' (stroke and a band inside it)
    or None. edges: subset of {'l', 'r', 't', 'b'} for 'resize', else empty."""
    fx, fy, fw, fh = frame_rect(w, h)
    l, t, r, b = fx, fy, fx + fw, fy + fh
    s = 1.0   # half stroke
    inside_outer = l - s <= x <= r + s and t - s <= y <= b + s
    inside_inner = l + IN_ZONE < x < r - IN_ZONE and t + IN_ZONE < y < b - IN_ZONE
    if inside_outer:
        return (None, frozenset()) if inside_inner else ("move", frozenset())
    if not (l - s - OUT_ZONE <= x <= r + s + OUT_ZONE and t - s - OUT_ZONE <= y <= b + s + OUT_ZONE):
        return None, frozenset()
    edges = set()
    if x < l:
        edges.add("l")
    if x > r:
        edges.add("r")
    if y < t:
        edges.add("t")
    if y > b:
        edges.add("b")
    if edges & {"t", "b"}:
        if x < l + CORNER:
            edges.add("l")
        if x > r - CORNER:
            edges.add("r")
    if edges & {"l", "r"}:
        if y < t + CORNER:
            edges.add("t")
        if y > b - CORNER:
            edges.add("b")
    return "resize", frozenset(edges)
