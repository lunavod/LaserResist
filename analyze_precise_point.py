"""Analyze the precise empty junction point."""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from laserresist.gerber_parser import GerberParser
from laserresist.fill_generator import FillGenerator
from shapely.geometry import Point, Polygon, MultiPolygon, box, LineString
from shapely.ops import nearest_points
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MPLPolygon, Circle
import numpy as np

# Precise junction coordinate (in Gerber space)
jx, jy = 23.6700, -0.7752

print(f"Analyzing precise junction at ({jx:.4f}, {jy:.4f}) mm\n")
print("="*80)

# Parse Gerber
gerber_path = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13\Gerber_TopLayer.GTL")
drill_path = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13\Drill_PTH_Through.DRL")

parser = GerberParser(gerber_path, drill_path)
geometry = parser.parse()
trace_centerlines = parser.get_trace_centerlines()
pads = parser.get_pads()
drill_holes = parser.get_drill_holes()

# Generate fills
fill_gen = FillGenerator(line_spacing=0.1, initial_offset=0.05)
paths = fill_gen.generate_fill(geometry, trace_centerlines=trace_centerlines,
                               offset_centerlines=False, pads=pads, drill_holes=drill_holes)

junction_point = Point(jx, jy)

# Check if point is in copper
is_in_copper = False
containing_poly = None

if isinstance(geometry, Polygon):
    if geometry.contains(junction_point):
        is_in_copper = True
        containing_poly = geometry
elif isinstance(geometry, MultiPolygon):
    for poly in geometry.geoms:
        if poly.contains(junction_point):
            is_in_copper = True
            containing_poly = poly
            break

print(f"Point is inside copper geometry: {is_in_copper}")

if is_in_copper and containing_poly:
    print(f"  Containing polygon area: {containing_poly.area:.4f} mm²")
    print(f"  Has holes: {len(containing_poly.interiors) > 0}")

# Find nearest fill path
min_distance = float('inf')
nearest_fill = None

for path in paths:
    dist = junction_point.distance(path)
    if dist < min_distance:
        min_distance = dist
        nearest_fill = path

print(f"Distance to nearest fill path: {min_distance:.4f} mm")

if is_in_copper and min_distance > 0.05:
    print(f"\n⚠️  GAP DETECTED!")
    print(f"  This point IS in copper but has NO fill within 0.05mm!")
    print(f"  Nearest fill is {min_distance:.4f} mm away")
    print(f"  This is a REAL unfilled copper area!")

    # Analyze why it's not filled
    print(f"\n  Investigating cause of gap...")

    # Check if it's near contour boundaries
    if containing_poly:
        # Distance to exterior boundary
        exterior_line = LineString(containing_poly.exterior.coords)
        dist_to_boundary = junction_point.distance(exterior_line)
        print(f"  Distance to polygon boundary: {dist_to_boundary:.4f} mm")

        # Check if it's in a hole
        for i, interior in enumerate(containing_poly.interiors):
            interior_line = LineString(interior.coords)
            dist_to_hole = junction_point.distance(interior_line)
            if dist_to_hole < 0.5:
                print(f"  Near hole #{i+1}: {dist_to_hole:.4f} mm away")

    # Check trace centerlines
    nearby_centerlines = 0
    for centerline in trace_centerlines:
        if junction_point.distance(centerline) < 1.0:
            nearby_centerlines += 1

    print(f"  Nearby trace centerlines (< 1mm): {nearby_centerlines}")

elif not is_in_copper:
    print(f"\n✓ Point is NOT in copper - this is just empty space between traces")
    print(f"  (This is normal and correct)")
else:
    print(f"\n✓ Point is in copper and has fills nearby ({min_distance:.4f} mm)")
    print(f"  (This area is being filled correctly)")

print("="*80)

# Create detailed visualization
fig, ax = plt.subplots(figsize=(14, 14))
fig.patch.set_facecolor('#2a2a2a')
ax.set_facecolor('#1a1a1a')
ax.set_aspect('equal')
ax.grid(True, alpha=0.3, color='gray', linestyle='--', linewidth=0.5)
ax.tick_params(colors='white')

# Very zoomed in (±0.5mm)
zoom = 0.5
ax.set_xlim(jx - zoom, jx + zoom)
ax.set_ylim(jy - zoom, jy + zoom)

view_box = box(jx - zoom, jy - zoom, jx + zoom, jy + zoom)

# Plot copper
if isinstance(geometry, Polygon):
    polys = [geometry]
elif isinstance(geometry, MultiPolygon):
    polys = list(geometry.geoms)

for poly in polys:
    if poly.intersects(view_box):
        # Fill copper area
        exterior_coords = np.array(poly.exterior.coords)
        ax.fill(exterior_coords[:, 0], exterior_coords[:, 1],
               color='#FFD700', alpha=0.4, zorder=1)
        # Draw boundary
        ax.plot(exterior_coords[:, 0], exterior_coords[:, 1],
               color='#FFA500', linewidth=2.5, zorder=2, label='Copper Boundary')

        # Plot holes
        for interior in poly.interiors:
            interior_coords = np.array(interior.coords)
            ax.fill(interior_coords[:, 0], interior_coords[:, 1],
                   color='#1a1a1a', zorder=3)
            ax.plot(interior_coords[:, 0], interior_coords[:, 1],
                   color='#FF0000', linewidth=2.5, zorder=4, label='Hole')

# Plot fill paths
for path in paths:
    if path.intersects(view_box):
        coords = np.array(path.coords)
        ax.plot(coords[:, 0], coords[:, 1],
               color='#00FF00', linewidth=2, alpha=0.9, zorder=5)

# Plot trace centerlines
for centerline in trace_centerlines:
    if centerline.intersects(view_box):
        coords = np.array(centerline.coords)
        ax.plot(coords[:, 0], coords[:, 1],
               color='#FF00FF', linewidth=2.5, alpha=0.7, zorder=6,
               linestyle='--', label='Trace Centerline')

# Mark the precise point
ax.plot(jx, jy, 'r*', markersize=30, markeredgewidth=2,
       markeredgecolor='white', zorder=10, label='Analyzed Point')
ax.add_patch(Circle((jx, jy), 0.05, color='red', fill=False,
                   linewidth=2, zorder=9))

# Show nearest fill distance
if nearest_fill:
    nearest_pt = nearest_points(junction_point, nearest_fill)[1]
    ax.plot([jx, nearest_pt.x], [jy, nearest_pt.y],
           'r--', linewidth=2, alpha=0.7, zorder=8,
           label=f'Distance to fill: {min_distance:.3f}mm')

status_color = '#FF0000' if (is_in_copper and min_distance > 0.05) else '#00FF00'
status_text = 'GAP DETECTED!' if (is_in_copper and min_distance > 0.05) else 'OK'

ax.set_title(f'Precise Analysis: ({jx:.4f}, {jy:.4f}) - {status_text}',
            color=status_color, fontsize=14, fontweight='bold', pad=20)
ax.set_xlabel('X (mm)', color='white', fontsize=11)
ax.set_ylabel('Y (mm)', color='white', fontsize=11)

# Remove duplicate labels
handles, labels = ax.get_legend_handles_labels()
by_label = dict(zip(labels, handles))
ax.legend(by_label.values(), by_label.keys(), loc='upper right',
         facecolor='#2a2a2a', edgecolor='white',
         labelcolor='white', framealpha=0.95)

plt.tight_layout()
plt.savefig('precise_point_analysis.png', dpi=300, facecolor='#2a2a2a')
print(f"\n✓ Detailed visualization saved to precise_point_analysis.png")

plt.close()
print("\nAnalysis complete!")
