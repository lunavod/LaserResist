"""Fill pattern generation for laser exposure."""

from typing import List, Union
from shapely.geometry import MultiPolygon, Polygon, LineString, GeometryCollection, Point, MultiLineString
from shapely import line_merge
from shapely.ops import voronoi_diagram, linemerge


class FillGenerator:
    """Generate fill patterns for polygon areas."""

    def __init__(self, line_spacing: float = 0.1):
        """Initialize the fill generator.

        Args:
            line_spacing: Spacing between fill lines in mm
        """
        self.line_spacing = line_spacing

    def generate_fill(self, geometry: Union[Polygon, MultiPolygon], trace_centerlines: List[LineString] = None) -> List[LineString]:
        """Generate fill lines for the given geometry using contour offset method.

        This algorithm creates concentric contours by repeatedly offsetting inward,
        allowing overlaps to ensure complete coverage without gaps.

        Args:
            geometry: Polygon or MultiPolygon of areas to fill
            trace_centerlines: Optional list of trace centerlines to add to fill

        Returns:
            List of LineString objects representing laser paths
        """
        paths = []

        # Normalize to MultiPolygon
        if isinstance(geometry, Polygon):
            geometry = MultiPolygon([geometry])

        # Start with the original geometry
        current_geom = geometry
        remaining_unfilled = None  # Track what's left after contours

        # Keep offsetting inward until nothing remains
        iteration = 0
        while not current_geom.is_empty:
            # Extract all boundaries from current geometry
            boundary_paths = self._extract_boundaries(current_geom)

            # Filter out degenerate geometries (points, very small fragments)
            boundary_paths = [p for p in boundary_paths if p.length > 0.01]  # Min 0.01mm
            paths.extend(boundary_paths)

            # Try to buffer inward
            next_geom = self._buffer_incremental(current_geom, self.line_spacing)

            # If buffering made it disappear or very small, add centerlines from current geometry
            # Only add centerlines when next buffer would eliminate most of the geometry
            current_area = self._get_total_area(current_geom)
            next_area = self._get_total_area(next_geom)

            if next_geom.is_empty or (current_area > 0 and next_area < current_area * 0.1):
                # Save the remaining unfilled geometry before adding centerlines
                remaining_unfilled = current_geom

                # Add centerlines for the remaining area (pads mostly)
                centerlines = self._extract_centerlines(current_geom)
                centerlines = [c for c in centerlines if c.length > 0.01]
                if centerlines:
                    print(f"  Adding {len(centerlines)} pad centerlines (iteration {iteration})")
                paths.extend(centerlines)
                break

            # Continue with the buffered geometry
            current_geom = next_geom
            iteration += 1

            # Safety limit to prevent infinite loops
            if iteration > 1000:
                print("Warning: Fill generation exceeded iteration limit")
                remaining_unfilled = current_geom
                break

        # Now add trace centerlines spanning full trace length
        # Clip them to slightly inward-buffered geometry to avoid the outer contour
        # but keep the full trace length from pad to pad
        if trace_centerlines:
            # Buffer inward by half line spacing to avoid overlapping the outermost contour
            interior_zone = geometry.buffer(-self.line_spacing * 0.5)
            if not interior_zone.is_empty:
                clipped_centerlines = self._clip_centerlines_to_geometry(trace_centerlines, interior_zone)
                print(f"  Adding {len(clipped_centerlines)} full-length trace centerlines (from {len(trace_centerlines)} original)")
                paths.extend(clipped_centerlines)
            else:
                # If interior is empty, geometry is too small, skip centerlines
                print(f"  Skipping trace centerlines (geometry too small)")

        return paths

    def _extract_boundaries(self, geometry: Union[Polygon, MultiPolygon]) -> List[LineString]:
        """Extract all boundary lines from geometry.

        Args:
            geometry: Polygon or MultiPolygon

        Returns:
            List of LineString representing boundaries
        """
        boundaries = []

        # Handle MultiPolygon
        if isinstance(geometry, MultiPolygon):
            for poly in geometry.geoms:
                boundaries.extend(self._extract_boundaries(poly))
        # Handle Polygon
        elif isinstance(geometry, Polygon):
            # Add exterior boundary
            if geometry.exterior:
                boundaries.append(LineString(geometry.exterior.coords))

            # Add interior boundaries (holes)
            for interior in geometry.interiors:
                boundaries.append(LineString(interior.coords))

        return boundaries

    def _buffer_incremental(self, geometry: Union[Polygon, MultiPolygon], distance: float) -> Union[Polygon, MultiPolygon, GeometryCollection]:
        """Buffer geometry inward by a negative offset incrementally.

        Args:
            geometry: Current geometry to buffer
            distance: Distance to offset inward (e.g., 0.1mm)

        Returns:
            Buffered geometry (may be empty, split, or merged)
        """
        # Negative buffer = inward offset from CURRENT geometry
        buffered = geometry.buffer(-distance)

        # Handle empty or invalid results
        if buffered.is_empty:
            return MultiPolygon()

        # Normalize to MultiPolygon for consistency
        if isinstance(buffered, Polygon):
            return MultiPolygon([buffered])
        elif isinstance(buffered, MultiPolygon):
            return buffered
        elif isinstance(buffered, GeometryCollection):
            # Extract only polygons from collection
            polys = [geom for geom in buffered.geoms if isinstance(geom, Polygon)]
            return MultiPolygon(polys) if polys else MultiPolygon()
        else:
            return MultiPolygon()

    def _is_too_thin(self, geometry: Union[Polygon, MultiPolygon], threshold: float) -> bool:
        """Check if geometry is too thin to buffer further.

        Args:
            geometry: Polygon or MultiPolygon
            threshold: Width threshold in mm

        Returns:
            True if any polygon is thinner than threshold
        """
        polygons = []
        if isinstance(geometry, MultiPolygon):
            polygons = list(geometry.geoms)
        elif isinstance(geometry, Polygon):
            polygons = [geometry]

        for poly in polygons:
            try:
                # Get minimum rotated rectangle
                min_rect = poly.minimum_rotated_rectangle
                coords = list(min_rect.exterior.coords)

                if len(coords) >= 5:
                    # Calculate side lengths
                    p0, p1, p2 = coords[0], coords[1], coords[2]
                    d01 = ((p1[0] - p0[0])**2 + (p1[1] - p0[1])**2)**0.5
                    d12 = ((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)**0.5

                    # Minimum of the two sides is the width
                    width = min(d01, d12)

                    # If width is less than threshold, it's too thin
                    if width < threshold:
                        return True
            except Exception:
                # If we can't determine, assume it's not too thin
                pass

        return False

    def _get_total_area(self, geometry: Union[Polygon, MultiPolygon]) -> float:
        """Get total area of geometry.

        Args:
            geometry: Polygon or MultiPolygon

        Returns:
            Total area in mm²
        """
        if isinstance(geometry, MultiPolygon):
            return sum(poly.area for poly in geometry.geoms)
        elif isinstance(geometry, Polygon):
            return geometry.area
        else:
            return 0.0

    def _extract_centerlines(self, geometry: Union[Polygon, MultiPolygon]) -> List[LineString]:
        """Extract centerlines from thin/small geometries.

        For narrow traces and small pads that can't be filled with more contours,
        this adds a centerline to ensure complete coverage.

        Args:
            geometry: Polygon or MultiPolygon

        Returns:
            List of centerline paths
        """
        centerlines = []

        # Handle MultiPolygon
        if isinstance(geometry, MultiPolygon):
            for poly in geometry.geoms:
                centerlines.extend(self._extract_centerlines(poly))
        # Handle Polygon
        elif isinstance(geometry, Polygon):
            # Use minimum rotated rectangle to find centerline
            try:
                min_rect = geometry.minimum_rotated_rectangle  # Fixed: was 'poly', should be 'geometry'
                coords = list(min_rect.exterior.coords)

                if len(coords) >= 5:  # Rectangle has 5 points (first == last)
                    p0, p1, p2, p3 = coords[0], coords[1], coords[2], coords[3]

                    # Calculate side lengths
                    d01 = ((p1[0] - p0[0])**2 + (p1[1] - p0[1])**2)**0.5
                    d12 = ((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)**0.5

                    # Find midpoints of the SHORT sides (perpendicular to the trace direction)
                    # The centerline connects these midpoints
                    if d01 > d12:  # d01 is long side, d12 is short side
                        # p1-p2 and p3-p0 are the short sides
                        mid1 = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
                        mid2 = ((p3[0] + p0[0]) / 2, (p3[1] + p0[1]) / 2)
                    else:  # d12 is long side, d01 is short side
                        # p0-p1 and p2-p3 are the short sides
                        mid1 = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
                        mid2 = ((p2[0] + p3[0]) / 2, (p2[1] + p3[1]) / 2)

                    # Create centerline
                    centerline = LineString([mid1, mid2])
                    if centerline.length > 0.01:  # Minimum useful length
                        centerlines.append(centerline)

            except Exception as e:
                # If we can't create a centerline, skip it
                print(f"Warning: centerline extraction failed: {e}")
                pass

        return centerlines

    def _clip_centerlines_to_geometry(self, centerlines: List[LineString], geometry: Union[Polygon, MultiPolygon]) -> List[LineString]:
        """Clip centerlines to only the parts within the geometry.

        This ensures centerlines don't extend into pads or outside copper areas.

        Args:
            centerlines: List of centerline paths
            geometry: Copper geometry to clip to

        Returns:
            List of clipped centerlines
        """
        clipped = []

        for line in centerlines:
            try:
                # Intersect the line with the geometry
                intersection = line.intersection(geometry)

                # Handle different result types
                if intersection.is_empty:
                    continue
                elif isinstance(intersection, LineString):
                    if intersection.length > 0.01:  # Min length threshold
                        clipped.append(intersection)
                elif isinstance(intersection, MultiLineString):
                    for segment in intersection.geoms:
                        if segment.length > 0.01:
                            clipped.append(segment)
                elif isinstance(intersection, GeometryCollection):
                    # Extract only LineStrings from the collection
                    for geom in intersection.geoms:
                        if isinstance(geom, LineString) and geom.length > 0.01:
                            clipped.append(geom)
                        elif isinstance(geom, MultiLineString):
                            for segment in geom.geoms:
                                if segment.length > 0.01:
                                    clipped.append(segment)
            except Exception as e:
                # If clipping fails, skip this centerline
                pass

        return clipped

    def _clip_centerlines_to_unfilled(self, centerlines: List[LineString], geometry: Union[Polygon, MultiPolygon], filled_area: Union[Polygon, MultiPolygon]) -> List[LineString]:
        """Clip centerlines to only unfilled areas (areas without contour coverage).

        Args:
            centerlines: List of centerline paths
            geometry: Original copper geometry
            filled_area: Areas already covered by contour fill

        Returns:
            List of clipped centerlines only in narrow/unfilled zones
        """
        # Calculate unfilled areas (geometry minus areas with good contour coverage)
        try:
            if filled_area.is_empty:
                # If no filled area, use full geometry
                unfilled = geometry
            else:
                # Unfilled = original geometry minus well-filled areas
                unfilled = geometry.difference(filled_area)
        except Exception:
            # If difference fails, fall back to full geometry
            unfilled = geometry

        # Now clip centerlines to only the unfilled areas
        return self._clip_centerlines_to_geometry(centerlines, unfilled)
