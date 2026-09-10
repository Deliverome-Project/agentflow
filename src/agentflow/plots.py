"""Headless gate plots and acquisition diagnostics."""

import numpy as np

from .theme import BERRY, setup_plots


def new_figure(width=10, height=7):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    setup_plots()
    fig = Figure(figsize=(width, height))
    FigureCanvasAgg(fig)
    return fig


def draw_population(ax, prepared, gate, parent_mask, view=None):
    from .plot_views import draw_events

    view = view or {}
    data = prepared.transformed.loc[parent_mask, gate["channels"]].to_numpy()
    normalization = {"Event counts": "count", "Unit area": "area", "% of peak": "peak"}
    draw_events(
        ax,
        data,
        gate["channels"],
        view.get("plot_type", "Density").lower(),
        color=view.get("color", BERRY),
        point_size=view.get("point_size", 8),
        opacity=view.get("opacity", 65) / 100,
        normalization=normalization.get(view.get("normalization"), "count"),
    )


def draw_gate(ax, gate):
    from .plot_views import draw_boundary

    draw_boundary(ax, gate)
    ax.autoscale_view()


def save_qc(prepared, recipe, masks, path, sample_id):
    gates = recipe["gates"]
    fig = new_figure(5 * max(1, min(3, len(gates))), 4 * max(1, (len(gates) + 2) // 3))
    fig.suptitle(f"{recipe.get('experiment', {}).get('label', 'Gate review')}\n{sample_id}")
    if not gates:
        ax = fig.add_subplot(111)
        ax.text(0.5, 0.5, f"{prepared.sample.event_count:,} events; no gates", ha="center")
    for i, gate in enumerate(gates):
        ax = fig.add_subplot((len(gates) + 2) // 3, min(3, len(gates)), i + 1)
        view = recipe.get("display", {})
        population = gate["name"] if gate["kind"] == "boolean" else gate["parent"]
        draw_population(ax, prepared, gate, masks[population], view)
        draw_gate(ax, gate)
        ax.set_title(
            f"{gate.get('label', gate['name'])}\n{masks[gate['name']].sum():,} / {masks[gate['parent']].sum():,} — {'reviewed' if gate.get('reviewed') else 'DRAFT'}"
        )
        from .plot_views import apply_axes

        modes = [
            view.get(key, "Recipe scale").lower().replace(" scale", "") for key in ["x_scale", "y_scale"]
        ]
        apply_axes(ax, gate["channels"], recipe, modes)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="white")


def save_time_qc(prepared, path):
    if "Time" not in prepared.sample.pnn_labels:
        return
    raw = prepared.sample.get_events(source="raw")
    time = raw[:, prepared.sample.pnn_labels.index("Time")]
    finite = np.isfinite(time)
    fig = new_figure(10, 4)
    ax = fig.add_subplot(121)
    ax.hist(time[finite], bins=60, color=BERRY)
    ax.set(xlabel="Time (FCS-scaled units)", ylabel="Events / bin", title="Acquisition rate")
    ax = fig.add_subplot(122)
    if "FSC-A" in prepared.sample.pnn_labels:
        signal = raw[:, prepared.sample.pnn_labels.index("FSC-A")]
        ax.hexbin(time[finite], signal[finite], gridsize=65, mincnt=1, bins="log", cmap="BuPu")
    ax.set(xlabel="Time (FCS-scaled units)", ylabel="FSC-A", title="Scatter stability — descriptive only")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
