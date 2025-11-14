"""Analyze specific junction coordinates to understand why they're empty."""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from laserresist.gerber_parser import GerberParser
from laserresist.fill_generator import FillGenerator
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle
from shapely.geometry import Point, Polygon, MultiPolygon, box
import numpy as np

# Junction coordinates (from user clicks)
junctions = [
    (23.80, 9.75, "Junction 1"),
    (20.46, 22.56, "Junction 2"),
    (31.56, 23.03, "Junction 3"),
    (13.57, 35.10, "Junction 4"),
]

# Parse Gerber files
gerber_path = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13\Gerber_TopLayer.GTL")
drill_path = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13\Drill_PTH_Through.DRL")

print(f"Parsing {gerber_path.name}...")
parser = GerberParser(gerber_path, drill_path)
geometry = parser.parse()
trace_centerlines = parser.get_trace_centerlines()
pads = parser.get_pads()
drill_holes = parser.get_drill_holes()

# Generate fills
fill_gen = FillGenerator(line_spacing=0.1, initial_offset=0.05)
paths = fill_gen.generate_fill(geometry, trace_centerlines=trace_centerlines,
                               offset_centerlines=False, pads=pads, drill_holes=drill_holes)

print(f"\nAnalyzing {len(junctions)} junction locations...\n")
print("="*80)

# Analyze each junction
for jx, jy, name in junctions:
    print(f"\n{name} at ({jx:.2f}, {jy:.2f}):")
    print("-" * 60)

    # Create a search box around the junction (±1.5mm)
    search_radius = 1.5
    search_box = box(jx - search_radius, jy - search_radius,
                     jx + search_radius, jy + search_radius)

    # Check if junction point is inside copper geometry
    junction_point = Point(jx, jy)
    is_in_copper = False

    if isinstance(geometry, Polygon):
        is_in_copper = geometry.contains(junction_point)
    elif isinstance(geometry, MultiPolygon):
        for poly in geometry.geoms:
            if poly.contains(junction_point):
                is_in_copper = True
                break

    print(f"  In copper geometry: {is_in_copper}")

    # Find nearby copper polygons
    nearby_polys = []
    if isinstance(geometry, Polygon):
        if geometry.intersects(search_box):
            nearby_polys.append(geometry)
    elif isinstance(geometry, MultiPolygon):
        for poly in geometry.geoms:
            if poly.intersects(search_box):
                nearby_polys.append(poly)

    print(f"  Nearby copper polygons: {len(nearby_polys)}")

    # Find nearby trace centerlines
    nearby_centerlines = []
    for centerline in trace_centerlines:
        if centerline.intersects(search_box):
            nearby_centerlines.append(centerline)

    print(f"  Nearby trace centerlines: {len(nearby_centerlines)}")

    # Find nearby fill paths
    nearby_fills = []
    for path in paths:
        if path.intersects(search_box):
            nearby_fills.append(path)

    print(f"  Nearby fill paths: {len(nearby_fills)}")

    # Calculate distance to nearest fill
    min_distance = float('inf')
    for fill_path in paths:
        dist = junction_point.distance(fill_path)
        if dist < min_distance:
            min_distance = dist

    print(f"  Distance to nearest fill: {min_distance:.3f} mm")

    # Check if this is a gap
    if is_in_copper and min_distance > 0.05:  # More than 0.05mm from any fill
        print(f"  ⚠ GAP DETECTED! Empty area {min_distance:.3f} mm from nearest fill")

        # Analyze the copper geometry here
        if nearby_polys:
            for i, poly in enumerate(nearby_polys[:1]):  # Analyze first polygon
                bounds = poly.bounds
                width = bounds[2] - bounds[0]
                height = bounds[3] - bounds[1]
                area = poly.area
                has_hole = len(poly.interiors) > 0

                print(f"    Polygon {i+1}:")
                print(f"      Size: {width:.2f} x {height:.2f} mm")
                print(f"      Area: {area:.2f} mm²")
                print(f"      Has holes: {has_hole}")

                # Check if junction is near a polygon hole
                if has_hole:
                    for hole in poly.interiors:
                        hole_poly = Polygon(hole.coords)
                        hole_dist = junction_point.distance(hole_poly)
                        if hole_dist < search_radius:
                            print(f"      Near hole! Distance: {hole_dist:.3f} mm")

print("\n" + "="*80)
print("\nNow generating detailed visualization...")

# Create detailed visualization
fig = plt.figure(figsize=(20, 10))
fig.patch.set_facecolor('#2a2a2a')

for idx, (jx, jy, name) in enumerate(junctions, 1):
    ax = plt.subplot(2, 2, idx)
    ax.set_facecolor('#1a1a1a')
    ax.set_aspect('equal')
    ax.grid(True, alpha=0.2, color='gray', linestyle='--')
    ax.tick_params(colors='white')

    # Focus on junction area (±2mm)
    view_radius = 2.0
    ax.set_xlim(jx - view_radius, jx + view_radius)
    ax.set_ylim(jy - view_radius, jy + view_radius)

    # Plot copper geometry in this area
    if isinstance(geometry, Polygon):
        polys = [geometry]
    elif isinstance(geometry, MultiPolygon):
        polys = list(geometry.geoms)

    for poly in polys:
        if poly.intersects(box(jx - view_radius, jy - view_radius,
                              jx + view_radius, jy + view_radius)):
            exterior_coords = np.array(poly.exterior.coords)
            ax.fill(exterior_coords[:, 0], exterior_coords[:, 1],
                   color='#FFD700', alpha=0.3, zorder=1)
            ax.plot(exterior_coords[:, 0], exterior_coords[:, 1],
                   color='#FFA500', linewidth=1.5, zorder=2)

            # Plot holes
            for interior in poly.interiors:
                interior_coords = np.array(interior.coords)
                ax.fill(interior_coords[:, 0], interior_coords[:, 1],
                       color='#1a1a1a', zorder=3)
                ax.plot(interior_coords[:, 0], interior_coords[:, 1],
                       color='#FFA500', linewidth=1.5, zorder=4)

    # Plot fill paths
    for path in paths:
        if path.intersects(box(jx - view_radius, jy - view_radius,
                             jx + view_radius, jy + view_radius)):
            coords = np.array(path.coords)
            ax.plot(coords[:, 0], coords[:, 1],
                   color='#00FF00', linewidth=1.5, alpha=0.8, zorder=5)

    # Plot trace centerlines
    for centerline in trace_centerlines:
        if centerline.intersects(box(jx - view_radius, jy - view_radius,
                                    jx + view_radius, jy + view_radius)):
            coords = np.array(centerline.coords)
            ax.plot(coords[:, 0], coords[:, 1],
                   color='#FF00FF', linewidth=2.0, alpha=0.6, zorder=6, linestyle='--')

    # Mark junction point
    ax.plot(jx, jy, 'rx', markersize=20, markeredgewidth=3, zorder=10)
    ax.add_patch(Circle((jx, jy), 0.1, color='red', alpha=0.3, zorder=9))

    ax.set_title(f'{name} ({jx:.2f}, {jy:.2f})',
                color='#FF6B6B', fontsize=11, fontweight='bold')
    ax.set_xlabel('X (mm)', color='white', fontsize=9)
    ax.set_ylabel('Y (mm)', color='white', fontsize=9)

# Add legend
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
legend_elements = [
    Patch(facecolor='#FFD700', alpha=0.3, edgecolor='#FFA500', label='Copper'),
    Line2D([0], [0], color='#00FF00', linewidth=1.5, label='Fill Paths'),
    Line2D([0], [0], color='#FF00FF', linewidth=2.0, linestyle='--', label='Trace Centerlines'),
    Line2D([0], [0], marker='x', color='w', markerfacecolor='r', markersize=10,
           linestyle='', label='Empty Junction'),
]
fig.legend(handles=legend_elements, loc='upper center', ncol=4,
          facecolor='#2a2a2a', edgecolor='#4a4a4a',
          labelcolor='white', framealpha=0.95)

plt.tight_layout(rect=[0, 0, 1, 0.96])
plt.savefig('junction_analysis.png', dpi=200, facecolor='#2a2a2a')
print(f"✓ Detailed visualization saved to junction_analysis.png")

plt.close()
print("\nAnalysis complete!")
