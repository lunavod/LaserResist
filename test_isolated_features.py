"""Test script to visualize isolated feature detection."""

import sys
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from shapely.geometry import LineString, Polygon, MultiPolygon

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from laserresist.gerber_parser import GerberParser
from laserresist.fill_generator import FillGenerator

def find_gerber_files(folder_path):
    """Find Gerber files in the folder."""
    folder = Path(folder_path)

    # Common patterns for copper layers
    copper_patterns = ['*.gtl', '*.gbl', '*F.Cu.gbr', '*B.Cu.gbr', '*-F_Cu.gbr', '*-B_Cu.gbr']
    outline_patterns = ['*.gko', '*.gm1', '*Edge.Cuts.gbr', '*-Edge_Cuts.gbr']

    copper_file = None
    outline_file = None

    for pattern in copper_patterns:
        files = list(folder.glob(pattern))
        if files:
            copper_file = files[0]
            print(f"Found copper file: {copper_file.name}")
            break

    for pattern in outline_patterns:
        files = list(folder.glob(pattern))
        if files:
            outline_file = files[0]
            print(f"Found outline file: {outline_file.name}")
            break

    return copper_file, outline_file

def visualize_isolated_features(copper_file, output_image="isolated_features_visualization.png",
                                  isolation_threshold=3.0):
    """Visualize which features are detected as isolated."""

    print(f"\n=== Testing Isolated Feature Detection ===")
    print(f"Copper file: {copper_file}")
    print(f"Isolation threshold: {isolation_threshold}mm")
    print(f"Output image: {output_image}")

    # Parse Gerber file
    print("\nParsing Gerber file...")
    parser = GerberParser(copper_file)
    geometry = parser.parse()
    trace_centerlines = parser.get_trace_centerlines()
    pads = parser.get_pads()
    drill_holes = parser.get_drill_holes()

    print(f"  Found {len(trace_centerlines)} trace centerlines")
    print(f"  Found {len(pads)} pads")

    # Generate fills WITHOUT isolation detection (for reference)
    print("\nGenerating normal fills...")
    fill_gen_normal = FillGenerator(
        line_spacing=0.1,
        initial_offset=0.05,
        double_expose_isolated=False
    )
    normal_result = fill_gen_normal.generate_fill(
        geometry,
        trace_centerlines=trace_centerlines,
        pads=pads,
        drill_holes=drill_holes
    )

    # Generate fills WITH isolation detection
    print(f"\nGenerating fills with isolation detection (threshold={isolation_threshold}mm)...")
    fill_gen_isolated = FillGenerator(
        line_spacing=0.1,
        initial_offset=0.05,
        double_expose_isolated=True,
        isolation_threshold=isolation_threshold
    )
    isolated_result = fill_gen_isolated.generate_fill(
        geometry,
        trace_centerlines=trace_centerlines,
        pads=pads,
        drill_holes=drill_holes
    )

    normal_paths = isolated_result['normal']
    isolated_paths = isolated_result['isolated']

    print(f"\nResults:")
    print(f"  Normal paths: {len(normal_paths)}")
    print(f"  Isolated paths: {len(isolated_paths)}")
    print(f"  Total paths: {len(normal_paths) + len(isolated_paths)}")

    normal_length = sum(p.length for p in normal_paths)
    isolated_length = sum(p.length for p in isolated_paths)
    print(f"\n  Normal path length: {normal_length:.2f}mm")
    print(f"  Isolated path length: {isolated_length:.2f}mm (will be exposed twice)")
    print(f"  Percentage isolated: {(isolated_length / (normal_length + isolated_length) * 100):.1f}%")

    # Create visualization
    print(f"\nCreating visualization...")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(20, 10))

    # Plot 1: Copper geometry + all paths
    ax1.set_title('Copper Geometry + All Fill Paths', fontsize=14, fontweight='bold')
    ax1.set_aspect('equal')
    ax1.grid(True, alpha=0.3)
    ax1.set_xlabel('X (mm)')
    ax1.set_ylabel('Y (mm)')

    # Draw copper geometry
    if isinstance(geometry, MultiPolygon):
        for poly in geometry.geoms:
            plot_polygon(ax1, poly, facecolor='lightgray', edgecolor='black', alpha=0.3, linewidth=0.5)
    elif isinstance(geometry, Polygon):
        plot_polygon(ax1, geometry, facecolor='lightgray', edgecolor='black', alpha=0.3, linewidth=0.5)

    # Draw all paths in light gray
    for path in normal_paths + isolated_paths:
        coords = list(path.coords)
        xs, ys = zip(*coords)
        ax1.plot(xs, ys, color='gray', linewidth=0.5, alpha=0.5)

    # Plot 2: Isolated paths highlighted
    ax2.set_title(f'Isolated Features Highlighted (threshold={isolation_threshold}mm)', fontsize=14, fontweight='bold')
    ax2.set_aspect('equal')
    ax2.grid(True, alpha=0.3)
    ax2.set_xlabel('X (mm)')
    ax2.set_ylabel('Y (mm)')

    # Draw copper geometry
    if isinstance(geometry, MultiPolygon):
        for poly in geometry.geoms:
            plot_polygon(ax2, poly, facecolor='lightgray', edgecolor='black', alpha=0.3, linewidth=0.5)
    elif isinstance(geometry, Polygon):
        plot_polygon(ax2, geometry, facecolor='lightgray', edgecolor='black', alpha=0.3, linewidth=0.5)

    # Draw normal paths in blue
    for path in normal_paths:
        coords = list(path.coords)
        xs, ys = zip(*coords)
        ax2.plot(xs, ys, color='blue', linewidth=0.8, alpha=0.6, label='Normal' if path == normal_paths[0] else '')

    # Draw isolated paths in red (thicker for visibility)
    for path in isolated_paths:
        coords = list(path.coords)
        xs, ys = zip(*coords)
        ax2.plot(xs, ys, color='red', linewidth=1.5, alpha=0.9, label='Isolated (2x exposure)' if path == isolated_paths[0] else '')

    # Add legend
    ax2.legend(loc='upper right', fontsize=10)

    # Add stats text box
    stats_text = f"Statistics:\n"
    stats_text += f"Normal paths: {len(normal_paths)} ({normal_length:.1f}mm)\n"
    stats_text += f"Isolated paths: {len(isolated_paths)} ({isolated_length:.1f}mm)\n"
    stats_text += f"Isolated %: {(isolated_length / (normal_length + isolated_length) * 100):.1f}%"

    ax2.text(0.02, 0.98, stats_text, transform=ax2.transAxes,
             verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
             fontsize=9, family='monospace')

    plt.tight_layout()
    plt.savefig(output_image, dpi=300, bbox_inches='tight')
    print(f"\nVisualization saved to: {output_image}")
    print("\nDone!")

    return {
        'normal_paths': len(normal_paths),
        'isolated_paths': len(isolated_paths),
        'normal_length': normal_length,
        'isolated_length': isolated_length
    }

def plot_polygon(ax, poly, **kwargs):
    """Helper to plot a polygon."""
    if poly.is_empty:
        return

    # Plot exterior
    x, y = poly.exterior.xy
    ax.fill(x, y, **kwargs)

    # Plot holes
    for interior in poly.interiors:
        x, y = interior.xy
        ax.fill(x, y, color='white', zorder=2)

if __name__ == "__main__":
    # Test with the specified Gerber files
    gerber_folder = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13")

    if not gerber_folder.exists():
        print(f"Error: Folder not found: {gerber_folder}")
        sys.exit(1)

    copper_file, outline_file = find_gerber_files(gerber_folder)

    if not copper_file:
        print("Error: Could not find copper layer file")
        sys.exit(1)

    # Test with different isolation thresholds
    print("\n" + "="*60)
    print("Testing with isolation_threshold = 3.0mm")
    print("="*60)
    visualize_isolated_features(
        copper_file,
        output_image="isolated_features_3mm.png",
        isolation_threshold=3.0
    )

    print("\n" + "="*60)
    print("Testing with isolation_threshold = 5.0mm")
    print("="*60)
    visualize_isolated_features(
        copper_file,
        output_image="isolated_features_5mm.png",
        isolation_threshold=5.0
    )
