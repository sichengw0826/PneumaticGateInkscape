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

    def compute_fillet(self, raw_pts, pts_loop, outer_r, inner_r, is_closed):
        """
        Replace each corner of the looped offset path with two cubic bezier segments
        approximating a circular fillet, choosing interior or exterior radius based on
        the raw input path angle (<pi interior, else exterior).
        """
        def angle_between(u, v):
            dot = max(-1.0, min(1.0, u[0]*v[0] + u[1]*v[1]))
            return math.acos(dot)

        fillet_cmds = []
        m = len(pts_loop)
        for i, p in enumerate(pts_loop):
            # open endpoints: simple line
            if not is_closed and (i == 0 or i == m-1):
                fillet_cmds.append(("L", p))
                continue

            # raw input neighbors
            raw_prev = raw_pts[i-1] if i>0 else raw_pts[-1]
            raw_cur  = raw_pts[i]
            raw_next = raw_pts[(i+1)%len(raw_pts)] if is_closed else raw_pts[i+1]
            # compute angle on raw input
            u = ((raw_prev[0]-raw_cur[0]), (raw_prev[1]-raw_cur[1]))
            v = ((raw_next[0]-raw_cur[0]), (raw_next[1]-raw_cur[1]))
            L1 = math.hypot(*u); L2 = math.hypot(*v)
            if L1==0 or L2==0:
                fillet_cmds.append(("L", p)); continue
            u = (u[0]/L1, u[1]/L1); v=(v[0]/L2, v[1]/L2)
            ang = angle_between(u, v)
            is_interior = ang < math.pi
            # choose radius
            r = inner_r if is_interior else outer_r
            # clamp radius to half shortest offset edge length
            # find adjacent offset pts
            prev_off = pts_loop[i-1] if i>0 else pts_loop[-1]
            next_off = pts_loop[(i+1)%m] if is_closed else pts_loop[i+1]
            d1 = math.hypot(prev_off[0]-p[0], prev_off[1]-p[1])
            d2 = math.hypot(next_off[0]-p[0], next_off[1]-p[1])
            r = min(r, 0.5*min(d1, d2))

            # compute tangent unit vectors along offset loop
            t1 = ((prev_off[0]-p[0])/d1, (prev_off[1]-p[1])/d1)
            t2 = ((next_off[0]-p[0])/d2, (next_off[1]-p[1])/d2)
            # arc endpoints
            start_pt = (p[0] + t1[0]*r, p[1] + t1[1]*r)
            end_pt   = (p[0] + t2[0]*r, p[1] + t2[1]*r)
            # angle between tangents
            theta = angle_between(t1, t2)
            if theta<1e-3 or abs(math.pi-theta)<1e-3:
                fillet_cmds.append(("L", p)); continue
            phi = theta/2.0
            k = 4.0/3.0*math.tan(phi/2.0)
            # control points
            # normal direction for first control
            n1 = (-t1[1], t1[0])
            n2 = (-t2[1], t2[0])
            c1 = (start_pt[0] + n1[0]*r*k * (1 if not is_interior else -1),
                  start_pt[1] + n1[1]*r*k * (1 if not is_interior else -1))
            c2 = (end_pt[0]   + n2[0]*r*k * (1 if is_interior else -1),
                  end_pt[1]   + n2[1]*r*k * (1 if is_interior else -1))

            # emit commands
            fillet_cmds.append(("L", start_pt))
            # two cubic segments
            fillet_cmds.append(("C", [c1, c2, end_pt]))
        return fillet_cmds

    def effect(self):

        def intersect(p1, d1, p2, d2):
            # Helper: intersect two infinite lines (p1 + t·d1) & (p2 + u·d2)
            denom = d1[0]*d2[1] - d1[1]*d2[0]
            if abs(denom) < 1e-6:
                # nearly parallel → just return p1
                return p1
            delta = (p2[0] - p1[0], p2[1] - p1[1])
            t = (delta[0]*d2[1] - delta[1]*d2[0]) / denom
            return (p1[0] + t*d1[0], p1[1] + t*d1[1])
        
        def build_path(cmds, move_first=True):
            path_cmds = []
            if move_first and cmds:
                # Move to the first point
                first = cmds[0]
                path_cmds.append(['M', first[1]])
                cmds_iter = cmds[1:]
            else:
                cmds_iter = cmds
            for letter, args in cmds_iter:
                #path_cmds.append([letter, args])

                new_cmd = []
                for ag in args:
                    if not (isinstance(ag,list) or isinstance(ag,tuple)):
                        new_cmd.append(ag)
                    else:
                        for val in ag:
                           new_cmd.append(val) 
                path_cmds.append([letter,new_cmd])

            path_cmds.append(['Z', []])
            return path_cmds

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
        left_loop = self.compute_fillet(pts, left_pts, outer_r, inner_r, closed)
        right_loop= self.compute_fillet(pts, right_pts, outer_r, inner_r, closed)

        # Create polygons

        parent = elem.getparent()
        fill_color = elem.style.get('stroke','#000000')
        if closed:
            outer = PathElement(); outer.style={'fill':fill_color,'stroke':'none'}
            outer.path = Path([['M',left_loop[0]]] + [['L',pt] for pt in left_loop[1:]] + [['Z',[]]])
            parent.add(outer)
            inner = PathElement(); inner.style={'fill':fill_color,'stroke':'none'}
            inner.path = Path([['M',right_loop[0]]] + [['L',pt] for pt in right_loop[1:]] + [['Z',[]]])
            parent.add(inner)
        else:
            ribbon = PathElement()
            ribbon.style = {'fill': fill_color, 'stroke': 'none'}
            # Combine loops: left then reversed right
            reversed_right = [[cmd[0], cmd[1]] for cmd in reversed(right_loop)]
            ribbon_loop = left_loop + reversed_right
            #inkex.errormsg(f"{ribbon_loop}")
            ribbon_cmds = build_path(ribbon_loop)
            inkex.errormsg(f"{ribbon_cmds}")
            ribbon.path = Path(ribbon_cmds)
            parent.add(ribbon)



if __name__ == "__main__":
    OffsetRibbon().run()
