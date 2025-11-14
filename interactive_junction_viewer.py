"""Interactive viewer to identify empty junction coordinates."""

from pathlib import Path
import sys
import re
sys.path.insert(0, str(Path(__file__).parent / 'src'))

import matplotlib.pyplot as plt
from matplotlib.patches import Circle
import numpy as np

# Parse G-code file
gcode_path = Path(r"C:\Users\yegor\Projects\PositivePCB\crosshatch_test.gcode")

print(f"Loading {gcode_path.name}...")

# Extract all G1 moves (laser on movements)
paths = []
current_path = []

with open(gcode_path, 'r') as f:
    laser_on = False
    for line in f:
        line = line.strip()

        if 'M3' in line:  # Laser on
            laser_on = True
            current_path = []
        elif 'M5' in line:  # Laser off
            laser_on = False
            if current_path:
                paths.append(current_path)
                current_path = []
        elif laser_on and line.startswith('G1 '):
            # Extract X and Y coordinates
            x_match = re.search(r'X([\d.]+)', line)
            y_match = re.search(r'Y([\d.]+)', line)
            if x_match and y_match:
                x = float(x_match.group(1))
                y = float(y_match.group(1))
                current_path.append((x, y))

print(f"Loaded {len(paths)} paths")

# Create interactive plot
fig, ax = plt.subplots(figsize=(16, 12))
fig.patch.set_facecolor('#2a2a2a')
ax.set_facecolor('#1a1a1a')
ax.set_aspect('equal')
ax.grid(True, alpha=0.2, color='gray', linestyle='--')
ax.tick_params(colors='white')

# Plot all paths
for path in paths:
    if len(path) >= 2:
        path_array = np.array(path)
        ax.plot(path_array[:, 0], path_array[:, 1],
               color='#00FF00', linewidth=0.5, alpha=0.5, zorder=1)

ax.set_title('Click on Empty Junctions - Coordinates will be printed and saved',
            color='#FF6B6B', fontsize=14, fontweight='bold', pad=20)
ax.set_xlabel('X (mm)', color='white', fontsize=12)
ax.set_ylabel('Y (mm)', color='white', fontsize=12)

# Storage for clicked points
clicked_points = []
point_markers = []

def onclick(event):
    """Handle mouse click events."""
    if event.inaxes != ax:
        return

    x, y = event.xdata, event.ydata
    clicked_points.append((x, y))

    # Add visual marker
    marker = ax.plot(x, y, 'rx', markersize=15, markeredgewidth=3, zorder=10)[0]
    point_markers.append(marker)

    # Add text label
    label = ax.text(x + 1, y + 1, f'{len(clicked_points)}',
                   color='red', fontsize=12, fontweight='bold', zorder=11)
    point_markers.append(label)

    # Print coordinates
    print(f"\nJunction #{len(clicked_points)}: X={x:.2f}, Y={y:.2f}")

    # Update plot
    fig.canvas.draw()

def onkey(event):
    """Handle keyboard events."""
    if event.key == 'enter' or event.key == 'escape':
        # Save and close
        print(f"\n{'='*60}")
        print(f"Saved {len(clicked_points)} junction coordinates:")
        for i, (x, y) in enumerate(clicked_points, 1):
            print(f"  Junction {i}: ({x:.2f}, {y:.2f})")
        print(f"{'='*60}\n")

        # Save to file
        with open('junction_coordinates.txt', 'w') as f:
            f.write("Empty Junction Coordinates\n")
            f.write("="*50 + "\n\n")
            for i, (x, y) in enumerate(clicked_points, 1):
                f.write(f"Junction {i}: ({x:.2f}, {y:.2f})\n")

        print("Coordinates saved to junction_coordinates.txt")
        plt.close()

# Connect event handlers
fig.canvas.mpl_connect('button_press_event', onclick)
fig.canvas.mpl_connect('key_press_event', onkey)

# Instructions
instruction_text = (
    "INSTRUCTIONS:\n"
    "• Click on empty junctions to mark them\n"
    "• Coordinates will be printed to console\n"
    "• Press ENTER or ESC when done to save and close\n"
)
fig.text(0.02, 0.98, instruction_text,
        transform=fig.transFigure,
        fontsize=11, color='#FFD700',
        verticalalignment='top',
        bbox=dict(boxstyle='round', facecolor='#2a2a2a',
                 edgecolor='#FFD700', pad=10, alpha=0.9))

plt.tight_layout(rect=[0, 0, 1, 0.95])
print("\n" + "="*60)
print("Interactive Viewer Started")
print("="*60)
print(instruction_text)
print("Window should open now. Click on empty junctions!")
print("="*60 + "\n")

plt.show()

# Final summary
if clicked_points:
    print("\nFinal Summary:")
    print(f"Identified {len(clicked_points)} empty junctions")
    print("\nYou can now run: python analyze_junction_coordinates.py")
else:
    print("\nNo junctions were marked.")
