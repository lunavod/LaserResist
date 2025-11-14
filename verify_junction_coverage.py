"""Verify junction polygon coverage with new contour-based fills."""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from laserresist.gerber_parser import GerberParser
from laserresist.fill_generator import FillGenerator
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MPLPolygon, Circle as MPLCircle
from shapely.geometry import Polygon, MultiPolygon, Point
import numpy as np

# Parse the Gerber file
gerber_path = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13\Gerber_TopLayer.GTL")
drill_path = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13\Drill_PTH_Through.DRL")

print(f"Parsing {gerber_path.name}...")
parser = GerberParser(gerber_path, drill_path)
geometry = parser.parse()
trace_centerlines = parser.get_trace_centerlines()
pads = parser.get_pads()
drill_holes = parser.get_drill_holes()

# Create fill generator
fill_gen = FillGenerator(line_spacing=0.1, initial_offset=0.05)

# Get junction polygons
geom_multi = MultiPolygon([geometry]) if isinstance(geometry, Polygon) else geometry
polys = list(geom_multi.geoms) if hasattr(geom_multi, 'geoms') else [geom_multi]

junction_polygons = []
for poly in polys:
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

    if area < 50.0 and aspect_ratio < 3.0 and hole_ratio > 0.05:
        junction_polygons.append(poly)

print(f"Found {len(junction_polygons)} junction polygons")

# Get junction fills
junction_fills = fill_gen._detect_and_fill_junction_polygons(geom_multi)
print(f"Generated {len(junction_fills)} junction fill paths")

# Create visualization
fig, ax = plt.subplots(figsize=(16, 12))
fig.patch.set_facecolor('#2a2a2a')
ax.set_facecolor('#1a1a1a')
ax.set_aspect('equal')
ax.grid(True, alpha=0.2, color='gray', linestyle='--')
ax.tick_params(colors='white')

# Plot junction polygons in semi-transparent yellow
for poly in junction_polygons:
    exterior_coords = np.array(poly.exterior.coords)
    patch = MPLPolygon(exterior_coords, closed=True,
                     facecolor='#FFD700', edgecolor='#FFA500',
                     linewidth=1.5, alpha=0.3, zorder=1)
    ax.add_patch(patch)

    # Mark centroid with a red dot
    centroid = poly.centroid
    ax.plot(centroid.x, centroid.y, 'ro', markersize=8, zorder=10,
           label='Junction Center' if poly == junction_polygons[0] else '')

    # Plot holes
    for interior in poly.interiors:
        interior_coords = np.array(interior.coords)
        hole_patch = MPLPolygon(interior_coords, closed=True,
                               facecolor='#1a1a1a', edgecolor='#FFA500',
                               linewidth=1.5, zorder=2)
        ax.add_patch(hole_patch)

# Plot junction fills in bright cyan
for path in junction_fills:
    coords = np.array(path.coords)
    if len(coords) >= 2:
        ax.plot(coords[:, 0], coords[:, 1], color='#00FFFF', linewidth=2.5, alpha=0.9, zorder=5)

ax.set_title(f'Junction Polygon Coverage - {len(junction_fills)} fill paths for {len(junction_polygons)} junctions',
            color='#00FFFF', fontsize=14, fontweight='bold', pad=20)

# Set reasonable bounds to focus on junctions
if junction_polygons:
    all_bounds = [poly.bounds for poly in junction_polygons]
    min_x = min(b[0] for b in all_bounds)
    min_y = min(b[1] for b in all_bounds)
    max_x = max(b[2] for b in all_bounds)
    max_y = max(b[3] for b in all_bounds)

    margin = max(max_x - min_x, max_y - min_y) * 0.1
    ax.set_xlim(min_x - margin, max_x + margin)
    ax.set_ylim(min_y - margin, max_y + margin)

ax.set_xlabel('X (mm)', color='white')
ax.set_ylabel('Y (mm)', color='white')

# Add legend
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
legend_elements = [
    Patch(facecolor='#FFD700', edgecolor='#FFA500', alpha=0.3, label='Junction Polygons'),
    Line2D([0], [0], color='#00FFFF', linewidth=2.5, label=f'Junction Fills ({len(junction_fills)} paths)'),
    Line2D([0], [0], marker='o', color='w', markerfacecolor='r', markersize=8, label='Junction Centers', linestyle=''),
]
ax.legend(handles=legend_elements, loc='upper right',
          facecolor='#2a2a2a', edgecolor='#4a4a4a',
          labelcolor='white', framealpha=0.95)

plt.tight_layout()
plt.savefig('junction_coverage_verification.png', dpi=200, facecolor='#2a2a2a')
print(f"\n✓ Verification saved to junction_coverage_verification.png")
plt.close()

print("\nSummary:")
print(f"  Junction polygons: {len(junction_polygons)}")
print(f"  Junction fill paths: {len(junction_fills)}")
print(f"  Average fills per junction: {len(junction_fills) / len(junction_polygons):.1f}")
