"""FlowJo-style N×N compensation check. Drawing only: edits live in spillover_edit."""

import numpy as np

from .channel_names import channel_label
from .engine import make_transform
from .plot_views import apply_axes, axis_range, subset_indices
from .spillover_edit import compensate_events
from .theme import CORAL, INK
from .workflow import default_transform

COMPENSATED_COLOR = INK
UNCOMPENSATED_COLOR = CORAL
DISPLAY_EVENTS = 5000


def matrix_channels(prepared):
    """Compensated detectors in matrix order; acquired fluorescence detectors when none applies."""
    sample = prepared.sample
    if prepared.matrix is not None:
        return [c for c in prepared.matrix.detectors if c in sample.pnn_labels]
    return [sample.pnn_labels[i] for i in sample.fluoro_indices]


def display_recipe(recipe, sample, channels):
    """Recipe transforms, plus FlowJo defaults for matrix detectors the recipe never gates on."""
    defaults = {c: default_transform(sample, c) for c in channels if c not in recipe["transforms"]}
    return {**recipe, "transforms": {**recipe["transforms"], **defaults}}


def matrix_events(prepared, recipe, channels, mask=None, maximum=DISPLAY_EVENTS, draft=None):
    """The same display subset, compensated and uncompensated, in recipe display coordinates.

    With a draft matrix spec, the compensated events come from FlowKit applying
    that draft to the raw events instead of the sample's assigned matrix.
    """
    rows = np.arange(len(prepared.values)) if mask is None else np.flatnonzero(np.asarray(mask))
    rows = rows[subset_indices(len(rows), maximum)]
    columns = [prepared.sample.pnn_labels.index(c) for c in channels]
    if draft is None:
        compensated = prepared.values[channels].to_numpy(dtype=float)[rows]
    else:
        compensated = np.asarray(compensate_events(prepared.sample, draft), dtype=float)[rows][:, columns]
    uncompensated = np.asarray(prepared.sample.get_events(source="raw"), dtype=float)[rows][:, columns]
    for k, channel in enumerate(channels):
        transform = make_transform(recipe["transforms"][channel])
        if transform is not None:
            compensated[:, k] = transform.apply(compensated[:, k])
            uncompensated[:, k] = transform.apply(uncompensated[:, k])
    return compensated, uncompensated


def draw_compensation_matrix(
    fig, prepared, recipe, channels, mask=None, overlay=False, locked=None, maximum=DISPLAY_EVENTS, draft=None
):
    """Upper-triangle grid as in FlowJo: row i plots detector i against each later detector.

    Axes come from each detector's range and transform (plot_views.axis_range), so
    flipping samples never moves them. The overlay draws the same events before
    compensation, on top, so residual spillover and its correction are visible.
    A draft matrix spec replaces the assigned matrix for the compensated events.
    Returns {(y_channel, x_channel): axes}.
    """
    fig.clear()
    channels = list(channels)
    if len(channels) < 2:
        ax = fig.add_subplot()
        ax.set_axis_off()
        ax.text(0.5, 0.5, "Choose at least two detectors", ha="center", transform=ax.transAxes)
        return {}
    sample, matrix = prepared.sample, prepared.matrix
    view = display_recipe(recipe, sample, channels)
    compensated, uncompensated = matrix_events(prepared, view, channels, mask, maximum, draft)
    overlay = overlay and matrix is not None
    locked = locked or {}
    names = {
        c: ("Comp-" if matrix is not None and c in matrix.detectors else "") + channel_label(sample, c)
        for c in channels
    }
    n = len(channels)
    grid = fig.add_gridspec(n - 1, n - 1)
    axes = {}
    for i in range(n - 1):
        for j in range(i + 1, n):
            ax = fig.add_subplot(grid[i, j - 1])
            x, y = channels[j], channels[i]
            ax.scatter(
                compensated[:, j],
                compensated[:, i],
                s=1.5,
                c=COMPENSATED_COLOR,
                edgecolors="none",
                rasterized=True,
                label="Compensated",
            )
            if overlay:
                ax.scatter(
                    uncompensated[:, j],
                    uncompensated[:, i],
                    s=1.5,
                    c=UNCOMPENSATED_COLOR,
                    alpha=0.45,
                    edgecolors="none",
                    rasterized=True,
                    label="Uncompensated",
                )
            ax.set_xlim(axis_range(view, x, sample, locked.get(x)))
            ax.set_ylim(axis_range(view, y, sample, locked.get(y)))
            apply_axes(ax, [x, y], view, ["recipe", "recipe"], sample=sample)
            ax.set_xlabel(names[x], fontsize=7)
            ax.set_ylabel(names[y], fontsize=7)
            ax.tick_params(labelsize=6, pad=1)
            axes[(y, x)] = ax
    if overlay:
        handles, labels = next(iter(axes.values())).get_legend_handles_labels()
        # The empty lower-left triangle keeps the legend off every plot.
        fig.legend(handles, labels, loc="lower left", fontsize=9, frameon=False, markerscale=6)
    return axes
