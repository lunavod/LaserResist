"""Zoomed viewer for precise junction clicking."""

from pathlib import Path
import sys
import re
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from laserresist.gerber_parser import GerberParser
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MPLPolygon
from shapely.geometry import Polygon, MultiPolygon, box
import numpy as np

# Junction 1 coordinates (from previous attempt) - IN GCODE COORDINATES
# Will be transformed to Gerber coordinates after loading transform
junction_x_gcode, junction_y_gcode = 23.80, 9.75

# Parse Gerber to show actual copper
gerber_path = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13\Gerber_TopLayer.GTL")
drill_path = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13\Drill_PTH_Through.DRL")

print(f"Loading Gerber geometry around Junction 1...")
parser = GerberParser(gerber_path, drill_path)
geometry = parser.parse()
trace_centerlines = parser.get_trace_centerlines()

# Parse G-code for fill paths and extract coordinate transformation
gcode_path = Path(r"C:\Users\yegor\Projects\PositivePCB\crosshatch_test.gcode")
print(f"Loading G-code paths...")

# Extract transformation from G-code header
transform_x = 0.0
transform_y = 0.0
with open(gcode_path, 'r') as f:
    for line in f:
        if 'Applied transform:' in line:
            # Extract X and Y offsets
            x_match = re.search(r'X\+?([-\d.]+)', line)
            y_match = re.search(r'Y\+?([-\d.]+)', line)
            if x_match and y_match:
                transform_x = float(x_match.group(1))
                transform_y = float(y_match.group(1))
                print(f"Found coordinate transform: X+{transform_x}, Y+{transform_y}")
                break

paths = []
current_path = []

with open(gcode_path, 'r') as f:
    laser_on = False
    for line in f:
        line = line.strip()
        if 'M3' in line:
            laser_on = True
            current_path = []
        elif 'M5' in line:
            laser_on = False
            if current_path:
                paths.append(current_path)
                current_path = []
        elif laser_on and line.startswith('G1 '):
            x_match = re.search(r'X([\d.]+)', line)
            y_match = re.search(r'Y([\d.]+)', line)
            if x_match and y_match:
                # Apply INVERSE transform to get back to Gerber coordinates
                x = float(x_match.group(1)) - transform_x
                y = float(y_match.group(1)) - transform_y
                current_path.append((x, y))

print(f"Loaded {len(paths)} paths (transformed to Gerber coordinates)")

# Transform junction coordinates to Gerber space
junction_x = junction_x_gcode - transform_x
junction_y = junction_y_gcode - transform_y
print(f"Junction in Gerber coordinates: ({junction_x:.2f}, {junction_y:.2f})")

# Create zoomed interactive plot
fig, ax = plt.subplots(figsize=(16, 12))
fig.patch.set_facecolor('#2a2a2a')
ax.set_facecolor('#1a1a1a')
ax.set_aspect('equal')
ax.grid(True, alpha=0.3, color='gray', linestyle='--', linewidth=0.5)
ax.tick_params(colors='white')

# Zoom into Junction 1 area (±3mm for better view)
zoom = 3.0
ax.set_xlim(junction_x - zoom, junction_x + zoom)
ax.set_ylim(junction_y - zoom, junction_y + zoom)

# Plot copper geometry (YELLOW - this is the actual copper from Gerber)
view_box = box(junction_x - zoom, junction_y - zoom, junction_x + zoom, junction_y + zoom)

if isinstance(geometry, Polygon):
    polys = [geometry]
elif isinstance(geometry, MultiPolygon):
    polys = list(geometry.geoms)

for poly in polys:
    if poly.intersects(view_box):
        exterior_coords = np.array(poly.exterior.coords)
        ax.fill(exterior_coords[:, 0], exterior_coords[:, 1],
               color='#FFD700', alpha=0.6, zorder=1, label='Copper (Gerber)')
        ax.plot(exterior_coords[:, 0], exterior_coords[:, 1],
               color='#FFA500', linewidth=2, zorder=2)

        # Plot holes in copper
        for interior in poly.interiors:
            interior_coords = np.array(interior.coords)
            ax.fill(interior_coords[:, 0], interior_coords[:, 1],
                   color='#1a1a1a', zorder=3)
            ax.plot(interior_coords[:, 0], interior_coords[:, 1],
                   color='#FFA500', linewidth=2, zorder=4)

# Plot fill paths (GREEN)
for path in paths:
    if len(path) >= 2:
        path_array = np.array(path)
        # Check if path is in view
        if any((junction_x - zoom <= x <= junction_x + zoom and
                junction_y - zoom <= y <= junction_y + zoom) for x, y in path):
            ax.plot(path_array[:, 0], path_array[:, 1],
                   color='#00FF00', linewidth=1.5, alpha=0.8, zorder=5)

# Plot trace centerlines (MAGENTA)
for centerline in trace_centerlines:
    if centerline.intersects(view_box):
        coords = np.array(centerline.coords)
        ax.plot(coords[:, 0], coords[:, 1],
               color='#FF00FF', linewidth=2.5, alpha=0.7, zorder=6,
               linestyle='--')

# Mark original click point
ax.plot(junction_x, junction_y, 'bx', markersize=20, markeredgewidth=3,
       zorder=10, label='Original Click')

ax.set_title('ZOOMED: Click PRECISELY on the empty copper area\n(Yellow = Copper, Green = Fills, Magenta = Trace Centers)',
            color='#FF6B6B', fontsize=14, fontweight='bold', pad=20)
ax.set_xlabel('X (mm)', color='white', fontsize=12)
ax.set_ylabel('Y (mm)', color='white', fontsize=12)

# Storage for clicked point
clicked_point = []

def onclick(event):
    """Handle mouse click."""
    if event.inaxes != ax:
        return

    x, y = event.xdata, event.ydata

    # Clear previous clicks
    if clicked_point:
        clicked_point.clear()

    clicked_point.append((x, y))

    # Remove old markers
    for artist in ax.lines + ax.collections:
        if hasattr(artist, '_precise_marker'):
            artist.remove()

    # Add new marker
    marker = ax.plot(x, y, 'r*', markersize=25, markeredgewidth=2,
                    markeredgecolor='white', zorder=15)[0]
    marker._precise_marker = True

    print(f"\nPRECISE Click: X={x:.4f}, Y={y:.4f}")

    fig.canvas.draw()

def onkey(event):
    """Save and close."""
    if event.key == 'enter' or event.key == 'escape':
        if clicked_point:
            x, y = clicked_point[0]
            print(f"\n{'='*60}")
            print(f"SAVED PRECISE COORDINATE: ({x:.4f}, {y:.4f})")
            print(f"{'='*60}\n")

            with open('precise_junction.txt', 'w') as f:
                f.write(f"Precise Junction Coordinate\n")
                f.write(f"X: {x:.4f}\n")
                f.write(f"Y: {y:.4f}\n")

            print("Saved to precise_junction.txt")
        plt.close()

fig.canvas.mpl_connect('button_press_event', onclick)
fig.canvas.mpl_connect('key_press_event', onkey)

# Legend
ax.legend(loc='upper right', facecolor='#2a2a2a', edgecolor='white',
         labelcolor='white', framealpha=0.95)

# Instructions
instruction_text = (
    "INSTRUCTIONS:\n"
    "• Click PRECISELY on the empty copper area\n"
    "• Press ENTER when done\n"
)
fig.text(0.02, 0.98, instruction_text,
        transform=fig.transFigure,
        fontsize=12, color='#FFD700',
        verticalalignment='top',
        bbox=dict(boxstyle='round', facecolor='#2a2a2a',
                 edgecolor='#FFD700', pad=10, alpha=0.9))

plt.tight_layout(rect=[0, 0, 1, 0.95])
print("\nZoomed viewer opened. Click precisely on the empty area!")
plt.show()

if clicked_point:
    x, y = clicked_point[0]
    print(f"\nRun: python analyze_precise_point.py {x:.4f} {y:.4f}")
