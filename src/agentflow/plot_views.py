"""Comparison plots and reversible display axes; gate geometry stays in recipe coordinates."""

import numpy as np
from matplotlib.colors import LinearSegmentedColormap, LogNorm
from matplotlib.ticker import FixedLocator, FuncFormatter, MaxNLocator

from .channel_names import channel_label as _channel_label
from .engine import make_transform
from .theme import BERRY

DENSITY = LinearSegmentedColormap.from_list(
    "flow_density", ["#1739d4", "#00bfff", "#00d65c", "#ffe600", "#ef1717"]
)


def plot_channels(gate, recipe, view=None):
    """A second display axis does not turn a one-dimensional gate into a 2D gate."""
    view = view or {}
    channels = list(gate["channels"])
    if gate["kind"] == "range" and view.get("plot_type", "Density dots") != "Histogram":
        candidates = [view.get("range_y_channel"), "SSC-A", "FSC-A", *recipe["transforms"]]
        other = next((c for c in candidates if c in recipe["transforms"] and c not in channels), None)
        if other is not None:
            channels.append(other)
    return channels


def density_points(data, limits=None, maximum=20000):
    """Color deterministic display dots using all finite parent events in 128×128 bins."""
    data = np.asarray(data)
    data = data[np.isfinite(data).all(axis=1)]
    if limits is not None:
        data = data[((data >= limits[0]) & (data <= limits[1])).all(axis=1)]
    if not len(data):
        return data, np.empty(0)
    # Bin over the central events, not the axis: fixed full-range axes would
    # otherwise give a cell cloud a handful of coarse bins. Edge bins absorb the tails.
    low, high = np.quantile(data, [0.005, 0.995], axis=0)
    span = np.maximum(high - low, 1e-9)
    counts, xe, ye = np.histogram2d(
        data[:, 0], data[:, 1], bins=128, range=list(zip(low - span * 0.02, high + span * 0.02))
    )
    selected = data[subset_indices(len(data), maximum)]
    x = np.clip(np.searchsorted(xe, selected[:, 0], side="right") - 1, 0, 127)
    y = np.clip(np.searchsorted(ye, selected[:, 1], side="right") - 1, 0, 127)
    density = counts[x, y]
    order = np.argsort(density, kind="stable")
    return selected[order], density[order]


def subset_indices(size, maximum=20000):
    if size <= maximum:
        return np.arange(size)
    return np.sort(np.random.default_rng(42).choice(size, maximum, replace=False))


def draw_events(
    ax,
    data,
    channels,
    kind="density dots",
    color=BERRY,
    name=None,
    point_size=7,
    opacity=0.65,
    normalization="count",
    bins=None,
    limits=None,
):
    """Bin density at the displayed range; all-event gate counts are independent."""
    if len(channels) == 2 and kind == "histogram":
        kind = "density dots"
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
        if kind == "density dots":
            selected, density = density_points(data, limits)
            ax.scatter(
                selected[:, 0],
                selected[:, 1],
                c=density,
                cmap=DENSITY,
                norm=LogNorm(vmin=1, vmax=max(2, density.max()) if len(density) else 2),
                s=point_size,
                alpha=opacity,
                edgecolors="none",
                rasterized=True,
            )
        elif kind == "scatter":
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
            hist, xe, ye = np.histogram2d(
                data[:, 0],
                data[:, 1],
                bins=55,
                range=None if limits is None else list(zip(limits[0], limits[1])),
            )
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
                extent=None if limits is None else (limits[0][0], limits[1][0], limits[0][1], limits[1][1]),
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


def apply_axes(ax, channels, recipe, modes, sample=None):
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
            if mode == "recipe":
                ax.set_xscale("linear")
            else:
                ax.set_xscale("function", functions=(forward, inverse))
            axis, limits = ax.xaxis, ax.get_xlim()
        else:
            if mode == "recipe":
                ax.set_yscale("linear")
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
            (channel if sample is None else _channel_label(sample, channel))
            + " · "
            + (recipe["transforms"][channel]["kind"] if mode == "recipe" else mode)
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
    if gate["kind"] == "quadrant":
        x = next(v for v in gate["bounds"][:2] if v is not None)
        y = next(v for v in gate["bounds"][2:] if v is not None)
        return [ax.axvline(x, color=color, linewidth=linewidth),
                ax.axhline(y, color=color, linewidth=linewidth)]
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


def scatter_limits(data, channels, full_range=False):
    """Display-only scatter limits; never filter the analytical event array."""
    data = np.asarray(data)
    if data.ndim != 2 or not len(data) or len(channels) != 2:
        return None
    if not all(c.startswith(("FSC-", "SSC-")) for c in channels):
        return None
    data = data[np.isfinite(data).all(axis=1)]
    if not len(data):
        return None
    low, high = np.quantile(data, [0, 1] if full_range else [0.005, 0.995], axis=0)
    margin = np.maximum((high - low) * 0.08, 1)
    return low - margin, high + margin


SCATTER_PREFIXES = ("FSC", "SSC", "BSC")
DEFAULT_RANGE = 262144.0


def instrument_range(sample, channel):
    """The detector's $PnR, the top of FlowJo's fixed axis; 2^18 when unknown."""
    try:
        value = float(sample.channels.iloc[sample.pnn_labels.index(channel)]["pnr"])
    except (AttributeError, ValueError, KeyError, IndexError, TypeError):
        return DEFAULT_RANGE
    return value if np.isfinite(value) and value > 0 else DEFAULT_RANGE


def axis_range(recipe, channel, sample=None, locked=None):
    """Display limits for one parameter in recipe coordinates, never from events.

    A locked range (raw units) wins. Otherwise the top is the logicle T or the
    instrument range; the bottom is 0 for linear scatter, else the biexponential
    floor (logicle display 0, about -111 for T = 262144) so negative compensated
    events stay visible. The same parameter gets the same axis on every sample.
    """
    spec = recipe["transforms"][channel]
    transform = make_transform(spec)
    if locked is not None:
        raw = np.asarray(locked, dtype=float)
    else:
        if spec["kind"] == "logicle":
            top = float(spec["parameters"]["param_t"])
            low = float(transform.inverse(np.array([0.0]))[0])
        elif spec["kind"] == "linear" and channel.startswith(SCATTER_PREFIXES):
            top, low = instrument_range(sample, channel), 0.0
        else:
            top = instrument_range(sample, channel)
            floor = make_transform(
                {"kind": "logicle", "parameters": {"param_t": top, "param_w": 0.5, "param_m": 4.5, "param_a": 0}}
            )
            low = float(floor.inverse(np.array([0.0]))[0])
        raw = np.array([low, top])
    shown = raw if transform is None else transform.apply(raw)
    return float(shown[0]), float(shown[1])


def fixed_limits(recipe, channels, sample=None, gate=None, locked=None):
    """(low, high) arrays like scatter_limits, widened only to keep the gate visible."""
    locked = recipe.get("display", {}).get("axis_ranges", {}) if locked is None else locked
    low, high = np.array([axis_range(recipe, c, sample, locked.get(c)) for c in channels]).T
    if gate is not None and gate.get("channels") == list(channels[: len(gate["channels"])]):
        points = None
        if gate["kind"] == "polygon":
            points = np.asarray(gate["vertices"], dtype=float)
        elif gate["kind"] in ("rectangle", "range"):
            values = [np.nan if v is None else v for v in gate["bounds"]]
            points = np.asarray(values, dtype=float).reshape(-1, 2).T
        if points is not None:
            for dim in range(min(points.shape[1], len(channels))):
                finite = points[:, dim][np.isfinite(points[:, dim])]
                if len(finite):
                    low[dim], high[dim] = min(low[dim], finite.min()), max(high[dim], finite.max())
    return low, high


def set_limits(ax, limits, dims=2):
    if limits is None:
        return
    ax.set_xlim(limits[0][0], limits[1][0])
    if dims == 2:
        ax.set_ylim(limits[0][1], limits[1][1])
