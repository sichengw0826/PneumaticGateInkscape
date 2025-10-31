#!/usr/bin/env python3
"""
Inkscape extension to create a 2D “ribbon” offset from an arbitrary (possibly multi‐segment,
open or closed) straight‐line path. Select one path, run the effect, enter the total ribbon
width, and a new filled polygon will be created around the original.
"""

import math
import inkex
from inkex import PathElement, Path
from inkex.transforms import Transform

class OffsetRibbon(inkex.Effect):

    def __init__(self):
        super().__init__()
        self.arg_parser.add_argument(
            "-w", "--width",
            type=float,
            default=10.0,
            help="Total ribbon width"
        )
        self.arg_parser.add_argument(
            "-f", "--fillet",
            type=float,
            default=0.6,
            help="Fillet radius as fraction of ribbon width (must be >0.5)"
        )

    def effect(self):
        # Require exactly one selected element
        if len(self.svg.selection) != 1:
            inkex.errormsg("Please select exactly one path.")
            return
        elem = next(iter(self.svg.selection.values()))
        if not isinstance(elem, PathElement):
            inkex.errormsg("Selected element is not a path.")
            return
        
        raw_path = elem.path
        closed = (raw_path.to_absolute()[-1].letter == 'Z')

        # Get the full object transform and the absolute path commands
        transform = elem.composed_transform()
        path_cmds = elem.path.to_absolute()

        # Extract only Move (M) and Line (L) points, applying the transform
        pts = []
        for cmd in path_cmds:
            if cmd.letter in ('M', 'L'):
                x, y = cmd.args
                px, py = transform.apply_to_point((x, y))
                pts.append((px, py))
            elif cmd.letter == 'Z':
                # closing handled below
                pass
            else:
                inkex.errormsg(f"Unsupported path command: only straight segments allowed, line type = {cmd.letter}")
                return

        # Must have at least two points
        if len(pts) < 2:
            inkex.errormsg("Path must have at least two points.")
            return

        # Detect closed path (first and last coincide)
        #closed = False
        #if math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-6:
        #    closed = True
        #    pts = pts[:-1]
        
        n = len(pts)
        width = self.options.width
        half_w = width/2.0
        fillet_pct = max(self.options.fillet, 0.5)
        design_r = fillet_pct * width
        outer_r = design_r + half_w
        inner_r = max(design_r - half_w, 0.0)

        # Compute direction vectors and normals for each segment
        dirs = []
        norms = []
        for i in range(n - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i+1]
            dx, dy = x2 - x1, y2 - y1
            L = math.hypot(dx, dy)
            if L == 0:
                inkex.errormsg("Zero‐length segment detected.")
                return
            ux, uy = dx / L, dy / L
            dirs.append((ux, uy))
            norms.append((-uy, ux))   # perp vector

        # If closed, add the final segment from last → first
        if closed:
            x1, y1 = pts[-1]
            x2, y2 = pts[0]
            dx, dy = x2 - x1, y2 - y1
            L = math.hypot(dx, dy)
            ux, uy = dx / L, dy / L
            dirs.append((ux, uy))
            norms.append((-uy, ux))

        # Helper: intersect two infinite lines (p1 + t·d1) & (p2 + u·d2)
        def intersect(p1, d1, p2, d2):
            denom = d1[0]*d2[1] - d1[1]*d2[0]
            if abs(denom) < 1e-6:
                # nearly parallel → just return p1
                return p1
            delta = (p2[0] - p1[0], p2[1] - p1[1])
            t = (delta[0]*d2[1] - delta[1]*d2[0]) / denom
            return (p1[0] + t*d1[0], p1[1] + t*d1[1])

        # Build the two offset polylines: left (+norm) and right (–norm)
        left_pts = []
        right_pts = []
        for i in range(n):
            p = pts[i]
            if i == 0:
                if closed:
                    d1, n1 = dirs[-1], norms[-1]
                    d2, n2 = dirs[i],   norms[i]
                    p1a = (p[0] + n1[0]*half_w, p[1] + n1[1]*half_w)
                    p2a = (p[0] + n2[0]*half_w, p[1] + n2[1]*half_w)
                    left_pts.append(intersect(p1a, d1, p2a, d2))

                    p1b = (p[0] - n1[0]*half_w, p[1] - n1[1]*half_w)
                    p2b = (p[0] - n2[0]*half_w, p[1] - n2[1]*half_w)
                    right_pts.append(intersect(p1b, d1, p2b, d2))
                else:
                    # start cap
                    nrm = norms[-1] if closed else norms[0]
                    left_pts.append((p[0] + nrm[0]*half_w, p[1] + nrm[1]*half_w))
                    right_pts.append((p[0] - nrm[0]*half_w, p[1] - nrm[1]*half_w))
            elif i == n - 1:
                if closed:
                    d1, n1 = dirs[i-1], norms[i-1]
                    d2, n2 = dirs[i],   norms[i]
                    p1a = (p[0] + n1[0]*half_w, p[1] + n1[1]*half_w)
                    p2a = (p[0] + n2[0]*half_w, p[1] + n2[1]*half_w)
                    left_pts.append(intersect(p1a, d1, p2a, d2))

                    p1b = (p[0] - n1[0]*half_w, p[1] - n1[1]*half_w)
                    p2b = (p[0] - n2[0]*half_w, p[1] - n2[1]*half_w)
                    right_pts.append(intersect(p1b, d1, p2b, d2))
                else:
                    # end cap
                    nrm = norms[0] if closed else norms[-1]
                    left_pts.append((p[0] + nrm[0]*half_w, p[1] + nrm[1]*half_w))
                    right_pts.append((p[0] - nrm[0]*half_w, p[1] - nrm[1]*half_w))
            else:
                # interior vertex: intersect the two offset segment‐lines
                d1, n1 = dirs[i-1], norms[i-1]
                d2, n2 = dirs[i],   norms[i]
                p1a = (p[0] + n1[0]*half_w, p[1] + n1[1]*half_w)
                p2a = (p[0] + n2[0]*half_w, p[1] + n2[1]*half_w)
                left_pts.append(intersect(p1a, d1, p2a, d2))

                p1b = (p[0] - n1[0]*half_w, p[1] - n1[1]*half_w)
                p2b = (p[0] - n2[0]*half_w, p[1] - n2[1]*half_w)
                right_pts.append(intersect(p1b, d1, p2b, d2))

        # For closed, drop the duplicate last point
        """ if closed:
            left_pts.pop()
            right_pts.pop() """

        # Create polygons
        parent = elem.getparent()
        fill_color = "none" #elem.style.get("stroke", "#000000")

        if closed:
            # Outer loop polygon
            outer_path = [["M", left_pts[0]]]
            for p in left_pts[1:]:
                outer_path.append(["L", p])
            outer_path.append(["Z", []])
            outer = PathElement()
            outer.style = {"fill": fill_color, "stroke": "#FF0000"}
            outer.path = Path(outer_path)
            parent.add(outer)

            # Inner loop polygon
            inner_path = [["M", right_pts[0]]]
            for p in right_pts[1:]:
                inner_path.append(["L", p])
            inner_path.append(["Z", []])
            inner = PathElement()
            inner.style = {"fill": fill_color, "stroke": "#FF0000"}
            inner.path = Path(inner_path)
            parent.add(inner)
        else:
            # Build a closed polygon: left side → reversed right side
            ribbon_path = []
            ribbon_path.append(["M", left_pts[0]])
            for p in left_pts[1:]:
                ribbon_path.append(["L", p])
            for p in reversed(right_pts):
                ribbon_path.append(["L", p])
            ribbon_path.append(["Z", []])

            # Create the new PathElement
            ribbon = PathElement()
            ribbon.style = {"fill": fill_color, "stroke": "#FF0000"}
            ribbon.path = Path(ribbon_path)

            # Insert it just above the original
            elem.getparent().add(ribbon)


if __name__ == "__main__":
    OffsetRibbon().run()
