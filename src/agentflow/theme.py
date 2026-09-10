"""Deliverome / Accessible Surfaceome typography and tokens, shared by desktop and plots."""

from pathlib import Path

ASSETS = Path(__file__).parent / "assets" / "fonts"
BERRY = "#6f0835"
CORAL = "#e2655e"
INK = "#141414"
MUTED = "#5a5f64"
BG = "#fefefc"
LINE = "#e7e5e5"
SOFT = "#f4ebef"


def setup_plots():
    import matplotlib as mpl
    from matplotlib import font_manager

    for path in ASSETS.glob("*.ttf"):
        if str(path) not in {f.fname for f in font_manager.fontManager.ttflist}:
            font_manager.fontManager.addfont(path)
    mpl.rcParams.update(
        {
            "font.family": "Manrope",
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.edgecolor": LINE,
            "axes.labelcolor": MUTED,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "text.color": INK,
            "figure.facecolor": BG,
        }
    )


def desktop_style():
    return f"""
    QWidget {{ font-family: "Manrope"; font-size: 13px; color: {INK}; }}
    QMainWindow, QDialog, QWidget#root {{ background: {BG}; }}
    QLabel {{ background: transparent; }}
    QLabel#brand {{ font-family: "Playfair Display"; font-size: 32px; color: {BERRY}; }}
    QLabel#title {{ font-family: "Playfair Display"; font-size: 30px; }}
    QLabel#muted {{ color: {MUTED}; }}
    QLabel#eyebrow {{ color: {BERRY}; font-size: 11px; font-weight: 600; }}
    QLabel#metric {{ font-family: "Playfair Display"; font-size: 30px; color: {BERRY}; }}
    QLabel#badge {{ background: {SOFT}; color: {BERRY}; border-radius: 6px; padding: 6px 10px; }}
    QFrame#card {{ background: white; border: 1px solid {LINE}; border-radius: 12px; }}
    QListWidget {{ background: transparent; border: none; outline: none; }}
    QListWidget::item {{ padding: 14px 12px; margin: 3px 0; border-radius: 8px; }}
    QListWidget::item:selected {{ color: {BERRY}; background: {SOFT}; }}
    QListWidget::item:hover {{ background: #faf6f8; }}
    QPushButton {{ background: white; border: 1px solid {LINE}; border-radius: 7px;
                    padding: 9px 14px; font-weight: 500; }}
    QPushButton:hover {{ border-color: {BERRY}; background: {SOFT}; }}
    QPushButton:pressed, QPushButton:checked {{ background: {SOFT}; color: {BERRY}; }}
    QPushButton#primary {{ background: {BERRY}; color: white; border-color: {BERRY}; }}
    QPushButton#primary:hover {{ background: #8b174a; }}
    QPushButton:disabled {{ color: #a6a3a4; background: #f6f5f5; border-color: {LINE}; }}
    QPushButton#primary:disabled {{ color: #a6a3a4; background: #f6f5f5; border-color: {LINE}; }}
    QLineEdit, QComboBox {{ background: white; border: 1px solid {LINE}; border-radius: 6px;
                           padding: 8px; min-width: 80px; }}
    QLineEdit:focus, QComboBox:focus {{ border-color: {BERRY}; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: #d9cbd1; border-radius: 4px; min-height: 24px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QTableWidget {{ background: white; gridline-color: {LINE}; border: 1px solid {LINE};
                     selection-background-color: {SOFT}; selection-color: {BERRY}; }}
    QHeaderView::section {{ background: {SOFT}; border: none; padding: 7px; color: {BERRY}; }}
    QToolBar {{ background: {BG}; border: none; }}
    QToolTip {{ background: white; border: 1px solid {LINE}; padding: 6px; }}
    """
