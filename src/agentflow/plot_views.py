"""Comparison plots and reversible display axes; gate geometry stays in recipe coordinates."""

import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import FixedLocator, FuncFormatter, MaxNLocator

from .engine import make_transform
from .theme import BERRY

DENSITY = LinearSegmentedColormap.from_list("flow_density", ["#93bab2", "#3d6b60", "#102f29"])


def subset_indices(size, maximum=20000):
    if size <= maximum:
        return np.arange(size)
    return np.sort(np.random.default_rng(42).choice(size, maximum, replace=False))


def draw_events(
    ax,
    data,
    channels,
    kind="density",
    color=BERRY,
    name=None,
    point_size=7,
    opacity=0.65,
    normalization="count",
    bins=None,
):
    """Density uses every event; only scatter is deterministically downsampled."""
    if len(channels) == 1:
        bins = 100 if bins is None else bins
        counts, edges = np.histogram(data[:, 0], bins=bins)
        values = counts.astype(float)
        if normalization == "area" and values.sum():
            values /= values.sum() * np.diff(edges)
        elif normalization == "peak" and values.max():
            values = values / values.max() * 100
        ax.stairs(
            values,
            edges,
            color=color,
            label=name,
            linewidth=1.7,
            fill=name is None,
            alpha=opacity,
        )
        ax.set_ylabel(
            {"count": "Events / bin", "area": "Probability density", "peak": "% of peak"}[normalization]
        )
    elif len(data):
        if kind == "scatter":
            selected = data[subset_indices(len(data))]
            ax.scatter(
                selected[:, 0],
                selected[:, 1],
                s=point_size,
                alpha=opacity,
                c=color,
                edgecolors="none",
                label=name,
                rasterized=True,
            )
        elif kind == "contour":
            hist, xe, ye = np.histogram2d(data[:, 0], data[:, 1], bins=55)
            from scipy.ndimage import gaussian_filter

            smooth = gaussian_filter(hist, 1.1)
            if smooth.max() > 0:
                ax.contour(
                    (xe[:-1] + xe[1:]) / 2,
                    (ye[:-1] + ye[1:]) / 2,
                    smooth.T,
                    levels=np.unique(smooth.max() * np.array([0.1, 0.3, 0.6, 0.85])),
                    colors=[color],
                    linewidths=1.3,
                )
                if name:
                    ax.plot([], [], color=color, label=name)
        else:
            ax.hexbin(
                data[:, 0],
                data[:, 1],
                gridsize=110,
                mincnt=1,
                bins="log",
                cmap=DENSITY,
                linewidths=0,
                rasterized=True,
            )
    else:
        ax.text(0.5, 0.5, "No parent events", transform=ax.transAxes, ha="center")
    ax.set_xlabel(channels[0])
    if len(channels) == 2:
        ax.set_ylabel(channels[1])


def display_spec(kind):
    if kind == "linear":
        return {"kind": "linear"}
    if kind == "asinh":
        return {"kind": "asinh", "cofactor": 150}
    return {
        "kind": "logicle",
        "parameters": {"param_t": 262144, "param_w": 0.5, "param_m": 4.5, "param_a": 0},
    }


def apply_axes(ax, channels, recipe, modes):
    """Axis functions change the view only, retaining canonical event/gate coordinates.

    Noncanonical views are inspection-only in the GUI. This avoids mistaking a
    straight display-space polygon edge for a straight canonical-space edge.
    """
    for i, channel in enumerate(channels):
        canonical = make_transform(recipe["transforms"][channel])
        mode = modes[i]
        target = canonical if mode == "recipe" else make_transform(display_spec(mode))

        def forward(values, old=canonical, new=target):
            values = np.asarray(values, dtype=float)
            raw = values if old is None else old.inverse(values)
            return raw if new is None else new.apply(raw)

        def inverse(values, old=canonical, new=target):
            values = np.asarray(values, dtype=float)
            raw = values if new is None else new.inverse(values)
            return raw if old is None else old.apply(raw)

        if i == 0:
            ax.set_xscale("function", functions=(forward, inverse))
            axis, limits = ax.xaxis, ax.get_xlim()
        else:
            ax.set_yscale("function", functions=(forward, inverse))
            axis, limits = ax.yaxis, ax.get_ylim()
        raw = np.asarray(limits) if canonical is None else canonical.inverse(np.asarray(limits))
        raw_ticks = np.array([-1e7, -1e6, -1e5, -1e4, -1e3, -100, -10, 0, 10, 100, 1e3, 1e4, 1e5, 1e6, 1e7])
        if (mode == "linear") or (mode == "recipe" and canonical is None):
            raw_ticks = MaxNLocator(nbins=4).tick_values(raw[0], raw[1])
        raw_ticks = raw_ticks[(raw_ticks >= raw[0]) & (raw_ticks <= raw[1])]
        positions = raw_ticks if canonical is None else canonical.apply(raw_ticks)
        # Avoid crowded labels in the central linear region.
        transformed = forward(positions)
        if len(transformed) > 1:
            span = float(forward(np.array(limits))[1] - forward(np.array(limits))[0])
            # Anchor at zero when visible, then place sufficiently separated decades.
            order = sorted(range(len(transformed)), key=lambda j: (raw_ticks[j] != 0, abs(raw_ticks[j])))
            chosen = []
            for j in order:
                if all(abs(transformed[j] - transformed[k]) >= abs(span) * 0.11 for k in chosen):
                    chosen.append(j)
            positions = positions[sorted(chosen)]
        axis.set_major_locator(FixedLocator(positions))

        def formatter(value, position, transform=canonical):
            raw_value = float(value if transform is None else transform.inverse(np.array([value]))[0])
            if abs(raw_value) >= 1e6:
                return f"{raw_value / 1e6:.3g}M"
            if abs(raw_value) >= 1000:
                return f"{raw_value / 1000:.3g}k"
            return f"{raw_value:.3g}"

        axis.set_major_formatter(FuncFormatter(formatter))
        axis.set_label_text(
            channel + " · " + (recipe["transforms"][channel]["kind"] if mode == "recipe" else mode)
        )


def draw_boundary(ax, gate, color="#e2655e", linewidth=1.7, pickable=False, recipe=None):
    """Densify canonical polygon edges before nonlinear display transforms."""
    if gate["kind"] == "ratio":
        if recipe is None:
            raise ValueError("Drawing a ratio boundary requires its display transforms")
        tx, ty = [make_transform(recipe["transforms"][c]) for c in gate["channels"]]
        displayed_y = np.linspace(*ax.get_ylim(), 512)
        signal_y = displayed_y if ty is None else ty.inverse(displayed_y)
        keep = signal_y > gate["denominator_min"]
        artists = []
        for bound in gate["bounds"]:
            signal_x = signal_y[keep] * bound
            displayed_x = signal_x if tx is None else tx.apply(signal_x)
            artists.extend(
                ax.plot(
                    displayed_x,
                    displayed_y[keep],
                    color=color,
                    linewidth=linewidth,
                    picker=6 if pickable else False,
                    scalex=False,
                    scaley=False,
                )
            )
        floor = gate["denominator_min"]
        artists.append(
            ax.axhline(
                floor if ty is None else ty.apply(np.array([floor]))[0],
                color=color,
                ls=":",
                linewidth=linewidth,
            )
        )
        return artists
    if gate["kind"] == "boolean":
        return []
    if gate["kind"] == "range":
        return [
            ax.axvline(v, color=color, linewidth=linewidth, picker=6 if pickable else False)
            for v in gate["bounds"]
            if v is not None
        ]
    if gate["kind"] == "rectangle":
        a, b, c, d = gate["bounds"]
        points = np.array([[a, c], [b, c], [b, d], [a, d]])
    else:
        points = np.asarray(gate["vertices"])
    dense = np.concatenate([np.linspace(a, b, 65) for a, b in zip(points, np.roll(points, -1, axis=0))])
    return ax.plot(
        dense[:, 0], dense[:, 1], color=color, linewidth=linewidth, picker=6 if pickable else False
    )
