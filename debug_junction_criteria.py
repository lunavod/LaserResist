"""Debug junction detection criteria."""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from laserresist.gerber_parser import GerberParser
from shapely.geometry import Polygon, MultiPolygon, Point

# Parse the Gerber file
gerber_path = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13\Gerber_TopLayer.GTL")
drill_path = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13\Drill_PTH_Through.DRL")

parser = GerberParser(gerber_path, drill_path)
geometry = parser.parse()

# Normalize to list of polygons
polys = []
if isinstance(geometry, Polygon):
    polys = [geometry]
elif isinstance(geometry, MultiPolygon):
    polys = list(geometry.geoms)

print(f"Total polygons: {len(polys)}\n")

# Analyze polygons with holes
for i, poly in enumerate(polys):
    if not isinstance(poly, Polygon) or len(poly.interiors) == 0:
        continue

    bounds = poly.bounds
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    area = poly.area

    hole_areas = [Polygon(interior.coords).area for interior in poly.interiors]
    total_hole_area = sum(hole_areas)

    aspect_ratio = max(width, height) / (min(width, height) + 0.001)
    hole_ratio = total_hole_area / (area + total_hole_area) if (area + total_hole_area) > 0 else 0

    # Check if hole is centered
    centroid = poly.centroid
    hole_centroids = [Polygon(interior.coords).centroid for interior in poly.interiors]
    is_hole_centered = False
    min_hole_dist = 999
    if hole_centroids:
        for hole_cent in hole_centroids:
            dist_to_center = Point(centroid.x, centroid.y).distance(hole_cent)
            min_hole_dist = min(min_hole_dist, dist_to_center)
            if dist_to_center < min(width, height) * 0.2:
                is_hole_centered = True
                break

    # Calculate circularity
    perimeter = poly.exterior.length
    circularity = (4 * 3.14159 * area) / (perimeter * perimeter) if perimeter > 0 else 0

    # Check all criteria (updated to match new conservative approach)
    checks = {
        'area < 3.0': area < 3.0,
        'aspect < 2.0': aspect_ratio < 2.0,
        'hole_ratio > 0.05': hole_ratio > 0.05,
    }

    is_junction = all(checks.values())

    if area < 100.0 and aspect_ratio < 4.0:  # Reasonable candidates
        print(f"Polygon #{i}:")
        print(f"  Area: {area:.2f} mm²")
        print(f"  Size: {width:.2f} x {height:.2f} mm")
        print(f"  Aspect ratio: {aspect_ratio:.2f}")
        print(f"  Hole ratio: {hole_ratio * 100:.1f}%")
        print(f"  Hole dist from center: {min_hole_dist:.3f} mm")
        print(f"  Circularity: {circularity:.3f}")
        print(f"  Checks: {checks}")
        print(f"  → Junction: {is_junction}")
        print()
