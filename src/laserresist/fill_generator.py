"""Fill pattern generation for laser exposure."""

from typing import List, Union
from shapely.geometry import MultiPolygon, Polygon, LineString, GeometryCollection, Point, MultiLineString
from shapely import line_merge
from shapely.ops import voronoi_diagram, linemerge, substring


class FillGenerator:
    """Generate fill patterns for polygon areas."""

    def __init__(self, line_spacing: float = 0.1):
        """Initialize the fill generator.

        Args:
            line_spacing: Spacing between fill lines in mm
        """
        self.line_spacing = line_spacing

    def generate_fill(self, geometry: Union[Polygon, MultiPolygon], trace_centerlines: List[LineString] = None, offset_centerlines: bool = False) -> List[LineString]:
        """Generate fill lines for the given geometry using contour offset method.

        This algorithm creates concentric contours by repeatedly offsetting inward,
        allowing overlaps to ensure complete coverage without gaps.

        Args:
            geometry: Polygon or MultiPolygon of areas to fill
            trace_centerlines: Optional list of trace centerlines to add to fill
            offset_centerlines: If True, offset centerlines from both ends by line_spacing (default: False)

        Returns:
            List of LineString objects representing laser paths
        """
        paths = []
        contour_paths = []  # Track contours separately for centerline clipping

        # Normalize to MultiPolygon
        if isinstance(geometry, Polygon):
            geometry = MultiPolygon([geometry])

        # Start with the original geometry
        current_geom = geometry
        remaining_unfilled = None  # Track what's left after contours

        # Detect thin annular pads from the ORIGINAL geometry before any buffering
        thin_annular_rings = self._detect_thin_annular_pads_at_start(geometry)
        if thin_annular_rings:
            print(f"  Adding {len(thin_annular_rings)} circles for thin annular pads")
            paths.extend(thin_annular_rings)
            contour_paths.extend(thin_annular_rings)

        # Keep offsetting inward until nothing remains
        iteration = 0
        while not current_geom.is_empty:
            # Extract all boundaries from current geometry
            boundary_paths = self._extract_boundaries(current_geom)

            # Filter out degenerate geometries (points, very small fragments)
            boundary_paths = [p for p in boundary_paths if p.length > 0.01]  # Min 0.01mm
            paths.extend(boundary_paths)
            contour_paths.extend(boundary_paths)  # Track for centerline clipping

            # Try to buffer inward
            next_geom = self._buffer_incremental(current_geom, self.line_spacing)

            # If buffering made it disappear or very small, add centerlines for remaining area
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
                contour_paths.extend(centerlines)  # These also count as filled areas
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
        # Clip them to avoid areas already filled by contours
        if trace_centerlines:
            # Create a "filled zone" from all contour paths
            # Buffer each contour by half line spacing to represent the laser spot coverage
            filled_zone = self._create_filled_zone(contour_paths, self.line_spacing / 2.0)

            if not filled_zone.is_empty:
                # Clip centerlines to avoid the filled zones
                clipped_centerlines = self._clip_centerlines_avoiding_filled_zones(
                    trace_centerlines, geometry, filled_zone, offset_centerlines
                )
                offset_msg = " with end offsets" if offset_centerlines else ""
                print(f"  Adding {len(clipped_centerlines)} trace centerlines{offset_msg} avoiding filled zones (from {len(trace_centerlines)} original)")
                paths.extend(clipped_centerlines)
            else:
                # If no filled zone, use the original geometry clipping
                interior_zone = geometry.buffer(-self.line_spacing * 0.5)
                if not interior_zone.is_empty:
                    clipped_centerlines = self._clip_centerlines_to_geometry(trace_centerlines, interior_zone)
                    print(f"  Adding {len(clipped_centerlines)} trace centerlines (from {len(trace_centerlines)} original)")
                    paths.extend(clipped_centerlines)

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

    def _create_filled_zone(self, contour_paths: List[LineString], buffer_distance: float) -> Union[Polygon, MultiPolygon]:
        """Create a filled zone from contour paths by buffering them.

        This represents areas that are already covered by contour fills.

        Args:
            contour_paths: List of contour LineStrings
            buffer_distance: Distance to buffer each path (usually half line spacing)

        Returns:
            Union of all buffered contours representing filled areas
        """
        if not contour_paths:
            return MultiPolygon()

        try:
            # Buffer each contour path to represent laser coverage area
            buffered = []
            for path in contour_paths:
                if path.length > 0.01:  # Skip very short paths
                    buf = path.buffer(buffer_distance, cap_style='round', join_style='round')
                    if not buf.is_empty:
                        buffered.append(buf)

            if not buffered:
                return MultiPolygon()

            # Union all buffered areas
            from shapely.ops import unary_union
            filled_zone = unary_union(buffered)

            return filled_zone

        except Exception as e:
            print(f"Warning: Failed to create filled zone: {e}")
            return MultiPolygon()

    def _clip_centerlines_avoiding_filled_zones(
        self,
        centerlines: List[LineString],
        original_geometry: Union[Polygon, MultiPolygon],
        filled_zone: Union[Polygon, MultiPolygon],
        offset_ends: bool = False
    ) -> List[LineString]:
        """Clip trace centerlines to avoid areas already filled by contours.

        This ensures centerlines only traverse narrow trace corridors between pads.
        Optionally offsets the centerlines from both ends by line_spacing to create a gap.

        Args:
            centerlines: Original trace centerlines
            original_geometry: Original copper geometry
            filled_zone: Areas already covered by contour fills
            offset_ends: If True, offset centerlines from both ends by line_spacing

        Returns:
            List of clipped and optionally offset centerlines that avoid filled zones
        """
        clipped = []
        # Set minimum length threshold based on whether we're offsetting
        min_length_threshold = self.line_spacing * 2.5 if offset_ends else 0.01

        for line in centerlines:
            try:
                # Calculate the unfilled corridor where the centerline should go
                # This is the original geometry minus the filled zones
                unfilled_corridor = original_geometry.difference(filled_zone)

                if unfilled_corridor.is_empty:
                    continue

                # Intersect the centerline with the unfilled corridor
                intersection = line.intersection(unfilled_corridor)

                # Collect segments to process
                segments = []
                if intersection.is_empty:
                    continue
                elif isinstance(intersection, LineString):
                    segments.append(intersection)
                elif isinstance(intersection, MultiLineString):
                    segments.extend(intersection.geoms)
                elif isinstance(intersection, GeometryCollection):
                    # Extract only LineStrings from the collection
                    for geom in intersection.geoms:
                        if isinstance(geom, LineString):
                            segments.append(geom)
                        elif isinstance(geom, MultiLineString):
                            segments.extend(geom.geoms)

                # Process each segment: optionally offset from both ends and check length
                for segment in segments:
                    if offset_ends:
                        trimmed = self._offset_line_from_ends(segment, self.line_spacing)
                        if trimmed and trimmed.length >= min_length_threshold:
                            clipped.append(trimmed)
                    else:
                        # No offsetting, just check minimum length
                        if segment.length >= min_length_threshold:
                            clipped.append(segment)

            except Exception as e:
                # If clipping fails, skip this centerline
                print(f"Warning: Failed to clip centerline: {e}")
                pass

        return clipped

    def _offset_line_from_ends(self, line: LineString, offset: float) -> LineString:
        """Offset a line from both ends by the specified distance.

        Args:
            line: Original LineString
            offset: Distance to trim from each end

        Returns:
            Trimmed LineString, or None if the line is too short
        """
        try:
            total_length = line.length

            # If line is too short to offset, return None
            if total_length <= offset * 2:
                return None

            # Get points at offset distance from start and end
            start_point = line.interpolate(offset)
            end_point = line.interpolate(total_length - offset)

            # Create new line from trimmed points
            # We need to extract the subsegment between these two points
            start_dist = offset
            end_dist = total_length - offset

            # Create a substring of the line
            trimmed_line = substring(line, start_dist, end_dist)

            return trimmed_line

        except Exception as e:
            # If offsetting fails, return None
            return None

    def _detect_thin_annular_pads_at_start(self, geometry: Union[Polygon, MultiPolygon]) -> List[LineString]:
        """Detect thin annular pads from the ORIGINAL geometry and generate circular centerlines.

        Specifically targets small circular pads with holes where ring_width is between
        line_spacing and 2*line_spacing (only fits one contour, but middle is empty).

        Args:
            geometry: Original unmodified geometry

        Returns:
            List of circular centerlines for thin rings
        """
        from shapely.geometry import Point
        from math import pi, cos, sin

        rings = []

        # Normalize to list of polygons
        polys = list(geometry.geoms) if hasattr(geometry, 'geoms') else [geometry]

        for poly in polys:
            if not isinstance(poly, Polygon):
                continue

            # MUST have interior ring (hole)
            if len(poly.interiors) == 0:
                continue

            # Get bounds to check if it's small and circular
            bounds = poly.bounds
            width = bounds[2] - bounds[0]
            height = bounds[3] - bounds[1]

            # Skip large pads - only look at small ones
            pad_size = max(width, height)
            if pad_size > 4.0:  # Skip pads larger than 4mm
                continue

            # Must be circular (very strict check)
            aspect_ratio = max(width, height) / (min(width, height) + 0.001)
            if aspect_ratio > 1.15:  # Very strict - must be nearly circular
                continue

            # Get the exterior and first interior ring
            exterior = poly.exterior
            interior = poly.interiors[0]

            centroid = poly.centroid

            # Calculate average radius from centroid to exterior and interior
            ext_coords = list(exterior.coords)
            int_coords = list(interior.coords)

            outer_distances = [Point(x, y).distance(centroid) for x, y in ext_coords]
            inner_distances = [Point(x, y).distance(centroid) for x, y in int_coords]

            outer_radius = sum(outer_distances) / len(outer_distances)
            inner_radius = sum(inner_distances) / len(inner_distances)

            # Calculate ring width (annular pad width)
            ring_width = outer_radius - inner_radius

            # ONLY process if ring width is between line_spacing and 2*line_spacing
            # This is the exact problem: only 1 contour fits, middle is empty
            if not (self.line_spacing < ring_width < 2 * self.line_spacing):
                continue

            # Generate a circular centerline at the midpoint radius
            mid_radius = (outer_radius + inner_radius) / 2.0

            # Create smooth circle
            num_points = max(16, int(2 * pi * mid_radius / (self.line_spacing / 2)))
            coords = []
            for i in range(num_points + 1):  # +1 to close the circle
                angle = 2 * pi * i / num_points
                x = centroid.x + mid_radius * cos(angle)
                y = centroid.y + mid_radius * sin(angle)
                coords.append((x, y))

            if len(coords) >= 2:
                try:
                    ring_centerline = LineString(coords)
                    rings.append(ring_centerline)
                except:
                    pass

        return rings
