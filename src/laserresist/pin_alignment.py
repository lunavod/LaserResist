"""Interactive pin alignment for PCB positioning."""

from typing import List, Dict, Tuple, Optional, Union
from shapely.geometry import Polygon, MultiPolygon, LineString
import matplotlib.pyplot as plt
from matplotlib.patches import Circle as MPLCircle, Polygon as MPLPolygon
from matplotlib.widgets import Button
import numpy as np


class PinAlignmentUI:
    """Interactive UI for selecting alignment pins using matplotlib."""

    def __init__(self):
        self.selected_holes = []
        self.all_holes = []
        self.hole_artists = {}
        self.selected_pins: Optional[Tuple[Dict, Dict]] = None
        self.cancelled = False
        self.confirmed = False

        self.fig = None
        self.ax = None
        self.text_status = None
        self.btn_confirm = None
        self.btn_cancel = None

    def show_board(
        self,
        geometry: Union[Polygon, MultiPolygon],
        bounds: tuple,
        pth_holes: List[Dict],
        npth_holes: List[Dict],
        trace_centerlines: List[LineString],
    ) -> Optional[Tuple[Dict, Dict]]:
        """Show interactive board visualization and get pin selection.

        Args:
            geometry: Copper geometry (pads and traces)
            bounds: Bounding box (min_x, min_y, max_x, max_y)
            pth_holes: List of PTH holes with x, y, diameter
            npth_holes: List of NPTH holes with x, y, diameter
            trace_centerlines: List of trace centerlines

        Returns:
            Tuple of (first_pin, second_pin) dicts with x, y, diameter, or None if cancelled
        """
        print("\nOpening pin alignment interface...")
        print("Please select two holes for alignment:")
        print("  1. Click first hole (bottom pin on laser table) - will turn green")
        print("  2. Click second hole (top pin on laser table) - will turn blue")
        print("  3. Click 'Confirm' or 'Cancel' button")

        # Combine all holes with type info
        self.all_holes = []
        for hole in pth_holes:
            self.all_holes.append({**hole, 'type': 'pth'})
        for hole in npth_holes:
            self.all_holes.append({**hole, 'type': 'npth'})

        # Create matplotlib figure
        self.fig, self.ax = plt.subplots(figsize=(14, 10))
        self.fig.canvas.manager.set_window_title('Pin Alignment - LaserResist')

        # Dark theme
        self.fig.patch.set_facecolor('#2a2a2a')
        self.ax.set_facecolor('#1a1a1a')

        # Plot copper geometry
        self._plot_copper(geometry)

        # Plot traces
        self._plot_traces(trace_centerlines)

        # Plot holes
        self._plot_holes()

        # Set bounds with margin
        min_x, min_y, max_x, max_y = bounds
        margin = max(max_x - min_x, max_y - min_y) * 0.1
        self.ax.set_xlim(min_x - margin, max_x + margin)
        self.ax.set_ylim(min_y - margin, max_y + margin)
        self.ax.set_aspect('equal')

        # Labels and title
        self.ax.set_xlabel('X (mm)', color='white')
        self.ax.set_ylabel('Y (mm)', color='white')
        self.ax.set_title('Pin Alignment Mode - Click holes to select',
                         color='#4CAF50', fontsize=14, fontweight='bold', pad=20)
        self.ax.tick_params(colors='white')
        self.ax.grid(True, alpha=0.2, color='gray', linestyle='--')

        # Status text
        self.text_status = self.fig.text(0.5, 0.95,
                                         'Click on first hole (bottom pin)...',
                                         ha='center', va='top',
                                         fontsize=11, color='#FFD700',
                                         bbox=dict(boxstyle='round', facecolor='#2a2a2a',
                                                  edgecolor='#4a4a4a', pad=0.5))

        # Add legend
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='#FFD700', edgecolor='#B8860B', label='Copper'),
            Patch(facecolor='#00BFFF', edgecolor='#0088CC', label='PTH Holes'),
            Patch(facecolor='#FF6B6B', edgecolor='#CC5555', label='NPTH Holes'),
            Patch(facecolor='#00FF00', edgecolor='#00AA00', label='1st Pin (bottom)'),
            Patch(facecolor='#0000FF', edgecolor='#0000AA', label='2nd Pin (top)'),
        ]
        self.ax.legend(handles=legend_elements, loc='upper right',
                      facecolor='#2a2a2a', edgecolor='#4a4a4a',
                      labelcolor='white', framealpha=0.95)

        # Add buttons
        ax_confirm = plt.axes([0.7, 0.02, 0.12, 0.04])
        ax_cancel = plt.axes([0.58, 0.02, 0.12, 0.04])

        self.btn_confirm = Button(ax_confirm, 'Confirm',
                                  color='#4CAF50', hovercolor='#45a049')
        self.btn_confirm.label.set_color('white')
        self.btn_confirm.on_clicked(self._on_confirm)

        self.btn_cancel = Button(ax_cancel, 'Cancel',
                                 color='#666', hovercolor='#555')
        self.btn_cancel.label.set_color('white')
        self.btn_cancel.on_clicked(self._on_cancel)

        # Connect events
        self.fig.canvas.mpl_connect('button_press_event', self._on_click)
        self.fig.canvas.mpl_connect('motion_notify_event', self._on_hover)

        # Show and wait
        plt.tight_layout(rect=[0, 0.05, 1, 0.94])
        plt.show()

        # Return result after window is closed
        if self.cancelled or not self.confirmed:
            return None

        return self.selected_pins

    def _plot_copper(self, geometry: Union[Polygon, MultiPolygon]):
        """Plot copper geometry."""
        polygons = []
        if isinstance(geometry, Polygon):
            polygons = [geometry]
        elif isinstance(geometry, MultiPolygon):
            polygons = list(geometry.geoms)

        for poly in polygons:
            if poly.is_empty:
                continue

            # Plot exterior
            exterior_coords = np.array(poly.exterior.coords)
            patch = MPLPolygon(exterior_coords, closed=True,
                             facecolor='#FFD700', edgecolor='#B8860B',
                             linewidth=0.5, alpha=0.9, zorder=1)
            self.ax.add_patch(patch)

            # Plot holes (interiors)
            for interior in poly.interiors:
                interior_coords = np.array(interior.coords)
                hole_patch = MPLPolygon(interior_coords, closed=True,
                                       facecolor='#1a1a1a', edgecolor='#B8860B',
                                       linewidth=0.5, zorder=2)
                self.ax.add_patch(hole_patch)

    def _plot_traces(self, trace_centerlines: List[LineString]):
        """Plot trace centerlines."""
        for line in trace_centerlines:
            coords = np.array(line.coords)
            if len(coords) >= 2:
                self.ax.plot(coords[:, 0], coords[:, 1],
                           color='#FFD700', linewidth=0.5, alpha=0.8, zorder=1)

    def _plot_holes(self):
        """Plot all drill holes."""
        for i, hole in enumerate(self.all_holes):
            x, y = hole['x'], hole['y']
            radius = hole['diameter'] / 2

            # Determine color based on type
            if hole['type'] == 'pth':
                facecolor = '#00BFFF'
                edgecolor = '#0088CC'
            else:
                facecolor = '#FF6B6B'
                edgecolor = '#CC5555'

            circle = MPLCircle((x, y), radius,
                              facecolor=facecolor, edgecolor=edgecolor,
                              linewidth=1, alpha=0.9, zorder=3,
                              picker=5)  # picker tolerance in points

            self.ax.add_patch(circle)
            self.hole_artists[i] = circle

    def _update_hole_colors(self):
        """Update hole colors based on selection."""
        for i, circle in self.hole_artists.items():
            hole = self.all_holes[i]

            # Check if this hole is selected
            if len(self.selected_holes) > 0 and self.selected_holes[0] == i:
                # First selection - green
                circle.set_facecolor('#00FF00')
                circle.set_edgecolor('#00AA00')
                circle.set_linewidth(3)
                circle.set_zorder(5)
            elif len(self.selected_holes) > 1 and self.selected_holes[1] == i:
                # Second selection - blue
                circle.set_facecolor('#0000FF')
                circle.set_edgecolor('#0000AA')
                circle.set_linewidth(3)
                circle.set_zorder(5)
            else:
                # Normal color
                if hole['type'] == 'pth':
                    circle.set_facecolor('#00BFFF')
                    circle.set_edgecolor('#0088CC')
                else:
                    circle.set_facecolor('#FF6B6B')
                    circle.set_edgecolor('#CC5555')
                circle.set_linewidth(1)
                circle.set_zorder(3)

        self.fig.canvas.draw_idle()

    def _update_status_text(self):
        """Update status text based on selection state."""
        if len(self.selected_holes) == 0:
            text = 'Click on first hole (bottom pin)...'
            color = '#FFD700'
        elif len(self.selected_holes) == 1:
            hole1 = self.all_holes[self.selected_holes[0]]
            text = f'1st: ({hole1["x"]:.2f}, {hole1["y"]:.2f}) {hole1["type"].upper()} Ø{hole1["diameter"]:.2f}mm - Click second hole (top pin)...'
            color = '#00FF00'
        else:
            hole1 = self.all_holes[self.selected_holes[0]]
            hole2 = self.all_holes[self.selected_holes[1]]
            text = f'1st: ({hole1["x"]:.2f}, {hole1["y"]:.2f}) - 2nd: ({hole2["x"]:.2f}, {hole2["y"]:.2f}) - Click Confirm or Cancel'
            color = '#4CAF50'

        self.text_status.set_text(text)
        self.text_status.set_color(color)
        self.fig.canvas.draw_idle()

    def _on_click(self, event):
        """Handle mouse click on holes."""
        if event.inaxes != self.ax:
            return

        # Find clicked hole
        clicked_hole = None
        for i, circle in self.hole_artists.items():
            if circle.contains(event)[0]:
                clicked_hole = i
                break

        if clicked_hole is None:
            return

        # Handle selection
        if clicked_hole in self.selected_holes:
            # Deselect
            self.selected_holes.remove(clicked_hole)
        elif len(self.selected_holes) < 2:
            # Select
            self.selected_holes.append(clicked_hole)

        self._update_hole_colors()
        self._update_status_text()

    def _on_hover(self, event):
        """Handle mouse hover for visual feedback."""
        if event.inaxes != self.ax:
            return

        # Highlight hovered hole
        hovered = False
        for i, circle in self.hole_artists.items():
            if circle.contains(event)[0]:
                # Don't change already selected holes
                if i not in self.selected_holes:
                    circle.set_linewidth(2)
                    hovered = True
            else:
                # Reset to normal if not selected
                if i not in self.selected_holes:
                    circle.set_linewidth(1)

        if hovered:
            self.fig.canvas.draw_idle()

    def _on_confirm(self, event):
        """Handle confirm button click."""
        if len(self.selected_holes) != 2:
            print(f"Please select exactly 2 holes before confirming.")
            return

        hole1 = self.all_holes[self.selected_holes[0]]
        hole2 = self.all_holes[self.selected_holes[1]]
        self.selected_pins = (hole1, hole2)

        self.confirmed = True
        self.cancelled = False

        plt.close(self.fig)

    def _on_cancel(self, event):
        """Handle cancel button click."""
        self.cancelled = True
        self.confirmed = False
        self.selected_pins = None
        plt.close(self.fig)

def get_pin_alignment_transform(pin1: Dict, pin2: Dict) -> Dict[str, float]:
    """Calculate coordinate transformation from pin alignment.

    Args:
        pin1: First selected pin (bottom pin) with x, y
        pin2: Second selected pin (top pin) with x, y

    Returns:
        Dict with transformation parameters:
        - rotate_180: bool, whether to rotate 180 degrees
        - translate_x: X translation to apply
        - translate_y: Y translation to apply
        - origin_x: New origin X coordinate
        - origin_y: New origin Y coordinate
    """
    # Check if first pin is lower than second pin
    if pin1['y'] < pin2['y']:
        # Normal orientation - first pin is physically lower
        # Just translate so first pin becomes origin
        return {
            'rotate_180': False,
            'translate_x': -pin1['x'],
            'translate_y': -pin1['y'],
            'origin_x': pin1['x'],
            'origin_y': pin1['y'],
        }
    else:
        # Upside down - first pin is physically higher
        # Rotate 180° and set first pin as origin
        return {
            'rotate_180': True,
            'translate_x': -pin1['x'],
            'translate_y': -pin1['y'],
            'origin_x': pin1['x'],
            'origin_y': pin1['y'],
        }
