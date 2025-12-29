#!/usr/bin/env python3
"""Parse SVG layers and emit object node locations for downstream tools."""

import json
import argparse
import inkex
from inkex import (
    PathElement,
    Rectangle,
    Circle,
    Ellipse,
    Line,
    Polyline,
    Polygon,
    load_svg,
)
from xml.etree import ElementTree as ET


class SvgLayerParser(inkex.Effect):
    def __init__(self):
        super().__init__()
        self.layer_names = ["substrate"]
        '''
        self.arg_parser.add_argument(
            "--output",
            default="parsed_layers.xml",
            help="Output XML file path",
        )
        '''

    def iter_layers(self):
        return self.svg.xpath(
            "//svg:g[@inkscape:groupmode='layer']",
            namespaces=inkex.NSS,
        )

    def get_layer_by_name(self, name):
        for layer in self.iter_layers():
            label = layer.get(inkex.addNS("label", "inkscape")) or layer.get("label")
            if label == name:
                return layer
        return None

    def is_filled(self, elem):
        style = elem.style if hasattr(elem, "style") else {}
        fill = None
        if style:
            fill = style.get("fill")
        if fill is None:
            fill = elem.get("fill")
        if fill is None:
            return False
        fill_value = str(fill).strip().lower()
        return fill_value != "none" and fill_value != ""

    def _points_from_path(self, path, transform):
        abs_path = path.to_absolute()
        points = []
        current = (0.0, 0.0)
        for cmd in abs_path:
            letter = cmd.letter
            args = list(cmd.args)
            if letter in ("M", "L", "T"):
                for i in range(0, len(args) - 1, 2):
                    pt = (args[i], args[i + 1])
                    points.append(pt)
                    current = pt
            elif letter == "H":
                for value in args:
                    pt = (value, current[1])
                    points.append(pt)
                    current = pt
            elif letter == "V":
                for value in args:
                    pt = (current[0], value)
                    points.append(pt)
                    current = pt
            elif letter == "C":
                for i in range(0, len(args) - 1, 2):
                    points.append((args[i], args[i + 1]))
                if len(args) >= 6:
                    current = (args[4], args[5])
            elif letter in ("S", "Q"):
                for i in range(0, len(args) - 1, 2):
                    points.append((args[i], args[i + 1]))
                if len(args) >= 4:
                    current = (args[-2], args[-1])
            elif letter == "A":
                if len(args) >= 2:
                    pt = (args[-2], args[-1])
                    points.append(pt)
                    current = pt
            elif letter == "Z":
                pass
        return [transform.apply_to_point(p) for p in points]

    def _points_from_rect(self, rect, transform):
        x = float(rect.get("x", 0.0))
        y = float(rect.get("y", 0.0))
        w = float(rect.get("width", 0.0))
        h = float(rect.get("height", 0.0))
        pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        return [transform.apply_to_point(p) for p in pts]

    def _points_from_circle(self, circle, transform):
        cx = float(circle.get("cx", 0.0))
        cy = float(circle.get("cy", 0.0))
        r = float(circle.get("r", 0.0))
        pts = [(cx + r, cy), (cx, cy + r), (cx - r, cy), (cx, cy - r)]
        return [transform.apply_to_point(p) for p in pts]

    def _points_from_ellipse(self, ellipse, transform):
        cx = float(ellipse.get("cx", 0.0))
        cy = float(ellipse.get("cy", 0.0))
        rx = float(ellipse.get("rx", 0.0))
        ry = float(ellipse.get("ry", 0.0))
        pts = [(cx + rx, cy), (cx, cy + ry), (cx - rx, cy), (cx, cy - ry)]
        return [transform.apply_to_point(p) for p in pts]

    def _points_from_line(self, line, transform):
        x1 = float(line.get("x1", 0.0))
        y1 = float(line.get("y1", 0.0))
        x2 = float(line.get("x2", 0.0))
        y2 = float(line.get("y2", 0.0))
        return [
            transform.apply_to_point((x1, y1)),
            transform.apply_to_point((x2, y2)),
        ]

    def _points_from_points_attr(self, points_attr, transform):
        pts = []
        if not points_attr:
            return pts
        raw = points_attr.replace(",", " ").split()
        for i in range(0, len(raw) - 1, 2):
            try:
                x = float(raw[i])
                y = float(raw[i + 1])
            except ValueError:
                continue
            pts.append(transform.apply_to_point((x, y)))
        return pts

    def node_locations(self, elem):
        transform = (
            elem.composed_transform() if hasattr(elem, "composed_transform") else inkex.Transform()
        )
        if isinstance(elem, PathElement) and elem.path is not None:
            return self._points_from_path(elem.path, transform)
        if hasattr(elem, "path") and elem.path is not None:
            return self._points_from_path(elem.path, transform)
        if isinstance(elem, Rectangle):
            return self._points_from_rect(elem, transform)
        if isinstance(elem, Circle):
            return self._points_from_circle(elem, transform)
        if isinstance(elem, Ellipse):
            return self._points_from_ellipse(elem, transform)
        if isinstance(elem, Line):
            return self._points_from_line(elem, transform)
        if isinstance(elem, (Polyline, Polygon)):
            return self._points_from_points_attr(elem.get("points"), transform)
        return []

    def element_type(self, elem):
        if isinstance(elem, PathElement):
            return "path"
        tag = elem.tag
        if "}" in tag:
            return tag.split("}", 1)[1]
        return tag

    def build_output(self):
        root = ET.Element("layers")
        for name in self.layer_names:
            layer = self.get_layer_by_name(name)
            if layer is None:
                continue
            layer_el = ET.SubElement(root, "layer")
            layer_el.set("name", name)
            for child in layer.iterdescendants():
                nodes = self.node_locations(child)
                nodeList = []
                for node in nodes:
                    nodeList.append([node.x,node.y])
                if not nodes:
                    continue
                obj = ET.SubElement(layer_el, "object")
                obj.set("id", child.get("id") or "")
                obj.set("type", self.element_type(child))
                obj.set("isFilled", "true" if self.is_filled(child) else "false")
                obj.set("nodeLocation", json.dumps(nodeList))
        ET.indent(root, space="  ", level=0)
        return root

    def write_output(self, root, output_path):
        tree = ET.ElementTree(root)
        tree.write(output_path, encoding="utf-8", xml_declaration=True)

    def parse_svg_file(self, svg_path, output_path=None, layer_names=None):
        if layer_names is not None:
            self.layer_names = list(layer_names)
        self.document = load_svg(svg_path)
        self.svg = self.document.getroot()
        root = self.build_output()
        out_path = output_path or "parsed_layers.xml"
        self.write_output(root, out_path)
        return out_path

    def effect(self):
        root = self.build_output()
        self.write_output(root, self.options.output)


if __name__ == "__main__":
    '''
    cli = argparse.ArgumentParser(description="Parse SVG layers to XML.")
    cli.add_argument("svg_path", help="Input SVG file path")
    cli.add_argument("--output", default="parsed_layers.xml", help="Output XML path")
    cli.add_argument(
        "--layer",
        action="append",
        dest="layers",
        help="Layer name to include (repeatable). Defaults to 'substrate'.",
    )
    args = cli.parse_args()
    layers = args.layers if args.layers else ["substrate"]
    '''
    parser = SvgLayerParser()
    svgPath = "D:\OneDrive - purdue.edu\Research\Fluidic Logic\\automated design\\"
    svgFile = "2D_synthesis_test.svg"
    outFile = "3D_gen_instructions.xml"
    parser.parse_svg_file(svgPath+svgFile, output_path=svgPath+outFile, layer_names=["substrate", "fold_bottom"])
