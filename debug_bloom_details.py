"""Debug script to examine blooming in detail on specific pads."""

import sys
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from shapely.geometry import box, Point

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from laserresist.gerber_parser import GerberParser
from laserresist.fill_generator import FillGenerator
from test_blooming_simulation import BloomingSimulator

gerber_folder = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13")
copper_file = gerber_folder / "Gerber_TopLayer.GTL"

print("="*70)
print("DETAILED BLOOM DEBUGGING")
print("="*70)

# Parse and generate fills
print("\n[1] Parsing Gerber and generating fills...")
parser = GerberParser(copper_file)
geometry = parser.parse()
trace_centerlines = parser.get_trace_centerlines()
pads = parser.get_pads()

fill_gen = FillGenerator(line_spacing=0.1, initial_offset=0.05)
paths = fill_gen.generate_fill(geometry, trace_centerlines=trace_centerlines, pads=pads)

print(f"  Generated {len(paths)} paths")
print(f"  Found {len(pads)} pads")

# Focus on a few specific pads
focus_pads = [
    {'name': 'Bottom Left Connector', 'bounds': (5, -8, 15, 2), 'expected': 'HIGH'},
    {'name': 'Top Center IC', 'bounds': (20, 20, 30, 30), 'expected': 'HIGH'},
    {'name': 'Right Edge Connector', 'bounds': (47, 5, 52, 15), 'expected': 'LOW/MED'},
]

# Create blooming simulator
print("\n[2] Creating blooming simulator...")
bounds = geometry.bounds
simulator = BloomingSimulator(resolution=0.15, bloom_radius=2.0)
simulator.create_grid(bounds)

# Simulate
print("\n[3] Simulating bloom...")
simulator.simulate_all_paths(paths, sample_distance=0.1, min_samples=10)

print(f"\n[4] Analyzing specific pad areas...")
print("="*70)

for pad_info in focus_pads:
    name = pad_info['name']
    bx1, by1, bx2, by2 = pad_info['bounds']
    expected = pad_info['expected']

    focus_box = box(bx1, by1, bx2, by2)

    # Count paths in this area
    paths_in_area = [p for p in paths if p.intersects(focus_box)]

    # Sample energy grid in this area
    # Convert bounds to grid coordinates
    gx1, gy1 = simulator.world_to_grid(bx1, by1)
    gx2, gy2 = simulator.world_to_grid(bx2, by2)

    # Ensure bounds are valid
    gx1 = max(0, min(gx1, simulator.grid_shape[1]-1))
    gx2 = max(0, min(gx2, simulator.grid_shape[1]-1))
    gy1 = max(0, min(gy1, simulator.grid_shape[0]-1))
    gy2 = max(0, min(gy2, simulator.grid_shape[0]-1))

    if gx1 > gx2:
        gx1, gx2 = gx2, gx1
    if gy1 > gy2:
        gy1, gy2 = gy2, gy1

    # Extract grid section
    grid_section = simulator.grid[gy1:gy2+1, gx1:gx2+1]

    print(f"\n{name} ({bx1:.1f}, {by1:.1f}) to ({bx2:.1f}, {by2:.1f})")
    print(f"  Expected bloom: {expected}")
    print(f"  Paths in area: {len(paths_in_area)}")
    print(f"  Grid section size: {grid_section.shape}")
    print(f"  Energy stats:")
    print(f"    Min:  {grid_section.min():.1f}")
    print(f"    Max:  {grid_section.max():.1f}")
    print(f"    Mean: {grid_section.mean():.1f}")
    print(f"    Std:  {grid_section.std():.1f}")

    # Show path length distribution
    short = sum(1 for p in paths_in_area if p.length < 5)
    medium = sum(1 for p in paths_in_area if 5 <= p.length < 20)
    long = sum(1 for p in paths_in_area if p.length >= 20)
    print(f"  Path lengths: {short} short, {medium} medium, {long} long")

# Create detailed visualization of one pad area
print("\n[5] Creating detailed visualization...")
focus = focus_pads[0]  # Bottom left connector
bx1, by1, bx2, by2 = focus['bounds']

fig, axes = plt.subplots(1, 3, figsize=(20, 7))

# Plot 1: Copper geometry in focus area
ax1 = axes[0]
ax1.set_title(f"{focus['name']} - Copper Geometry", fontweight='bold')
ax1.set_aspect('equal')
ax1.set_xlim(bx1, bx2)
ax1.set_ylim(by1, by2)
ax1.grid(True, alpha=0.3)

# Draw copper polygons
for geom in geometry.geoms if hasattr(geometry, 'geoms') else [geometry]:
    if geom.intersects(box(bx1, by1, bx2, by2)):
        x, y = geom.exterior.xy
        ax1.fill(x, y, color='orange', alpha=0.5, edgecolor='black', linewidth=0.5)

# Plot 2: Fill paths
ax2 = axes[1]
ax2.set_title(f"{focus['name']} - Fill Paths", fontweight='bold')
ax2.set_aspect('equal')
ax2.set_xlim(bx1, bx2)
ax2.set_ylim(by1, by2)
ax2.grid(True, alpha=0.3)

for path in paths:
    if path.intersects(box(bx1, by1, bx2, by2)):
        coords = list(path.coords)
        xs, ys = zip(*coords)
        ax2.plot(xs, ys, 'b-', linewidth=1, alpha=0.7)

# Plot 3: Energy heatmap
ax3 = axes[2]
ax3.set_title(f"{focus['name']} - Bloom Energy", fontweight='bold')
ax3.set_aspect('equal')
ax3.set_xlim(bx1, bx2)
ax3.set_ylim(by1, by2)

# Extract and plot grid section
gx1, gy1 = simulator.world_to_grid(bx1, by1)
gx2, gy2 = simulator.world_to_grid(bx2, by2)
gx1, gx2 = (min(gx1, gx2), max(gx1, gx2))
gy1, gy2 = (min(gy1, gy2), max(gy1, gy2))

grid_section = simulator.grid[gy1:gy2+1, gx1:gx2+1]

im = ax3.imshow(grid_section, cmap='hot', origin='lower',
                extent=[bx1, bx2, by1, by2],
                interpolation='nearest', aspect='equal')
plt.colorbar(im, ax=ax3, label='Energy')

# Overlay paths
for path in paths:
    if path.intersects(box(bx1, by1, bx2, by2)):
        coords = list(path.coords)
        xs, ys = zip(*coords)
        ax3.plot(xs, ys, 'cyan', linewidth=0.5, alpha=0.5)

plt.tight_layout()
plt.savefig('bloom_debug_detailed.png', dpi=200)
print(f"\nSaved detailed visualization to: bloom_debug_detailed.png")

print("\n" + "="*70)
print("DIAGNOSTIC COMPLETE")
print("="*70)
