"""Deliverome / Accessible Surfaceome typography and tokens, shared by desktop and plots."""

from pathlib import Path

ASSETS = Path(__file__).parent / "assets" / "fonts"
BERRY = "#922038"
CORAL = "#e2655e"
INK = "#1f1718"
MUTED = "#6f5d5a"
BG = "#ffffff"
LINE = "#e7e7ea"
SOFT = "#fcf7f8"


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
    icons = ASSETS.parent / "icons"
    return f"""
    QWidget {{ font-family: "Manrope"; font-size: 12px; color: {INK}; }}
    QMainWindow, QDialog, QWidget#root, QWidget#analysis_panel {{ background: {BG}; }}
    QLabel {{ background: transparent; }}
    QLabel#brand {{ font-family: "Playfair Display"; font-size: 28px; color: {BERRY}; }}
    QLabel#title {{ font-family: "Playfair Display"; font-size: 27px; }}
    QLabel#muted {{ color: {MUTED}; }}
    QLabel#eyebrow {{ color: {BERRY}; font-size: 11px; font-weight: 600; }}
    QLabel#metric {{ font-family: "Playfair Display"; font-size: 27px; color: {BERRY}; }}
    QLabel#badge {{ background: {SOFT}; color: {BERRY}; border-radius: 6px; padding: 6px 10px; }}
    QFrame#card {{ background: white; border: 1px solid {LINE}; border-radius: 12px; }}
    QTreeWidget {{ background: transparent; border: none; outline: none; }}
    QTreeWidget::item {{ padding: 8px 2px; border-radius: 6px; }}
    QTreeWidget::item:selected {{ color: {BERRY}; background: {SOFT}; }}
    QTreeWidget::item:hover {{ background: #faf6f8; }}
    QListWidget {{ background: transparent; border: none; outline: none; }}
    QListWidget::item {{ padding: 14px 12px; margin: 3px 0; border-radius: 8px; }}
    QListWidget::item:selected {{ color: {BERRY}; background: {SOFT}; }}
    QListWidget::item:hover {{ background: #faf6f8; }}
    QPushButton {{ background: white; border: 1px solid {LINE}; border-radius: 7px;
                    padding: 7px 11px; font-weight: 500; }}
    QPushButton:hover {{ border-color: {BERRY}; background: {SOFT}; }}
    QPushButton:pressed, QPushButton:checked {{ background: {SOFT}; color: {BERRY}; }}
    QPushButton#primary {{ background: {BERRY}; color: white; border-color: {BERRY}; }}
    QPushButton#primary:hover {{ background: #8b174a; }}
    QPushButton:disabled {{ color: #a6a3a4; background: #f6f5f5; border-color: {LINE}; }}
    QPushButton#primary:disabled {{ color: #a6a3a4; background: #f6f5f5; border-color: {LINE}; }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background: white; border: 1px solid {LINE}; border-radius: 6px;
                           padding: 7px; min-width: 52px; }}
    QLineEdit:focus, QComboBox:focus {{ border-color: {BERRY}; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: #d9cbd1; border-radius: 4px; min-height: 24px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QTableWidget {{ background: white; gridline-color: {LINE}; border: 1px solid {LINE};
                     selection-background-color: {SOFT}; selection-color: {BERRY}; }}
    QHeaderView::section {{ background: {SOFT}; border: none; padding: 7px; color: {BERRY}; }}
    QToolBar {{ background: {BG}; border: none; }}
    QWidget#sidebar {{ background: #fafafb; border-radius: 12px; }}
    QWidget#experiment_bar {{ background: white; border: 1px solid {LINE}; border-radius: 10px; }}
    QWidget#gallery {{ background: #ffffff; border-radius: 12px; }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QComboBox::drop-down {{ border: none; width: 23px; }}
    QComboBox::down-arrow {{ image: url("{icons / "chevron.svg"}"); width: 12px; height: 12px; }}
    QComboBox {{ padding-right: 25px; }}
    QComboBox QAbstractItemView {{ background: white; selection-background-color: {SOFT}; selection-color: {BERRY}; padding: 6px; outline: none; }}
    QMenu {{ background: white; border: 1px solid {LINE}; padding: 6px; }}
    QMenu::item {{ padding: 8px 20px; border-radius: 5px; }}
    QMenu::item:selected {{ background: {SOFT}; color: {BERRY}; }}
    QMenu::separator {{ height: 1px; background: {LINE}; margin: 5px; }}
    QCheckBox {{ spacing: 7px; padding: 3px 0; }}
    QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid #c5b7b1; border-radius: 4px; background: white; }}
    QCheckBox::indicator:checked {{ background: {BERRY}; border: 2px solid {BERRY}; image: url("{icons / "check.svg"}"); }}
    QSplitter::handle {{ background: transparent; width: 8px; }}
    QSplitter::handle:hover {{ background: {LINE}; }}
    QScrollBar:horizontal {{ background: transparent; height: 8px; }}
    QScrollBar::handle:horizontal {{ background: #d9cbd1; border-radius: 4px; min-width: 24px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
    QToolTip {{ background: white; border: 1px solid {LINE}; padding: 6px; }}
    """
