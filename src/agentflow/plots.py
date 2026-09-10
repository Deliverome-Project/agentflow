"""Headless gate plots and acquisition diagnostics."""

import numpy as np


def new_figure(width=10, height=7):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    fig = Figure(figsize=(width, height))
    FigureCanvasAgg(fig)
    return fig


def draw_population(ax, prepared, gate, parent_mask):
    data = prepared.transformed.loc[parent_mask, gate["channels"]]
    if gate["kind"] == "range":
        channel = gate["channels"][0]
        if len(data):
            ax.hist(data[channel], bins=100, color="#397988", alpha=0.8)
        ax.set_xlabel(channel)
        ax.set_ylabel("Events")
    else:
        x, y = gate["channels"]
        if len(data):
            ax.hexbin(data[x], data[y], gridsize=80, mincnt=1, bins="log", cmap="viridis")
        ax.set_xlabel(x)
        ax.set_ylabel(y)
    if not len(data):
        ax.text(0.5, 0.5, "Parent gate contains no events", transform=ax.transAxes, ha="center")


def draw_gate(ax, gate):
    from matplotlib.patches import Polygon, Rectangle

    if gate["kind"] == "range":
        for bound in gate["bounds"]:
            if bound is not None:
                ax.axvline(bound, color="#dd503b", lw=1.5)
    elif gate["kind"] == "polygon":
        ax.add_patch(Polygon(gate["vertices"], fill=False, edgecolor="#dd503b", linewidth=1.5))
    else:
        x0, x1, y0, y1 = gate["bounds"]
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor="#dd503b", linewidth=1.5))
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
        draw_population(ax, prepared, gate, masks[gate["parent"]])
        draw_gate(ax, gate)
        ax.set_title(
            f"{gate.get('label', gate['name'])}\n{masks[gate['name']].sum():,} / {masks[gate['parent']].sum():,} — {'reviewed' if gate.get('reviewed') else 'DRAFT'}"
        )
        ax.set_xlabel(f"{gate['channels'][0]} ({recipe['transforms'][gate['channels'][0]]['kind']})")
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
    ax.hist(time[finite], bins=60, color="#397988")
    ax.set(xlabel="Time (FCS-scaled units)", ylabel="Events / bin", title="Acquisition rate")
    ax = fig.add_subplot(122)
    if "FSC-A" in prepared.sample.pnn_labels:
        signal = raw[:, prepared.sample.pnn_labels.index("FSC-A")]
        ax.hexbin(time[finite], signal[finite], gridsize=65, mincnt=1, bins="log", cmap="viridis")
    ax.set(xlabel="Time (FCS-scaled units)", ylabel="FSC-A", title="Scatter stability — descriptive only")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
