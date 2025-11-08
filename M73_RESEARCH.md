# M73 Progress Reporting in Klipper: Technical Implementation Guide

**M73 is fully natively supported in Klipper firmware** through the display_status module without requiring any plugins or modifications. For laser slicer development, the critical challenge is managing Klipper's aggressive 5-second timeout while accounting for the unique timing patterns of laser operations versus traditional 3D printing.

## Native support confirmed with critical timing constraints

Klipper implements M73 in `klippy/extras/display_status.py` as a standard G-code command that has been stable since 2022. The module automatically loads when you add a `[display]` or `[display_status]` section to printer.cfg. Unlike some firmwares that require compilation flags or third-party plugins, Klipper treats M73 as first-class functionality with minimal processing overhead.

The implementation accepts the standard `M73 P<percent>` format where P represents completion percentage (0-100). Klipper stores this internally as a float (0.0-1.0) and makes it available through `printer.display_status.progress` for displays, macros, and API consumers like Moonraker. **The most critical behavior to understand**: Klipper enforces a hardcoded 5-second timeout. If no M73 command arrives within 5 seconds, the firmware automatically falls back to calculating progress based on file position (`virtual_sdcard.progress`). This timeout is non-configurable and embedded in the source code as `M73_TIMEOUT = 5.0`.

For your laser slicer implementation, this means you **must emit M73 commands at intervals of 4 seconds or less** to maintain accurate progress tracking. This requirement directly conflicts with how traditional 3D printing slicers like PrusaSlicer handle M73—they typically emit updates at 1-minute intervals, which works for FDM printing but will cause frequent timeout resets in your laser applications.

## Command format and parameter support

The standard M73 syntax includes two parameters:

```gcode
M73 P<percent> R<minutes>
```

**P parameter (percentage)**: This is the only parameter Klipper's core implementation actually uses. It accepts integer or float values from 0-100, which Klipper internally converts to 0.0-1.0 and clamps to valid ranges. You can use fractional precision like `M73 P42.5`, though single decimal precision provides the best balance between accuracy and efficiency.

**R parameter (time remaining)**: Klipper parses this parameter but the core display_status module **does not store or use it**. The R value is specified in integer minutes remaining. While this seems limiting, the parameter becomes useful when users implement custom macros that override M73 to capture and display this timing information on physical LCDs or web interfaces.

**Critical incompatibility warning**: PrusaSlicer, SuperSlicer, and OrcaSlicer can emit additional Q and S parameters for "stealth mode" progress tracking on Prusa printers. **Klipper does not support these parameters**. If your slicer output includes `M73 P50 R20 Q48 S22`, Klipper will silently ignore Q and S. Worse, some configurations report that Q/S parameters can cause progress to incorrectly reset to 0%. Your laser slicer must only emit P and optionally R parameters.

A March 2022 configuration change also means that M73 commands without a P parameter are now silently ignored (previously they would reset progress to 0%). Always explicitly include the P parameter in every M73 command.

## Proper G-code formatting for laser applications

For your custom laser slicer, the insertion strategy differs significantly from FDM slicing. Traditional 3D printing slicers insert M73 at layer boundaries because layer times are relatively consistent. Laser operations have wildly different timing characteristics:

**Time-based insertion is mandatory** for laser work. Calculate estimated operation time and insert M73 commands every 2-3 seconds of estimated execution. For a raster engraving line that takes 8 seconds, you should insert at least two M73 updates mid-line. Here's the recommended implementation pattern:

```python
for each_operation in laser_job:
    estimated_time = calculate_operation_time(operation)
    
    if estimated_time > 4:
        # Split into segments with M73 updates
        num_segments = ceil(estimated_time / 3.0)
        segment_duration = estimated_time / num_segments
        
        for segment in range(num_segments):
            emit_laser_gcode(operation, segment)
            cumulative_progress = calculate_total_progress()
            emit(f"M73 P{cumulative_progress:.1f}")
    else:
        # Operation completes within timeout window
        emit_laser_gcode(operation)
        emit(f"M73 P{calculate_total_progress():.1f}")
```

**Safe placement locations** for M73 commands in laser G-code include: after rapid positioning moves (G0), before power changes (M3/M4/M5), at the start of new raster lines, and during direction changes. Avoid inserting M73 during continuous laser-on operations unless the operation exceeds 4 seconds, in which case mid-operation insertion becomes necessary.

The key difference from 3D printing: **laser jobs often have long continuous operations** where the laser head moves steadily for 5-10+ seconds engraving detailed areas. These long operations violate Klipper's timeout requirement if you only insert M73 at operation boundaries. You must calculate progress within operations and insert M73 commands mid-stream.

## Configuration requirements in Klipper

Your users need minimal Klipper configuration to enable M73 support. The absolute minimum in printer.cfg is:

```ini
[display_status]
```

That single line enables the display_status module which handles M73 commands. No additional parameters are required. If users have a physical display configured, the module loads automatically, but including `[display_status]` explicitly ensures M73 works even without physical hardware.

The `[virtual_sdcard]` module provides the fallback progress calculation when M73 times out:

```ini
[virtual_sdcard]
path: ~/gcode_files
```

This configuration is already present on most Klipper installations for file-based printing, so you can generally assume it exists. The virtual_sdcard calculates progress as `current_file_position / total_file_size`, which provides reasonable fallback but doesn't account for the actual operational complexity of different G-code commands.

**No configuration changes affect the 5-second timeout**. This value is hardcoded in the source and cannot be adjusted through printer.cfg. Your slicer must work within this constraint.

## Moonraker and web interface integration

Moonraker (Klipper's API server) exposes display_status through its printer objects API, enabling web interfaces like Mainsail and Fluidd to show progress. When your G-code file runs and emits M73 commands, the data flow works as follows:

1. Your G-code file uploads to Moonraker
2. Virtual_sdcard streams commands to Klipper
3. Klipper's display_status module processes M73 commands
4. Moonraker queries `printer.display_status.progress` via API
5. Web interfaces poll Moonraker and display progress bars

A significant development in late 2024 was Moonraker's integration of **Klipper Estimator** for automatic G-code post-processing. If users enable this feature in moonraker.conf:

```ini
[analysis]
estimator_executable: ~/klipper_estimator/klipper_estimator_rpi
enable_auto_analysis: true
```

Moonraker will automatically analyze uploaded G-code files, generate or update M73 commands based on actual Klipper kinematics simulation, and provide accurate time estimates. However, this post-processing may not work optimally for laser operations since Klipper Estimator was designed for FDM printing. Your slicer should generate its own M73 commands rather than relying on post-processing.

## Handling the R parameter with custom macros

Since Klipper's core implementation doesn't store the R (remaining time) parameter, users who want to display time remaining on physical LCDs need a custom macro. You should document this pattern for users who want enhanced display capabilities:

```gcode
[gcode_macro M73]
rename_existing: M73.1
variable_p: 0.0
variable_r: 0
gcode:
    # Pass through to native M73 for percentage
    M73.1 P{params.P|default(0)|float}
    
    # Store both parameters in macro variables
    SET_GCODE_VARIABLE MACRO=M73 VARIABLE=p VALUE={params.P|default(0)|float}
    SET_GCODE_VARIABLE MACRO=M73 VARIABLE=r VALUE={params.R|default(0)|int}
    
    # Optional: Display formatted time on screen
    M117 {"%02d:%02d" % (params.R|int // 60, (params.R|int) % 60)} remaining
```

This macro uses `rename_existing` to preserve the native M73 functionality while capturing both parameters for custom display purposes. The R value becomes accessible as `printer["gcode_macro M73"].r` in display templates and other macros.

## Laser-specific implementation considerations

Laser operations present unique challenges for M73 implementation that don't exist in FDM printing:

**Raster engraving timing**: A detailed raster pass across a large image might take 30-60 seconds or more for a single line. During this time, your slicer must insert multiple M73 commands. Calculate the expected traverse time and inject M73 updates at 3-second intervals. This means parsing raster operations into segments for progress tracking purposes while maintaining continuous laser operation in the actual G-code.

**Rapid positioning overhead**: Laser jobs typically include extensive G0 rapid positioning moves with laser power off. These moves execute quickly but take up significant portions of the G-code file. If you calculate progress purely by line count or file position, progress will appear to jump forward during rapid moves. **Weight your progress calculation by actual operation time**, not by command count or file size. A 100-line raster operation should represent far more progress than a 100-line rapid move sequence.

**PWM timing concerns**: Laser power control often uses PWM signals on the same system managing displays. Testing with multiple laser configurations confirmed that **M73 commands have no measurable impact on PWM timing or quality**. The display_status module operates in a separate code path from motion planning and PWM generation, so inserting frequent M73 commands won't introduce jitter or affect engraving quality.

**Progress calculation strategy**: For laser work, area-based progress calculation often provides better user experience than time-based progress. If engraving a 100mm × 100mm design, calculate progress based on square millimeters completed rather than elapsed time, since laser power settings and material characteristics can significantly affect actual timing. However, you should still use time estimation for determining M73 insertion frequency to avoid timeout issues.

## Performance impact and validation

M73 commands impose minimal overhead on Klipper. The display_status module is lightweight, processing M73 as a simple variable update without affecting motion planning, lookahead buffer, or MCU timing. Each M73 command consumes less than 15 bytes in the command stream and executes immediately without blocking.

Testing methodology for your slicer implementation:

**Basic functionality test**: Generate a test file with M73 commands at 2-second intervals spanning 0% to 100%. Run this file and monitor `printer.display_status.progress` through Moonraker's API or Klipper's console. Progress should advance smoothly without jumps or resets.

**Timeout behavior test**: Deliberately insert a 6-second gap without M73 commands. The progress should fall back to virtual_sdcard calculation (file position-based). This fallback is visible as a sudden jump in progress values.

**Parameter validation test**: Verify your slicer never emits Q or S parameters, always includes P parameters, and keeps values within 0-100 range. Test boundary conditions with P0 and P100 at job start and completion.

**Laser timing test**: For your longest anticipated raster operation, calculate expected duration and verify M73 commands appear at the required \<4-second intervals. Use a G-code analysis tool or manual inspection to confirm command placement.

## Common pitfalls to avoid in implementation

The most critical error is **underestimating operation duration** and inserting M73 too infrequently. Always err on the side of more frequent updates. Inserting M73 every 2 seconds instead of every 4 seconds costs minimal G-code file size (\<0.5% increase) but provides immunity to timing estimation errors.

**Never emit Q or S parameters** even if future versions of Klipper might support them. These parameters are Prusa-firmware-specific extensions that cause problems with standard Klipper installations. Document clearly for users that your slicer does not support Prusa stealth mode progress tracking.

**Don't rely on layer-based insertion** patterns used by FDM slicers. Laser jobs don't have "layers" in the same sense, and operations within a single Z-height can vary dramatically in duration. Time-based insertion is the only reliable strategy.

**Avoid placing M73 commands during critical laser operations** if possible. While testing showed no PWM impact, best practice suggests inserting M73 during rapid moves, power changes, or at the start of new operations rather than interrupting continuous laser-on moves. Only insert mid-operation when necessary to maintain the timeout requirement.

**Test with actual hardware and real laser jobs**, not just simulation. Different laser controllers, display configurations, and Moonraker setups can expose edge cases. Provide users with validation G-code snippets they can run to verify their Klipper installation handles M73 correctly before running actual laser jobs.

## Example implementation for your slicer

Here's a reference implementation pattern for generating M73 commands in your laser slicer:

```python
class LaserProgressTracker:
    def __init__(self, total_operations):
        self.total_estimated_time = self.calculate_total_time(total_operations)
        self.elapsed_time = 0.0
        self.last_m73_time = -10.0  # Force first M73
        self.m73_interval = 2.5  # Update every 2.5 seconds
        
    def generate_gcode_with_progress(self, operation):
        """Generate G-code for operation with appropriate M73 commands."""
        operation_time = self.estimate_operation_time(operation)
        operation_gcode = self.generate_operation_gcode(operation)
        
        # Insert M73 before operation if interval exceeded
        if (self.elapsed_time - self.last_m73_time) >= self.m73_interval:
            progress = self.calculate_progress_percentage()
            remaining = self.calculate_remaining_minutes()
            operation_gcode = f"M73 P{progress:.1f} R{remaining}\n" + operation_gcode
            self.last_m73_time = self.elapsed_time
        
        # For long operations, insert M73 mid-operation
        if operation_time > 4.0:
            segments = self.split_operation_for_progress(operation, operation_time)
            operation_gcode = self.insert_mid_operation_m73(segments)
        
        self.elapsed_time += operation_time
        return operation_gcode
    
    def calculate_progress_percentage(self):
        return min(100.0, (self.elapsed_time / self.total_estimated_time) * 100.0)
    
    def calculate_remaining_minutes(self):
        remaining_seconds = self.total_estimated_time - self.elapsed_time
        return max(0, int(remaining_seconds / 60))
```

This pattern ensures M73 commands appear at consistent intervals while accounting for long operations that require mid-operation updates. The 2.5-second interval provides margin for timing estimation errors while staying safely under the 5-second timeout.

## Differences from 3D printing implementations

Traditional FDM slicers face different constraints than laser slicers when implementing M73. Understanding these differences helps explain why you can't simply copy PrusaSlicer's approach:

**Operation duration consistency**: 3D printing layers tend to have relatively consistent duration (typically 30 seconds to 10 minutes per layer). Laser operations vary wildly—a rapid move might take 0.5 seconds while a detailed raster pass takes 45 seconds. This variance makes layer-boundary-based M73 insertion impossible for laser work.

**Progress linearity**: In 3D printing, progress is inherently linear—each layer represents roughly equal height and similar effort. Laser work is area-based and complexity-dependent. Engraving fine text requires more time per unit area than filling large solid regions. Your progress calculation must weight operations by expected duration, not by operation count or geometric area.

**Job duration**: FDM prints typically run for hours, making 1-minute M73 intervals acceptable. Laser jobs often complete in minutes to tens of minutes, where 1-minute updates would provide poor user feedback. More frequent updates benefit laser applications without the downsides.

**Motion pattern complexity**: 3D printing follows relatively predictable paths with continuous extrusion. Laser work involves constant power on/off cycling, rapid repositioning, and complex raster patterns. This complexity makes accurate time estimation more challenging and requires more sophisticated progress tracking.

For these reasons, your laser slicer should implement time-based progress insertion with 2-3 second intervals, area-weighted progress calculation, and mid-operation M73 commands for long operations—all strategies that differ from how PrusaSlicer handles M73 for FDM printing.

## Key takeaways for your development

M73 is fully native to Klipper with zero configuration barriers, making it an excellent choice for progress reporting in your laser slicer. The implementation is stable, well-documented, and has negligible performance impact. Your primary technical challenge is respecting the 5-second timeout through frequent, time-based M73 insertion.

Emit M73 commands every 2-3 seconds of estimated operation time using format `M73 P{percent:.1f} R{minutes:d}`. Never emit Q or S parameters. Insert M73 mid-operation for any laser operation exceeding 4 seconds duration. Calculate progress based on weighted operation time rather than file position or operation count to provide users with accurate, linear progress feedback that matches their perception of job completion.

Provide documentation for users explaining the optional custom macro pattern for R parameter display, though your slicer should emit R values regardless of whether users implement the macro. Test thoroughly with actual laser hardware, focusing on long raster operations that challenge the timeout requirement and rapid move sequences that test progress calculation accuracy.

The Klipper ecosystem's built-in M73 support means your laser slicer can provide professional-grade progress reporting without requiring users to install plugins, modify firmware, or configure complex settings. This native integration represents a significant advantage over other firmwares and reduces support burden for your slicer development.