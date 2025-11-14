"""Fill pattern generation for laser exposure."""

from typing import List, Union, Dict
from shapely.geometry import MultiPolygon, Polygon, LineString, GeometryCollection, Point, MultiLineString
from shapely import line_merge
from shapely.ops import voronoi_diagram, linemerge, substring


class FillGenerator:
    """Generate fill patterns for polygon areas."""

    def __init__(self, line_spacing: float = 0.1, initial_offset: float = 0.05, forced_pad_centerlines: bool = False, force_trace_centerlines: bool = False, force_trace_centerlines_max_thickness: float = 0.0, double_expose_isolated: bool = False, isolation_threshold: float = 3.0):
        """Initialize the fill generator.

        Args:
            line_spacing: Spacing between fill lines in mm
            initial_offset: Initial inward offset of outer boundaries to compensate for laser dot size in mm (default: 0.05)
                          This shrinks the outermost contour while keeping internal fill structure unchanged.
            forced_pad_centerlines: Add centerlines to all pads regardless of size (default: False)
            force_trace_centerlines: Force all trace centerlines without clipping to avoid filled zones (default: False)
            force_trace_centerlines_max_thickness: Max thickness for forced trace centerlines. 0 = all traces, >0 = only traces <= this thickness (default: 0.0)
            double_expose_isolated: Enable double exposure for isolated features (default: False)
            isolation_threshold: Distance in mm - features with no copper within this radius are "isolated" (default: 3.0)
        """
        self.line_spacing = line_spacing
        self.initial_offset = initial_offset
        self.forced_pad_centerlines = forced_pad_centerlines
        self.force_trace_centerlines = force_trace_centerlines
        self.force_trace_centerlines_max_thickness = force_trace_centerlines_max_thickness
        self.double_expose_isolated = double_expose_isolated
        self.isolation_threshold = isolation_threshold

    def generate_fill(self, geometry: Union[Polygon, MultiPolygon], trace_centerlines: List[dict] = None, offset_centerlines: bool = False, pads: List[dict] = None, drill_holes: Union[Polygon, MultiPolygon] = None) -> Union[List[LineString], Dict[str, List[LineString]]]:
        """Generate fill lines for the given geometry using contour offset method.

        This algorithm creates concentric contours by repeatedly offsetting inward,
        allowing overlaps to ensure complete coverage without gaps.

        Args:
            geometry: Polygon or MultiPolygon of areas to fill
            trace_centerlines: Optional list of trace centerline dicts with 'line' and 'width' keys
            offset_centerlines: If True, offset centerlines from both ends by line_spacing (default: False)
            pads: Optional list of pad geometries with aperture info
            drill_holes: Optional polygon of drill holes to subtract from geometry

        Returns:
            List of LineString objects representing laser paths, or dict with 'normal' and 'isolated' keys if double_expose_isolated is enabled
        """
        paths = []
        contour_paths = []  # Track contours separately for centerline clipping

        # Normalize to MultiPolygon
        if isinstance(geometry, Polygon):
            geometry = MultiPolygon([geometry])

        # Detect thin annular pads from the ORIGINAL geometry before any buffering
        original_geometry = geometry
        thin_annular_rings = self._detect_thin_annular_pads_at_start(original_geometry)

        # Junction detection disabled - was catching pads instead of actual junctions
        # TODO: Need better approach to detect Y/T junction gaps
        junction_fills = []

        # Add forced pad centerlines if requested
        forced_pad_paths = []
        if self.forced_pad_centerlines:
            forced_pad_paths = self._generate_forced_pad_centerlines(pads, drill_holes, thin_annular_rings)
            if forced_pad_paths:
                print(f"  Adding {len(forced_pad_paths)} forced pad centerlines")
                paths.extend(forced_pad_paths)
                contour_paths.extend(forced_pad_paths)

        # Start with the original geometry
        current_geom = geometry
        remaining_unfilled = None  # Track what's left after contours
        if thin_annular_rings:
            print(f"  Adding {len(thin_annular_rings)} circles for thin annular pads")
            paths.extend(thin_annular_rings)
            contour_paths.extend(thin_annular_rings)

        # Add tiny junction fills
        if junction_fills:
            print(f"  Adding {len(junction_fills)} fills for tiny junction polygons")
            paths.extend(junction_fills)
            contour_paths.extend(junction_fills)

        # Keep offsetting inward until nothing remains
        iteration = 0
        while not current_geom.is_empty:
            # For the first iteration, apply initial_offset inward to the boundaries
            # This compensates for laser dot size on the outer edges
            if iteration == 0 and self.initial_offset > 0:
                # Buffer inward to account for laser dot size
                offset_geom = current_geom.buffer(-self.initial_offset)
                if not offset_geom.is_empty:
                    # Extract boundaries from the offset geometry
                    boundary_paths = self._extract_boundaries(offset_geom)
                else:
                    # If offset makes it disappear, use original
                    boundary_paths = self._extract_boundaries(current_geom)
            else:
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

        # Gap detection disabled - needs refinement to avoid over-filling pads
        # gap_fills = self._detect_and_fill_gaps(geometry, paths)
        # if gap_fills:
        #     print(f"  Adding {len(gap_fills)} gap fills for unfilled copper areas")
        #     paths.extend(gap_fills)

        # Now add trace centerlines spanning full trace length
        # Clip them to avoid areas already filled by contours (unless force_trace_centerlines is True)
        if trace_centerlines:
            if self.force_trace_centerlines:
                # Force mode: add all trace centerlines without clipping
                # Filter by thickness if max_thickness is set
                filtered_centerlines = []
                for tc_dict in trace_centerlines:
                    line = tc_dict['line']
                    width = tc_dict['width']
                    # Apply thickness filter: 0 = all traces, >0 = only traces <= max_thickness
                    if self.force_trace_centerlines_max_thickness <= 0 or width <= self.force_trace_centerlines_max_thickness:
                        filtered_centerlines.append(line)

                # Optionally offset from ends if requested
                if offset_centerlines:
                    processed_centerlines = []
                    for line in filtered_centerlines:
                        trimmed = self._offset_line_from_ends(line, self.line_spacing)
                        if trimmed and trimmed.length >= self.line_spacing * 2.5:
                            processed_centerlines.append(trimmed)
                    offset_msg = " with end offsets"
                else:
                    processed_centerlines = [line for line in filtered_centerlines if line.length > 0.01]
                    offset_msg = ""

                thickness_msg = f" (<= {self.force_trace_centerlines_max_thickness}mm)" if self.force_trace_centerlines_max_thickness > 0 else ""
                print(f"  Adding {len(processed_centerlines)} forced trace centerlines{offset_msg}{thickness_msg} (unclipped, from {len(trace_centerlines)} total)")
                paths.extend(processed_centerlines)
            else:
                # Normal mode: clip centerlines to avoid filled zones
                # Extract LineStrings from trace_centerlines dicts
                centerline_lines = [tc_dict['line'] for tc_dict in trace_centerlines]

                # Create a "filled zone" from all contour paths
                # Buffer each contour by half line spacing to represent the laser spot coverage
                filled_zone = self._create_filled_zone(contour_paths, self.line_spacing / 2.0)

                if not filled_zone.is_empty:
                    # Clip centerlines to avoid the filled zones
                    clipped_centerlines = self._clip_centerlines_avoiding_filled_zones(
                        centerline_lines, geometry, filled_zone, offset_centerlines
                    )
                    offset_msg = " with end offsets" if offset_centerlines else ""
                    print(f"  Adding {len(clipped_centerlines)} trace centerlines{offset_msg} avoiding filled zones (from {len(trace_centerlines)} original)")
                    paths.extend(clipped_centerlines)
                else:
                    # If no filled zone, use the original geometry clipping
                    interior_zone = geometry.buffer(-self.line_spacing * 0.5)
                    if not interior_zone.is_empty:
                        clipped_centerlines = self._clip_centerlines_to_geometry(centerline_lines, interior_zone)
                        print(f"  Adding {len(clipped_centerlines)} trace centerlines (from {len(trace_centerlines)} original)")
                        paths.extend(clipped_centerlines)

        # Separate isolated paths if requested
        if self.double_expose_isolated and self.isolation_threshold > 0:
            normal_paths, isolated_paths = self._separate_isolated_paths(paths, geometry)
            print(f"  Isolated feature detection: {len(isolated_paths)} isolated paths, {len(normal_paths)} normal paths")
            return {
                'normal': normal_paths,
                'isolated': isolated_paths
            }
        else:
            return paths

    def _separate_isolated_paths(self, paths: List[LineString], full_geometry: Union[Polygon, MultiPolygon]) -> tuple:
        """Separate paths into normal and isolated based on proximity to other copper.

        Args:
            paths: List of all paths
            full_geometry: The complete copper geometry

        Returns:
            Tuple of (normal_paths, isolated_paths)
        """
        normal_paths = []
        isolated_paths = []

        for path in paths:
            if self._is_path_isolated(path, full_geometry):
                isolated_paths.append(path)
            else:
                normal_paths.append(path)

        return normal_paths, isolated_paths

    def _is_path_isolated(self, path: LineString, full_geometry: Union[Polygon, MultiPolygon]) -> bool:
        """Check if a path is isolated (far from other copper).

        A path is considered isolated if the area around it (within isolation_threshold)
        has low copper density.

        Args:
            path: The path to check
            full_geometry: The complete copper geometry

        Returns:
            True if path is isolated, False otherwise
        """
        # Buffer the path by the isolation threshold to create a search zone
        search_zone = path.buffer(self.isolation_threshold)

        # Find what portion of the search zone contains copper
        copper_in_zone = search_zone.intersection(full_geometry)

        # Calculate the copper density in the search zone
        if search_zone.area > 0:
            copper_density = copper_in_zone.area / search_zone.area
            # Consider isolated if copper density is low (< 20%)
            # This means most of the area around the path is empty
            return copper_density < 0.20

        return False

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

    def _generate_forced_pad_centerlines(self, pads: List[dict], drill_holes: Union[Polygon, MultiPolygon, None], existing_thin_rings: List[LineString]) -> List[LineString]:
        """Generate forced centerlines for all pads using actual pad info from Gerber.

        Args:
            pads: List of pad dictionaries from GerberParser.get_pads()
            drill_holes: Drill hole geometry to subtract from pads
            existing_thin_rings: List of already-generated thin annular pad circles to avoid duplication

        Returns:
            List of LineString centerlines for pads
        """
        from shapely.geometry import Point, MultiLineString
        from math import pi, cos, sin

        if not pads:
            return []

        centerlines = []

        # Track which pads already have thin ring circles to avoid duplicates
        existing_ring_centroids = []
        if existing_thin_rings:
            for ring in existing_thin_rings:
                coords = list(ring.coords)
                if coords:
                    center_x = sum(x for x, y in coords) / len(coords)
                    center_y = sum(y for x, y in coords) / len(coords)
                    existing_ring_centroids.append((center_x, center_y))

        for pad in pads:
            aperture_type = pad['aperture_type']
            position = pad['position']

            # Check if duplicate (already has thin ring)
            is_duplicate = False
            for ex_x, ex_y in existing_ring_centroids:
                if abs(position[0] - ex_x) < 0.1 and abs(position[1] - ex_y) < 0.1:
                    is_duplicate = True
                    break

            if is_duplicate:
                continue

            # Start with the original pad geometry
            poly = pad['geometry']

            # Subtract any drill holes that intersect this pad
            if drill_holes and not drill_holes.is_empty:
                poly = poly.difference(drill_holes)

            # Apply initial offset inward (same as for outer contours)
            if self.initial_offset > 0:
                poly = poly.buffer(-self.initial_offset)

            # Handle case where operations return GeometryCollection, MultiPolygon, or empty
            if poly.is_empty:
                continue
            if not isinstance(poly, Polygon):
                # If we got a MultiPolygon or GeometryCollection, take the largest polygon
                if hasattr(poly, 'geoms'):
                    polys = [g for g in poly.geoms if isinstance(g, Polygon)]
                    if not polys:
                        continue
                    poly = max(polys, key=lambda p: p.area)
                else:
                    continue

            has_hole = len(poly.interiors) > 0
            centroid = poly.centroid
            bounds = poly.bounds

            if aperture_type == 'circle':
                if has_hole:
                    # Donut pad - add circle in middle of ring
                    exterior = poly.exterior
                    interior = poly.interiors[0]

                    ext_coords = list(exterior.coords)
                    int_coords = list(interior.coords)

                    outer_distances = [Point(x, y).distance(centroid) for x, y in ext_coords]
                    inner_distances = [Point(x, y).distance(centroid) for x, y in int_coords]

                    outer_radius = sum(outer_distances) / len(outer_distances)
                    inner_radius = sum(inner_distances) / len(inner_distances)

                    mid_radius = (outer_radius + inner_radius) / 2.0

                    # Generate circle
                    num_points = max(16, int(2 * pi * mid_radius / (self.line_spacing / 2)))
                    coords = []
                    for i in range(num_points + 1):
                        angle = 2 * pi * i / num_points
                        x = centroid.x + mid_radius * cos(angle)
                        y = centroid.y + mid_radius * sin(angle)
                        coords.append((x, y))

                    if len(coords) >= 2:
                        try:
                            centerlines.append(LineString(coords))
                        except:
                            pass
                else:
                    # Circular pad without hole - add circle at radius/2
                    exterior_coords = list(poly.exterior.coords)
                    distances = [Point(x, y).distance(centroid) for x, y in exterior_coords]
                    radius = sum(distances) / len(distances)

                    circle_radius = radius / 2.0

                    num_points = max(16, int(2 * pi * circle_radius / (self.line_spacing / 2)))
                    coords = []
                    for i in range(num_points + 1):
                        angle = 2 * pi * i / num_points
                        x = centroid.x + circle_radius * cos(angle)
                        y = centroid.y + circle_radius * sin(angle)
                        coords.append((x, y))

                    if len(coords) >= 2:
                        try:
                            centerlines.append(LineString(coords))
                        except:
                            pass

            elif aperture_type == 'rectangle':
                # Rectangular pad - add AXIS-ALIGNED + from center
                try:
                    cx, cy = centroid.x, centroid.y

                    # Horizontal line through center
                    h_line = LineString([(bounds[0], cy), (bounds[2], cy)])
                    # Vertical line through center
                    v_line = LineString([(cx, bounds[1]), (cx, bounds[3])])

                    # Clip to actual pad geometry (handles holes)
                    h_clipped = h_line.intersection(poly)
                    v_clipped = v_line.intersection(poly)

                    # Add valid segments
                    for clipped in [h_clipped, v_clipped]:
                        if clipped.is_empty:
                            continue
                        elif isinstance(clipped, LineString):
                            if clipped.length > 0.01:
                                centerlines.append(clipped)
                        elif isinstance(clipped, MultiLineString):
                            for segment in clipped.geoms:
                                if segment.length > 0.01:
                                    centerlines.append(segment)
                except:
                    pass

        return centerlines

    def _detect_tiny_junction_polygons(self, geometry: Union[Polygon, MultiPolygon]) -> List[LineString]:
        """Detect and fill ONLY very small polygons at multi-trace junctions.

        Very conservative detection to avoid overfilling pads. Only processes tiny polygons
        (< 5 mm²) with holes, which are likely Y/T junction intersections.

        Args:
            geometry: Original unmodified geometry

        Returns:
            List of fill paths for tiny junction polygons
        """
        from shapely.geometry import Point
        from math import pi, cos, sin

        junction_fills = []

        # Normalize to list of polygons
        polys = list(geometry.geoms) if hasattr(geometry, 'geoms') else [geometry]

        for poly in polys:
            if not isinstance(poly, Polygon):
                continue

            # MUST have interior ring (hole)
            if len(poly.interiors) == 0:
                continue

            # Get polygon characteristics
            bounds = poly.bounds
            width = bounds[2] - bounds[0]
            height = bounds[3] - bounds[1]
            area = poly.area

            # Calculate hole areas
            hole_areas = []
            for interior in poly.interiors:
                hole_poly = Polygon(interior.coords)
                hole_areas.append(hole_poly.area)

            total_hole_area = sum(hole_areas)

            # VERY conservative detection: only tiny polygons with irregular shapes
            # Most pads are > 3mm², so limiting to < 3mm² catches junctions but not pads

            aspect_ratio = max(width, height) / (min(width, height) + 0.001)
            hole_ratio = total_hole_area / (area + total_hole_area) if (area + total_hole_area) > 0 else 0

            is_junction = (
                area < 3.0 and  # VERY small only (< 3 mm²)
                aspect_ratio < 2.0 and  # Roughly square
                hole_ratio > 0.05  # Has a hole (> 5%)
            )

            if not is_junction:
                continue

            # This is a junction polygon - add proper fill patterns
            # Strategy: Fill with contour offsets like the main algorithm, but for this small area

            # Apply initial offset to match main fill behavior
            fill_poly = poly.buffer(-self.initial_offset) if self.initial_offset > 0 else poly

            if fill_poly.is_empty or fill_poly.area < 0.01:
                continue

            # Generate contour fills for this junction polygon
            current = fill_poly
            iteration = 0
            max_iterations = 20  # Safety limit for small polygons

            while not current.is_empty and iteration < max_iterations:
                # Extract boundaries
                try:
                    if isinstance(current, Polygon):
                        # Add exterior boundary
                        if current.exterior and len(current.exterior.coords) >= 3:
                            boundary = LineString(current.exterior.coords)
                            if boundary.length > 0.01:
                                junction_fills.append(boundary)

                        # Add interior boundaries (holes)
                        for interior in current.interiors:
                            if len(interior.coords) >= 3:
                                boundary = LineString(interior.coords)
                                if boundary.length > 0.01:
                                    junction_fills.append(boundary)

                    elif isinstance(current, MultiPolygon):
                        for p in current.geoms:
                            if p.exterior and len(p.exterior.coords) >= 3:
                                boundary = LineString(p.exterior.coords)
                                if boundary.length > 0.01:
                                    junction_fills.append(boundary)
                            for interior in p.interiors:
                                if len(interior.coords) >= 3:
                                    boundary = LineString(interior.coords)
                                    if boundary.length > 0.01:
                                        junction_fills.append(boundary)

                    # Buffer inward
                    next_current = current.buffer(-self.line_spacing)

                    # Check if we should stop
                    if next_current.is_empty:
                        # Add centerline for remaining area
                        try:
                            min_rect = current.minimum_rotated_rectangle if isinstance(current, Polygon) else current
                            if isinstance(min_rect, Polygon):
                                coords = list(min_rect.exterior.coords)
                                if len(coords) >= 5:
                                    p0, p1, p2, p3 = coords[0], coords[1], coords[2], coords[3]
                                    d01 = ((p1[0] - p0[0])**2 + (p1[1] - p0[1])**2)**0.5
                                    d12 = ((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)**0.5

                                    if d01 > d12:
                                        mid1 = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
                                        mid2 = ((p3[0] + p0[0]) / 2, (p3[1] + p0[1]) / 2)
                                    else:
                                        mid1 = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
                                        mid2 = ((p2[0] + p3[0]) / 2, (p2[1] + p3[1]) / 2)

                                    centerline = LineString([mid1, mid2])
                                    if centerline.length > 0.01:
                                        junction_fills.append(centerline)
                        except:
                            pass
                        break

                    current = next_current
                    iteration += 1

                except Exception:
                    break

        return junction_fills

    def _generate_crosshatch_fill(self, geometry: Union[Polygon, MultiPolygon], spacing: float) -> List[LineString]:
        """Generate dense crosshatch pattern for small remaining areas.

        Creates a grid of horizontal and vertical lines to ensure complete coverage
        of small gaps at junctions that the contour fill might miss.

        Args:
            geometry: Small remaining unfilled geometry
            spacing: Line spacing for the crosshatch (typically smaller than main line_spacing)

        Returns:
            List of crosshatch fill lines
        """
        fills = []

        # Normalize to list of polygons
        polys = list(geometry.geoms) if hasattr(geometry, 'geoms') else [geometry]

        for poly in polys:
            if not isinstance(poly, Polygon) or poly.is_empty:
                continue

            bounds = poly.bounds
            min_x, min_y, max_x, max_y = bounds

            # Generate horizontal lines
            y = min_y
            while y <= max_y:
                line = LineString([(min_x - spacing, y), (max_x + spacing, y)])
                # Clip to polygon
                try:
                    clipped = line.intersection(poly)
                    if not clipped.is_empty:
                        if isinstance(clipped, LineString) and clipped.length > 0.01:
                            fills.append(clipped)
                        elif isinstance(clipped, MultiLineString):
                            fills.extend([seg for seg in clipped.geoms if seg.length > 0.01])
                except:
                    pass
                y += spacing

            # Generate vertical lines
            x = min_x
            while x <= max_x:
                line = LineString([(x, min_y - spacing), (x, max_y + spacing)])
                # Clip to polygon
                try:
                    clipped = line.intersection(poly)
                    if not clipped.is_empty:
                        if isinstance(clipped, LineString) and clipped.length > 0.01:
                            fills.append(clipped)
                        elif isinstance(clipped, MultiLineString):
                            fills.extend([seg for seg in clipped.geoms if seg.length > 0.01])
                except:
                    pass
                x += spacing

        return fills

    def _detect_and_fill_gaps(self, geometry: Union[Polygon, MultiPolygon], existing_fills: List[LineString]) -> List[LineString]:
        """Detect unfilled gaps in copper and add targeted fills.

        Samples points across the copper geometry and finds areas > 0.06mm from any fill.
        Adds minimal crosshatch fills only for the detected gap areas.

        Args:
            geometry: Copper geometry to check for gaps
            existing_fills: Already generated fill paths

        Returns:
            List of gap fill paths
        """
        from shapely.geometry import Point, box
        from shapely.ops import unary_union

        gap_fills = []

        # Normalize to list of polygons
        polys = list(geometry.geoms) if hasattr(geometry, 'geoms') else [geometry]

        # Sample points across copper geometry to detect gaps
        sample_spacing = self.line_spacing * 1.5  # Sample every 1.5x line spacing
        gap_threshold = self.line_spacing * 0.6  # Gap if > 60% of line spacing from fill

        gap_points = []

        for poly in polys:
            if not isinstance(poly, Polygon) or poly.is_empty:
                continue

            bounds = poly.bounds
            min_x, min_y, max_x, max_y = bounds

            # Sample points in a grid
            y = min_y
            while y <= max_y:
                x = min_x
                while x <= max_x:
                    point = Point(x, y)

                    # Check if point is in copper
                    if poly.contains(point):
                        # Check distance to nearest fill (optimized - only check nearby fills)
                        min_dist = float('inf')
                        search_box = box(x - gap_threshold*2, y - gap_threshold*2,
                                       x + gap_threshold*2, y + gap_threshold*2)

                        for fill in existing_fills:
                            # Skip fills that are obviously too far
                            if fill.intersects(search_box):
                                dist = point.distance(fill)
                                if dist < min_dist:
                                    min_dist = dist
                                if dist < gap_threshold:  # Early exit if close enough
                                    break

                        # If too far from any fill, this is a gap
                        if min_dist > gap_threshold:
                            gap_points.append((x, y, min_dist))

                    x += sample_spacing
                y += sample_spacing

        if not gap_points:
            return []

        print(f"    Detected {len(gap_points)} gap sample points")

        # Group nearby gap points into clusters
        from sklearn.cluster import DBSCAN
        import numpy as np

        try:
            # Cluster gap points
            points_array = np.array([(x, y) for x, y, _ in gap_points])
            clustering = DBSCAN(eps=self.line_spacing * 2, min_samples=1).fit(points_array)

            # Generate fills for each cluster
            for cluster_id in set(clustering.labels_):
                cluster_points = points_array[clustering.labels_ == cluster_id]

                if len(cluster_points) < 2:
                    continue

                # Get bounds of cluster
                cluster_min_x = cluster_points[:, 0].min()
                cluster_max_x = cluster_points[:, 0].max()
                cluster_min_y = cluster_points[:, 1].min()
                cluster_max_y = cluster_points[:, 1].max()

                # Create a small fill area for this cluster
                cluster_box = box(cluster_min_x - self.line_spacing,
                                cluster_min_y - self.line_spacing,
                                cluster_max_x + self.line_spacing,
                                cluster_max_y + self.line_spacing)

                # Find the copper polygon this cluster belongs to
                for poly in polys:
                    if poly.intersects(cluster_box):
                        # Generate dense crosshatch for this specific area
                        cluster_geom = poly.intersection(cluster_box)
                        if not cluster_geom.is_empty:
                            cluster_fills = self._generate_crosshatch_fill(cluster_geom, self.line_spacing * 0.6)
                            gap_fills.extend(cluster_fills)
                            break

        except ImportError:
            # sklearn not available, fall back to simpler approach
            # Just add a line through each gap point
            for x, y, _ in gap_points[:20]:  # Limit to 20 points
                # Add a small cross at each gap point
                for poly in polys:
                    point = Point(x, y)
                    if poly.contains(point):
                        # Horizontal line
                        h_line = LineString([(x - self.line_spacing*0.5, y),
                                            (x + self.line_spacing*0.5, y)])
                        # Vertical line
                        v_line = LineString([(x, y - self.line_spacing*0.5),
                                            (x, y + self.line_spacing*0.5)])

                        for line in [h_line, v_line]:
                            clipped = line.intersection(poly)
                            if isinstance(clipped, LineString) and clipped.length > 0.01:
                                gap_fills.append(clipped)
                        break

        return gap_fills
