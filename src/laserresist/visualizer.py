"""Visualization tools for PCB geometry and fill patterns."""

from pathlib import Path
from typing import Union, List, Optional
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MPLPolygon
from matplotlib.collections import PatchCollection
from shapely.geometry import Polygon, MultiPolygon, LineString


class PCBVisualizer:
    """Visualize PCB geometry and laser paths."""

    def __init__(self, figsize=(12, 10)):
        """Initialize the visualizer.

        Args:
            figsize: Figure size in inches (width, height)
        """
        self.figsize = figsize
        self.fig = None
        self.ax = None

    def plot_geometry(
        self,
        geometry: Union[Polygon, MultiPolygon],
        color: str = "gold",
        alpha: float = 0.9,
        edgecolor: str = "darkgoldenrod",
        linewidth: float = 0.5,
    ):
        """Plot Shapely polygon geometry.

        Args:
            geometry: Polygon or MultiPolygon to plot
            color: Fill color for polygons
            alpha: Transparency (0-1)
            edgecolor: Edge color
            linewidth: Edge line width
        """
        if self.fig is None:
            self.fig, self.ax = plt.subplots(figsize=self.figsize)
            self.ax.set_aspect("equal")
            self.ax.set_facecolor("#1a1a1a")  # Dark background like PCB
            self.fig.patch.set_facecolor("#2a2a2a")

        # Convert to list of polygons
        if isinstance(geometry, Polygon):
            polygons = [geometry]
        elif isinstance(geometry, MultiPolygon):
            polygons = list(geometry.geoms)
        else:
            return

        # Create matplotlib patches from Shapely polygons
        patches = []
        for poly in polygons:
            if poly.is_empty:
                continue

            # Get exterior coordinates
            exterior_coords = list(poly.exterior.coords)
            mpl_poly = MPLPolygon(exterior_coords, closed=True)
            patches.append(mpl_poly)

            # Handle holes
            for interior in poly.interiors:
                interior_coords = list(interior.coords)
                # Holes are rendered as polygons with background color
                hole_poly = MPLPolygon(interior_coords, closed=True)
                patches.append(hole_poly)

        # Create patch collection
        if patches:
            collection = PatchCollection(
                patches, facecolor=color, edgecolor=edgecolor, linewidth=linewidth, alpha=alpha
            )
            self.ax.add_collection(collection)

    def plot_paths(
        self,
        paths: List[LineString],
        color: str = "cyan",
        alpha: float = 0.6,
        linewidth: float = 0.3,
        label: str = "Laser paths",
    ):
        """Plot laser fill paths.

        Args:
            paths: List of LineString paths
            color: Line color
            alpha: Transparency
            linewidth: Line width
            label: Label for legend
        """
        if self.fig is None:
            self.fig, self.ax = plt.subplots(figsize=self.figsize)
            self.ax.set_aspect("equal")

        for path in paths:
            coords = list(path.coords)
            if len(coords) >= 2:
                x_coords = [c[0] for c in coords]
                y_coords = [c[1] for c in coords]
                self.ax.plot(x_coords, y_coords, color=color, alpha=alpha, linewidth=linewidth)

        # Add label to legend (only once)
        if paths:
            self.ax.plot([], [], color=color, alpha=alpha, linewidth=linewidth * 3, label=label)

    def set_bounds(self, min_x: float, min_y: float, max_x: float, max_y: float, margin: float = 2.0):
        """Set the plot bounds with margin.

        Args:
            min_x: Minimum X coordinate
            min_y: Minimum Y coordinate
            max_x: Maximum X coordinate
            max_y: Maximum Y coordinate
            margin: Margin around the geometry in mm
        """
        if self.ax is None:
            return

        self.ax.set_xlim(min_x - margin, max_x + margin)
        self.ax.set_ylim(min_y - margin, max_y + margin)

    def add_labels(self, title: str = "PCB Laser Exposure", show_grid: bool = True):
        """Add labels and styling to the plot.

        Args:
            title: Plot title
            show_grid: Whether to show grid
        """
        if self.ax is None:
            return

        self.ax.set_xlabel("X (mm)", color="white")
        self.ax.set_ylabel("Y (mm)", color="white")
        self.ax.set_title(title, color="white", fontsize=14, fontweight="bold")

        if show_grid:
            self.ax.grid(True, alpha=0.2, color="gray", linestyle="--", linewidth=0.5)

        # Style tick labels
        self.ax.tick_params(colors="white", which="both")

        # Add legend if there are labeled items
        if self.ax.get_legend_handles_labels()[0]:
            self.ax.legend(facecolor="#2a2a2a", edgecolor="gray", labelcolor="white")

    def save(self, output_path: Union[str, Path], dpi: int = 300):
        """Save the plot to a file.

        Args:
            output_path: Output file path (PNG, PDF, SVG, etc.)
            dpi: Resolution in dots per inch
        """
        if self.fig is None:
            return

        self.fig.tight_layout()
        self.fig.savefig(output_path, dpi=dpi, facecolor=self.fig.get_facecolor())
        print(f"Saved visualization to: {output_path}")

    def show(self):
        """Display the plot interactively."""
        if self.fig is None:
            return

        self.fig.tight_layout()
        plt.show()

    def close(self):
        """Close the plot."""
        if self.fig is not None:
            plt.close(self.fig)
            self.fig = None
            self.ax = None


def visualize_gerber(
    geometry: Union[Polygon, MultiPolygon],
    bounds: tuple,
    output_path: Optional[Union[str, Path]] = None,
    show: bool = False,
    title: str = "Parsed Gerber Geometry",
):
    """Quick function to visualize parsed Gerber geometry.

    Args:
        geometry: Parsed geometry
        bounds: Bounding box (min_x, min_y, max_x, max_y)
        output_path: Optional path to save the image
        show: Whether to display interactively
        title: Plot title
    """
    viz = PCBVisualizer()
    viz.plot_geometry(geometry)
    viz.set_bounds(*bounds)
    viz.add_labels(title=title)

    if output_path:
        viz.save(output_path)

    if show:
        viz.show()
    else:
        viz.close()
