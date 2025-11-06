"""Gerber file parsing and geometry extraction."""

from pathlib import Path
from typing import List, Union, Optional
from shapely.geometry import Polygon, MultiPolygon, GeometryCollection, Point, LineString
from shapely.ops import unary_union
from gerbonara import GerberFile, ExcellonFile, MM
from gerbonara.graphic_primitives import Circle, Line as GerberLine


class GerberParser:
    """Parse Gerber files and extract copper geometry."""

    def __init__(self, file_path: Path, drill_pth_path: Optional[Path] = None, drill_via_path: Optional[Path] = None):
        """Initialize the parser with a Gerber file.

        Args:
            file_path: Path to the Gerber file
            drill_pth_path: Optional path to PTH (Plated Through Hole) drill file
            drill_via_path: Optional path to Via drill file
        """
        self.file_path = file_path
        self.drill_pth_path = drill_pth_path
        self.drill_via_path = drill_via_path
        self.layer: GerberFile = None
        self.polygons: List[Polygon] = []
        self.trace_centerlines: List[LineString] = []  # Store trace centerlines

    def parse(self) -> Union[MultiPolygon, Polygon]:
        """Parse the Gerber file and return copper geometry.

        Returns:
            MultiPolygon or Polygon representing all copper areas to be exposed
        """
        # Load the Gerber file using gerbonara
        self.layer = GerberFile.open(str(self.file_path))

        # Convert to shapely geometries
        # Each graphic object needs to be converted to primitives, then to arc polygons
        geometries = []
        self.trace_centerlines = []  # Reset centerlines

        # Iterate through all graphics objects in the layer
        for obj in self.layer.objects:
            try:
                # Convert object to primitives (unit: MM)
                primitives = obj.to_primitives(MM)

                # Convert each primitive to a Shapely polygon
                for prim in primitives:
                    # Special handling for Circle primitives (pads with circular apertures)
                    if isinstance(prim, Circle):
                        # Circles need to be created using Point.buffer()
                        # because to_arc_poly() only returns 2 points (diameter endpoints)
                        center = Point(prim.x, prim.y)
                        radius = prim.r
                        poly = center.buffer(radius)
                        if poly.is_valid and not poly.is_empty:
                            geometries.append(poly)
                    # Special handling for Line primitives (traces with circular apertures)
                    elif isinstance(prim, GerberLine):
                        # Lines should have circular caps for proper connectivity at angles
                        # Use LineString.buffer() to create proper rounded ends
                        line = LineString([(prim.x1, prim.y1), (prim.x2, prim.y2)])
                        # Buffer by half the line width (radius) with round caps
                        width = prim.width if hasattr(prim, 'width') else 0.1
                        radius = width / 2
                        poly = line.buffer(radius, cap_style='round', join_style='round')
                        if poly.is_valid and not poly.is_empty:
                            geometries.append(poly)

                        # Also store the centerline for later use in fill generation
                        if line.length > 0.01:  # Only meaningful lines
                            self.trace_centerlines.append(line)
                    else:
                        # For other primitives, convert to arc polygon
                        arc_poly = prim.to_arc_poly()

                        # Get the outline points
                        if arc_poly.outline and len(arc_poly.outline) >= 3:
                            # Create a Shapely polygon from the outline
                            poly = Polygon(arc_poly.outline)
                            if poly.is_valid and not poly.is_empty:
                                geometries.append(poly)

            except Exception as e:
                # Skip objects we can't convert
                print(f"Warning: Could not convert object {type(obj).__name__}: {e}")
                pass

        # Merge all geometries into a single MultiPolygon
        if not geometries:
            return MultiPolygon()

        # Union all geometries to merge overlapping areas
        unified = unary_union(geometries)

        # Parse drill files and subtract holes from copper
        holes = self._parse_drill_holes()
        if holes and not holes.is_empty:
            # Subtract holes from the unified copper geometry
            unified = unified.difference(holes)

        # Ensure we return a MultiPolygon or Polygon
        if isinstance(unified, (Polygon, MultiPolygon)):
            return unified
        elif isinstance(unified, GeometryCollection):
            # Extract only polygons from the collection
            polys = [geom for geom in unified.geoms if isinstance(geom, Polygon)]
            if not polys:
                return MultiPolygon()
            return MultiPolygon(polys)
        else:
            return MultiPolygon()

    def _parse_drill_holes(self) -> Union[MultiPolygon, Polygon, None]:
        """Parse drill files and create hole geometry.

        Returns:
            MultiPolygon of all drill holes, or None if no drill files
        """
        hole_circles = []

        # Parse PTH drill file
        if self.drill_pth_path and self.drill_pth_path.exists():
            try:
                drill_file = ExcellonFile.open(str(self.drill_pth_path))
                for obj in drill_file.objects:
                    # Each drill object has x, y coordinates and tool (which has diameter)
                    if hasattr(obj, 'x') and hasattr(obj, 'y') and hasattr(obj, 'tool'):
                        x = obj.x
                        y = obj.y
                        # Tool diameter is the hole diameter
                        diameter = obj.tool.diameter if obj.tool and hasattr(obj.tool, 'diameter') else 0
                        if diameter > 0:
                            radius = diameter / 2
                            hole = Point(x, y).buffer(radius)
                            hole_circles.append(hole)
            except Exception as e:
                print(f"Warning: Could not parse PTH drill file: {e}")

        # Parse Via drill file
        if self.drill_via_path and self.drill_via_path.exists():
            try:
                drill_file = ExcellonFile.open(str(self.drill_via_path))
                for obj in drill_file.objects:
                    if hasattr(obj, 'x') and hasattr(obj, 'y') and hasattr(obj, 'tool'):
                        x = obj.x
                        y = obj.y
                        diameter = obj.tool.diameter if obj.tool and hasattr(obj.tool, 'diameter') else 0
                        if diameter > 0:
                            radius = diameter / 2
                            hole = Point(x, y).buffer(radius)
                            hole_circles.append(hole)
            except Exception as e:
                print(f"Warning: Could not parse Via drill file: {e}")

        # Union all holes
        if not hole_circles:
            return None

        return unary_union(hole_circles)

    def get_bounds(self) -> tuple:
        """Get the bounding box of the parsed geometry.

        Returns:
            Tuple of (min_x, min_y, max_x, max_y) in mm
        """
        if self.layer is None:
            raise ValueError("Must call parse() before get_bounds()")

        bbox = self.layer.bounding_box()
        if bbox is None:
            return (0, 0, 0, 0)

        # gerbonara returns ((min_x, min_y), (max_x, max_y))
        # Flatten to (min_x, min_y, max_x, max_y)
        (min_x, min_y), (max_x, max_y) = bbox
        return (min_x, min_y, max_x, max_y)

    @staticmethod
    def parse_board_outline(outline_path: Path) -> tuple:
        """Parse a board outline Gerber file and return its bounding box.

        Args:
            outline_path: Path to the board outline Gerber file (.gko, .gm1, etc.)

        Returns:
            Tuple of (min_x, min_y, max_x, max_y) in mm
        """
        try:
            outline_layer = GerberFile.open(str(outline_path))
            bbox = outline_layer.bounding_box()

            if bbox is None:
                return (0, 0, 0, 0)

            # gerbonara returns ((min_x, min_y), (max_x, max_y))
            (min_x, min_y), (max_x, max_y) = bbox
            return (min_x, min_y, max_x, max_y)

        except Exception as e:
            print(f"Warning: Could not parse board outline: {e}")
            return (0, 0, 0, 0)

    def get_trace_centerlines(self) -> List[LineString]:
        """Get the centerlines of all trace lines.

        Returns:
            List of LineString centerlines from trace objects
        """
        return self.trace_centerlines
