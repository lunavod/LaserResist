"""Blooming simulation to detect under-exposed traces based on ambient light scatter."""

import sys
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from shapely.geometry import LineString, Polygon, MultiPolygon
import time
from multiprocessing import Pool, cpu_count
from functools import partial

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from laserresist.gerber_parser import GerberParser
from laserresist.fill_generator import FillGenerator


class BloomingSimulator:
    """Simulate laser blooming/scatter to identify under-exposed features."""

    def __init__(self, resolution=0.2, bloom_radius=2.0):
        """
        Args:
            resolution: Grid resolution in mm (smaller = more accurate but slower)
            bloom_radius: Bloom/scatter radius in mm (how far light spreads)
        """
        self.resolution = resolution
        self.bloom_radius = bloom_radius
        self.grid = None
        self.bounds = None
        self.grid_shape = None

    def create_grid(self, bounds):
        """Create the energy accumulation grid.

        Args:
            bounds: (min_x, min_y, max_x, max_y) in mm
        """
        min_x, min_y, max_x, max_y = bounds

        # Add padding for bloom
        padding = self.bloom_radius * 2
        min_x -= padding
        min_y -= padding
        max_x += padding
        max_y += padding

        self.bounds = (min_x, min_y, max_x, max_y)

        # Calculate grid size
        width = max_x - min_x
        height = max_y - min_y

        grid_width = int(np.ceil(width / self.resolution))
        grid_height = int(np.ceil(height / self.resolution))

        self.grid_shape = (grid_height, grid_width)
        self.grid = np.zeros(self.grid_shape, dtype=np.float32)

        print(f"  Grid created: {grid_width} x {grid_height} = {grid_width * grid_height:,} cells")
        print(f"  Grid bounds: ({min_x:.1f}, {min_y:.1f}) to ({max_x:.1f}, {max_y:.1f}) mm")

    def world_to_grid(self, x, y):
        """Convert world coordinates (mm) to grid indices."""
        min_x, min_y, _, _ = self.bounds
        grid_x = int((x - min_x) / self.resolution)
        grid_y = int((y - min_y) / self.resolution)
        return grid_x, grid_y

    def grid_to_world(self, grid_x, grid_y):
        """Convert grid indices to world coordinates (mm)."""
        min_x, min_y, _, _ = self.bounds
        x = min_x + grid_x * self.resolution
        y = min_y + grid_y * self.resolution
        return x, y

    def apply_bloom_at_point(self, x, y, intensity=1.0):
        """Apply circular bloom kernel at a world coordinate point.

        Args:
            x, y: World coordinates in mm
            intensity: Energy intensity (default 1.0)
        """
        # Convert to grid coordinates
        center_gx, center_gy = self.world_to_grid(x, y)

        # Calculate bloom radius in grid cells
        bloom_radius_cells = int(np.ceil(self.bloom_radius / self.resolution))

        # Create circular bloom kernel bounds
        min_gx = max(0, center_gx - bloom_radius_cells)
        max_gx = min(self.grid_shape[1], center_gx + bloom_radius_cells + 1)
        min_gy = max(0, center_gy - bloom_radius_cells)
        max_gy = min(self.grid_shape[0], center_gy + bloom_radius_cells + 1)

        # Apply bloom with distance-based falloff
        for gy in range(min_gy, max_gy):
            for gx in range(min_gx, max_gx):
                # Calculate distance from center
                dx = (gx - center_gx) * self.resolution
                dy = (gy - center_gy) * self.resolution
                distance = np.sqrt(dx*dx + dy*dy)

                if distance <= self.bloom_radius:
                    # Simple circular falloff: 1.0 at center, 0.0 at bloom_radius
                    # Using inverse square for more realistic light scatter
                    falloff = max(0.0, 1.0 - (distance / self.bloom_radius)**2)
                    self.grid[gy, gx] += intensity * falloff

    def simulate_path_exposure(self, path, sample_distance=0.1, min_samples=10):
        """Simulate exposure along a path with blooming.

        Args:
            path: LineString path
            sample_distance: Target sample spacing in mm (smaller = more accurate)
            min_samples: Minimum number of samples per path regardless of length
        """
        # Sample points along the path
        length = path.length

        # Calculate number of samples
        # Use max of: length-based samples OR minimum samples
        num_samples_by_length = max(2, int(np.ceil(length / sample_distance)))
        num_samples = max(num_samples_by_length, min_samples)

        # Sample at regular intervals (normalized along path)
        if num_samples == 2:
            coords = list(path.coords)  # Just start and end
        else:
            coords = [path.interpolate(i / (num_samples - 1), normalized=True).coords[0]
                     for i in range(num_samples)]

        # Apply bloom at each sampled point
        for x, y in coords:
            self.apply_bloom_at_point(x, y)

    def simulate_all_paths(self, paths, sample_distance=0.1, min_samples=10, num_workers=None):
        """Simulate exposure for all paths using parallel processing.

        Args:
            paths: List of LineString paths
            sample_distance: Target sample spacing in mm along path
            min_samples: Minimum samples per path (ensures short paths get adequate sampling)
            num_workers: Number of parallel workers (default: cpu_count())
        """
        if num_workers is None:
            num_workers = cpu_count()

        print(f"\n  Simulating bloom for {len(paths)} paths...")
        print(f"    Sample distance: {sample_distance}mm, min samples: {min_samples}")
        print(f"    Using {num_workers} parallel workers")
        start_time = time.time()

        # Split paths into chunks for parallel processing
        chunk_size = max(1, len(paths) // num_workers)
        path_chunks = [paths[i:i + chunk_size] for i in range(0, len(paths), chunk_size)]

        print(f"    Split into {len(path_chunks)} chunks of ~{chunk_size} paths each")

        # Process chunks in parallel
        with Pool(num_workers) as pool:
            process_func = partial(self._process_path_chunk,
                                   sample_distance=sample_distance,
                                   min_samples=min_samples)
            chunk_grids = pool.map(process_func, path_chunks)

        # Sum all grids
        print(f"    Merging results from {len(chunk_grids)} workers...")
        for chunk_grid in chunk_grids:
            self.grid += chunk_grid

        elapsed = time.time() - start_time
        print(f"  Simulation completed in {elapsed:.2f}s")
        print(f"  Max energy: {self.grid.max():.2f}")
        print(f"  Mean energy: {self.grid.mean():.2f}")

    def _process_path_chunk(self, paths, sample_distance, min_samples):
        """Process a chunk of paths and return the accumulated grid.

        This runs in a separate process.

        Args:
            paths: List of paths to process
            sample_distance: Sample spacing
            min_samples: Minimum samples per path

        Returns:
            numpy array with accumulated bloom energy for this chunk
        """
        # Create a local grid for this chunk
        chunk_grid = np.zeros(self.grid_shape, dtype=np.float32)

        # Process each path
        for path in paths:
            # Sample points along the path
            length = path.length
            num_samples_by_length = max(2, int(np.ceil(length / sample_distance)))
            num_samples = max(num_samples_by_length, min_samples)

            if num_samples == 2:
                coords = list(path.coords)
            else:
                coords = [path.interpolate(i / (num_samples - 1), normalized=True).coords[0]
                         for i in range(num_samples)]

            # Apply bloom at each sampled point to the chunk grid
            for x, y in coords:
                self._apply_bloom_to_grid(chunk_grid, x, y, intensity=1.0)

        return chunk_grid

    def _apply_bloom_to_grid(self, grid, x, y, intensity=1.0):
        """Apply bloom at a point to a specific grid (helper for parallel processing)."""
        center_gx, center_gy = self.world_to_grid(x, y)
        bloom_radius_cells = int(np.ceil(self.bloom_radius / self.resolution))

        min_gx = max(0, center_gx - bloom_radius_cells)
        max_gx = min(self.grid_shape[1], center_gx + bloom_radius_cells + 1)
        min_gy = max(0, center_gy - bloom_radius_cells)
        max_gy = min(self.grid_shape[0], center_gy + bloom_radius_cells + 1)

        for gy in range(min_gy, max_gy):
            for gx in range(min_gx, max_gx):
                dx = (gx - center_gx) * self.resolution
                dy = (gy - center_gy) * self.resolution
                distance = np.sqrt(dx*dx + dy*dy)

                if distance <= self.bloom_radius:
                    falloff = max(0.0, 1.0 - (distance / self.bloom_radius)**2)
                    grid[gy, gx] += intensity * falloff

    def get_path_energy(self, path, num_samples=20):
        """Get average energy along a path.

        Args:
            path: LineString path
            num_samples: Number of points to sample along path

        Returns:
            Average energy value along the path
        """
        # Sample points along the path
        energies = []

        for i in range(num_samples):
            point = path.interpolate(i / (num_samples - 1), normalized=True)
            x, y = point.x, point.y

            gx, gy = self.world_to_grid(x, y)

            # Check bounds
            if 0 <= gx < self.grid_shape[1] and 0 <= gy < self.grid_shape[0]:
                energies.append(self.grid[gy, gx])

        return np.mean(energies) if energies else 0.0

    def identify_underexposed_paths(self, paths, threshold_percentile=30):
        """Identify paths that received less blooming energy.

        Args:
            paths: List of LineString paths
            threshold_percentile: Paths below this percentile of energy are underexposed

        Returns:
            Tuple of (normal_paths, underexposed_paths, all_energies)
        """
        print(f"\n  Analyzing path exposure levels...")

        # Calculate energy for each path
        path_energies = []
        for i, path in enumerate(paths):
            if (i + 1) % 100 == 0:
                print(f"    Analyzed {i + 1}/{len(paths)} paths...")
            energy = self.get_path_energy(path, num_samples=20)
            path_energies.append(energy)

        path_energies = np.array(path_energies)

        # Calculate threshold based on percentile
        threshold = np.percentile(path_energies, threshold_percentile)

        print(f"\n  Energy statistics:")
        print(f"    Min: {path_energies.min():.2f}")
        print(f"    Max: {path_energies.max():.2f}")
        print(f"    Mean: {path_energies.mean():.2f}")
        print(f"    Median: {np.median(path_energies):.2f}")
        print(f"    {threshold_percentile}th percentile (threshold): {threshold:.2f}")

        # Classify paths
        normal_paths = []
        underexposed_paths = []

        for path, energy in zip(paths, path_energies):
            if energy < threshold:
                underexposed_paths.append(path)
            else:
                normal_paths.append(path)

        print(f"\n  Classification:")
        print(f"    Normal paths: {len(normal_paths)}")
        print(f"    Under-exposed paths: {len(underexposed_paths)}")
        print(f"    Under-exposed percentage: {len(underexposed_paths) / len(paths) * 100:.1f}%")

        return normal_paths, underexposed_paths, path_energies


def visualize_blooming(simulator, paths, normal_paths, underexposed_paths,
                        geometry, output_file="blooming_simulation.png"):
    """Create visualization of blooming simulation results."""

    print(f"\n  Creating visualization...")

    fig = plt.figure(figsize=(24, 10))
    gs = fig.add_gridspec(1, 3, width_ratios=[1, 1, 1])
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1])
    ax3 = fig.add_subplot(gs[2])

    # Plot 1: Energy heatmap
    ax1.set_title('Blooming Energy Heatmap', fontsize=14, fontweight='bold')
    ax1.set_aspect('equal')
    ax1.set_xlabel('X (mm)')
    ax1.set_ylabel('Y (mm)')

    # Create custom colormap (dark blue -> yellow -> red)
    colors = ['#000033', '#0000FF', '#00FFFF', '#FFFF00', '#FF0000']
    n_bins = 256
    cmap = LinearSegmentedColormap.from_list('bloom', colors, N=n_bins)

    # Get grid bounds for extent
    min_x, min_y, max_x, max_y = simulator.bounds

    # Plot heatmap with correct aspect ratio
    im = ax1.imshow(simulator.grid, cmap=cmap, origin='lower',
                    extent=[min_x, max_x, min_y, max_y],
                    interpolation='nearest', aspect='equal')

    plt.colorbar(im, ax=ax1, label='Accumulated Energy')

    # Overlay copper geometry outline
    if isinstance(geometry, MultiPolygon):
        for poly in geometry.geoms:
            x, y = poly.exterior.xy
            ax1.plot(x, y, 'white', linewidth=0.5, alpha=0.5)
    elif isinstance(geometry, Polygon):
        x, y = geometry.exterior.xy
        ax1.plot(x, y, 'white', linewidth=0.5, alpha=0.5)

    # Plot 2: All paths on copper
    ax2.set_title('All Fill Paths', fontsize=14, fontweight='bold')
    ax2.set_aspect('equal')
    ax2.grid(True, alpha=0.3)
    ax2.set_xlabel('X (mm)')
    ax2.set_ylabel('Y (mm)')

    # Draw copper geometry
    if isinstance(geometry, MultiPolygon):
        for poly in geometry.geoms:
            plot_polygon(ax2, poly, facecolor='lightgray', edgecolor='black',
                        alpha=0.3, linewidth=0.5)
    elif isinstance(geometry, Polygon):
        plot_polygon(ax2, geometry, facecolor='lightgray', edgecolor='black',
                    alpha=0.3, linewidth=0.5)

    # Draw all paths
    for path in paths:
        coords = list(path.coords)
        xs, ys = zip(*coords)
        ax2.plot(xs, ys, color='gray', linewidth=0.5, alpha=0.5)

    # Plot 3: Under-exposed paths highlighted
    ax3.set_title('Under-Exposed Paths (Need 2x Exposure)', fontsize=14, fontweight='bold')
    ax3.set_aspect('equal')
    ax3.grid(True, alpha=0.3)
    ax3.set_xlabel('X (mm)')
    ax3.set_ylabel('Y (mm)')

    # Draw copper geometry
    if isinstance(geometry, MultiPolygon):
        for poly in geometry.geoms:
            plot_polygon(ax3, poly, facecolor='lightgray', edgecolor='black',
                        alpha=0.3, linewidth=0.5)
    elif isinstance(geometry, Polygon):
        plot_polygon(ax3, geometry, facecolor='lightgray', edgecolor='black',
                    alpha=0.3, linewidth=0.5)

    # Draw normal paths in blue
    for i, path in enumerate(normal_paths):
        coords = list(path.coords)
        xs, ys = zip(*coords)
        label = 'Normal exposure' if i == 0 else ''
        ax3.plot(xs, ys, color='blue', linewidth=0.8, alpha=0.6, label=label)

    # Draw under-exposed paths in red (thicker)
    for i, path in enumerate(underexposed_paths):
        coords = list(path.coords)
        xs, ys = zip(*coords)
        label = 'Under-exposed (2x)' if i == 0 else ''
        ax3.plot(xs, ys, color='red', linewidth=1.5, alpha=0.9, label=label)

    # Add legend
    ax3.legend(loc='upper right', fontsize=10)

    # Add stats box
    normal_length = sum(p.length for p in normal_paths)
    under_length = sum(p.length for p in underexposed_paths)
    total_length = normal_length + under_length

    stats_text = f"Statistics:\n"
    stats_text += f"Normal: {len(normal_paths)} paths ({normal_length:.1f}mm)\n"
    stats_text += f"Under-exposed: {len(underexposed_paths)} paths ({under_length:.1f}mm)\n"
    stats_text += f"Under-exposed %: {under_length / total_length * 100:.1f}%\n"
    stats_text += f"\nBloom radius: {simulator.bloom_radius}mm\n"
    stats_text += f"Grid resolution: {simulator.resolution}mm"

    ax3.text(0.02, 0.98, stats_text, transform=ax3.transAxes,
             verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
             fontsize=9, family='monospace')

    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"  Visualization saved to: {output_file}")


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


def find_gerber_files(folder_path):
    """Find Gerber files in the folder."""
    folder = Path(folder_path)

    copper_patterns = ['*.gtl', '*.gbl', '*F.Cu.gbr', '*B.Cu.gbr', '*-F_Cu.gbr', '*-B_Cu.gbr']

    copper_file = None
    for pattern in copper_patterns:
        files = list(folder.glob(pattern))
        if files:
            copper_file = files[0]
            print(f"Found copper file: {copper_file.name}")
            break

    return copper_file


def run_blooming_simulation(copper_file, resolution=0.2, bloom_radius=2.0,
                             threshold_percentile=30, output_image="blooming_simulation.png"):
    """Run the complete blooming simulation."""

    print(f"\n{'='*60}")
    print(f"BLOOMING SIMULATION")
    print(f"{'='*60}")
    print(f"Copper file: {copper_file}")
    print(f"Grid resolution: {resolution}mm")
    print(f"Bloom radius: {bloom_radius}mm")
    print(f"Under-exposure threshold: {threshold_percentile}th percentile")
    print(f"{'='*60}")

    # Parse Gerber
    print("\n[1/5] Parsing Gerber file...")
    parser = GerberParser(copper_file)
    geometry = parser.parse()
    trace_centerlines = parser.get_trace_centerlines()
    pads = parser.get_pads()
    drill_holes = parser.get_drill_holes()

    # Generate fill paths
    print("\n[2/5] Generating fill paths...")
    fill_gen = FillGenerator(line_spacing=0.1, initial_offset=0.05)
    paths = fill_gen.generate_fill(geometry, trace_centerlines=trace_centerlines,
                                    pads=pads, drill_holes=drill_holes)

    print(f"  Generated {len(paths)} paths")

    # Calculate bounds
    min_x, min_y, max_x, max_y = geometry.bounds
    bounds = (min_x, min_y, max_x, max_y)

    # Create simulator
    print("\n[3/5] Creating blooming simulator...")
    simulator = BloomingSimulator(resolution=resolution, bloom_radius=bloom_radius)
    simulator.create_grid(bounds)

    # Simulate exposure
    print("\n[4/5] Simulating laser exposure with bloom...")
    simulator.simulate_all_paths(paths, sample_distance=0.1, min_samples=10)

    # Identify under-exposed paths
    print("\n[5/5] Identifying under-exposed paths...")
    normal_paths, underexposed_paths, energies = simulator.identify_underexposed_paths(
        paths, threshold_percentile=threshold_percentile
    )

    # Visualize
    visualize_blooming(simulator, paths, normal_paths, underexposed_paths,
                       geometry, output_image)

    print(f"\n{'='*60}")
    print("SIMULATION COMPLETE!")
    print(f"{'='*60}\n")

    return {
        'normal_paths': len(normal_paths),
        'underexposed_paths': len(underexposed_paths),
        'normal_length': sum(p.length for p in normal_paths),
        'underexposed_length': sum(p.length for p in underexposed_paths)
    }


if __name__ == "__main__":
    # Required for multiprocessing on Windows
    import multiprocessing
    multiprocessing.freeze_support()

    # Test with the specified Gerber files
    gerber_folder = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13")

    if not gerber_folder.exists():
        print(f"Error: Folder not found: {gerber_folder}")
        sys.exit(1)

    copper_file = find_gerber_files(gerber_folder)

    if not copper_file:
        print("Error: Could not find copper layer file")
        sys.exit(1)

    # Run simulation with different parameters
    print("\n" + "="*80)
    print("TEST 1: Fine grid (2mm bloom, 0.05mm resolution - 2x finer than line spacing)")
    print("="*80)
    run_blooming_simulation(
        copper_file,
        resolution=0.05,
        bloom_radius=2.0,
        threshold_percentile=30,
        output_image="blooming_2mm_30pct.png"
    )

    print("\n" + "="*80)
    print("TEST 2: Wider bloom (3mm bloom, 0.15mm resolution)")
    print("="*80)
    run_blooming_simulation(
        copper_file,
        resolution=0.15,
        bloom_radius=3.0,
        threshold_percentile=30,
        output_image="blooming_3mm_30pct.png"
    )
