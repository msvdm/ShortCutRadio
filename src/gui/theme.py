"""The skin: two token palettes and the stylesheet built from them.

ShortCutRadio is fully skinned rather than left to the platform style, because the
window sits next to games and should look like one thing on every machine.
Two ways in:

* `stylesheet()` -- one QSS string set on the QApplication, so the window, the
  dialogs, the message boxes and the menus are all covered from one place.
* `tokens()` -- the same colors for the parts that are painted by hand (the
  source rows, the hero art, the level meters, the pill switches). A stylesheet
  cannot reach inside a `paintEvent`.

The overlay card is deliberately not themed: it renders over games, so it stays
dark and takes its colors from the user's overlay settings.
"""

from PySide6.QtGui import QGuiApplication

DARK = {
    "window": "#16181c",
    "hero_from": "#22262d",
    "hero_to": "#16181c",
    "tabbar": "#14161a",
    "raised": "#1b1e23",
    "active_row": "#22262d",
    "sel_row": "#1f232a",
    "hover_row": "#1b1e23",
    "control": "#20242a",
    "keycap": "#272c33",
    "hairline": "#262a31",
    "border": "#333941",
    "strong": "#3a4049",
    "text": "#f1f3f6",
    "text2": "#e2e5ea",
    "muted": "#9aa1ab",
    "muted_small": "#8b929c",
    "disabled": "#787f89",
    "accent": "#ff6a2b",
    "accent_pressed": "#d9531a",
    "accent_small": "#ff6a2b",      # small text: already readable on dark
    "on_accent": "#16181c",
    "on_accent_pressed": "#0f1114",
    "slider_track": "#2f343c",
    "slider_fill": "#cfd5dd",
    "slider_handle": "#f1f3f6",
    "slider_handle_border": "#f1f3f6",
    "menu_bg": "#1b1e23",
    "menu_border": "#2c3139",
    "menu_hover": "#23272e",
    "menu_sep": "#2a2e35",
    "art_a": "#242931",
    "art_b": "#2b313a",
}

LIGHT = {
    "window": "#ffffff",
    "hero_from": "#f7f5f2",
    "hero_to": "#ffffff",
    "tabbar": "#fbfaf8",
    "raised": "#f7f5f2",
    "active_row": "#f7f5f2",
    "sel_row": "#f1eee9",
    "hover_row": "#faf8f5",
    "control": "#f7f5f2",
    "keycap": "#f3f1ed",
    "hairline": "#eeece8",
    "border": "#dedbd6",
    "strong": "#cfcac3",
    "text": "#17181a",
    "text2": "#17181a",
    "muted": "#6b645d",
    "muted_small": "#5f5952",
    "disabled": "#a39c94",
    "accent": "#e8541c",
    "accent_pressed": "#c2410c",
    "accent_small": "#b23c10",      # small orange text needs this to stay 4.5:1
    "on_accent": "#ffffff",
    "on_accent_pressed": "#ffffff",
    "slider_track": "#e6e2dc",
    "slider_fill": "#55504a",
    "slider_handle": "#ffffff",
    "slider_handle_border": "#cfcac3",
    "menu_bg": "#ffffff",
    "menu_border": "#e3e1dd",
    "menu_hover": "#f7f5f2",
    "menu_sep": "#eeece8",
    "art_a": "#f0ede8",
    "art_b": "#e7e3dd",
}

_current = DARK


def resolve(name):
    """"auto" -> what the desktop is set to, falling back to dark."""
    if name in ("dark", "light"):
        return name
    hints = QGuiApplication.styleHints()
    try:
        scheme = hints.colorScheme() if hints else None
    except AttributeError:                       # Qt < 6.5
        return "dark"
    return "light" if scheme is not None and scheme.name == "Light" else "dark"


def set_current(resolved):
    global _current
    _current = LIGHT if resolved == "light" else DARK
    return _current


def tokens():
    return _current


def stylesheet(t=None):
    t = t or _current
    return f"""
/* ---------------------------------------------------------------- base */
QDialog, QMessageBox, QInputDialog, QColorDialog, #window {{
    background: {t['window']};
}}
QWidget {{ color: {t['text2']}; }}
QLabel {{ background: transparent; color: {t['text2']}; font-size: 13px; }}
QLabel:disabled {{ color: {t['disabled']}; }}
QToolTip {{
    background: {t['raised']}; color: {t['text']};
    border: 1px solid {t['border']}; border-radius: 6px; padding: 4px 7px;
}}

/* ---------------------------------------------------------------- hero */
#hero {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 {t['hero_from']}, stop:1 {t['hero_to']});
}}
#heroCompact {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 {t['hero_from']}, stop:1 {t['hero_to']});
    border-bottom: 1px solid {t['hairline']};
}}
#heroName {{ font-size: 22px; font-weight: 600; color: {t['text']}; }}
#heroTrack {{ font-size: 14px; color: {t['muted']}; }}
#heroStatus {{ font-size: 10px; color: {t['accent_small']}; }}
#heroCompactName {{ font-size: 15px; font-weight: 600; color: {t['text']}; }}
#heroCompactTrack {{ font-size: 12px; color: {t['muted']}; }}
#heroVolume {{ font-size: 12px; color: {t['muted']}; }}

/* ------------------------------------------------------------ tab strip */
#tabStrip {{ background: {t['tabbar']}; border-bottom: 1px solid {t['hairline']}; }}
QPushButton#tab {{
    background: transparent; border: none; border-bottom: 2px solid transparent;
    padding: 12px 0; font-size: 14px; color: {t['muted']}; text-align: center;
}}
QPushButton#tab:hover {{ color: {t['text2']}; }}
QPushButton#tab[active="true"] {{
    color: {t['text']}; font-weight: 600; border-bottom: 2px solid {t['accent']};
}}
#tabHint {{ font-size: 12px; color: {t['muted_small']}; }}
QPushButton#resetBtn {{
    font-size: 12px; color: {t['muted']}; background: transparent;
    border: 1px solid {t['border']}; border-radius: 7px; padding: 5px 10px;
}}
QPushButton#resetBtn:hover {{ color: {t['text']}; border-color: {t['strong']}; }}
QPushButton#resetBtn:pressed {{ background: {t['raised']}; }}

/* ------------------------------------------------------------- sources */
QListWidget#srcList {{ background: transparent; border: none; outline: none; }}
QPushButton#addSource {{
    font-size: 13px; font-weight: 600; color: {t['text2']};
    background: {t['control']}; border: 1px solid {t['border']};
    border-radius: 9px; padding: 11px;
}}
QPushButton#addSource:hover {{
    background: {t['accent']}; color: {t['on_accent']}; border-color: {t['accent']};
}}
QPushButton#addSource:pressed {{
    background: {t['accent_pressed']}; color: {t['on_accent_pressed']};
    border-color: {t['accent_pressed']};
}}

/* ----------------------------------------------------------- shortcuts */
#shortcutRow {{ background: {t['raised']}; border: 1px solid transparent; border-radius: 9px; }}
#shortcutRow[capturing="true"] {{ background: {t['keycap']}; border: 1px solid {t['accent']}; }}
#shortcutLabel {{ font-size: 13px; color: {t['text2']}; }}
QPushButton#keyCap {{
    font-size: 12px; color: {t['text']}; background: {t['keycap']};
    border: 1px solid {t['strong']}; border-bottom-width: 2px;
    border-radius: 6px; padding: 4px 8px;
}}
QPushButton#keyCap:hover {{ border-color: {t['accent']}; }}
QPushButton#keyCap[capturing="true"] {{
    color: {t['accent_small']}; background: transparent; border: none; padding: 5px 8px;
}}
#helpText {{ font-size: 12px; color: {t['muted']}; }}
#warnText {{ font-size: 12px; color: {t['accent_small']}; }}

/* ------------------------------------------------------- overlay tab */
#hair {{ background: {t['hairline']}; border: none; }}
#fieldLabel {{ font-size: 13px; color: {t['muted']}; }}
#footerNote {{ font-size: 12px; color: {t['muted']}; }}
#toggleLabel {{ font-size: 13px; color: {t['text2']}; }}
#showOverlayBox {{
    background: {t['raised']}; border: 1px solid {t['border']}; border-radius: 9px;
}}
#showOverlayLabel {{ font-size: 13px; font-weight: 600; color: {t['text2']}; }}
QPushButton#colorBtn {{ border: 1px solid {t['strong']}; border-radius: 7px; }}

/* ---------------------------------------------------------------- fields */
QLineEdit, QSpinBox, QComboBox, QFontComboBox, QAbstractSpinBox {{
    background: {t['raised']}; color: {t['text']};
    border: 1px solid {t['border']}; border-radius: 7px;
    padding: 6px 10px; font-size: 13px;
    selection-background-color: {t['accent']}; selection-color: {t['on_accent']};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QFontComboBox:focus {{
    border: 1px solid {t['accent']};
}}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{ color: {t['disabled']}; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox::down-arrow {{ image: none; width: 0; height: 0; }}
QComboBox QAbstractItemView {{
    background: {t['raised']}; color: {t['text']};
    border: 1px solid {t['border']}; border-radius: 7px; padding: 4px;
    selection-background-color: {t['active_row']}; selection-color: {t['text']};
    outline: none;
}}

/* --------------------------------------------------------------- sliders */
QSlider::groove:horizontal {{
    height: 4px; background: {t['slider_track']}; border-radius: 2px;
}}
QSlider::sub-page:horizontal {{ background: {t['slider_fill']}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    width: 14px; height: 14px; margin: -5px 0;
    border-radius: 7px; background: {t['slider_handle']};
    border: 1px solid {t['slider_handle_border']};
}}

/* --------------------------------------------------------- plain buttons */
QPushButton {{
    background: {t['control']}; color: {t['text2']};
    border: 1px solid {t['border']}; border-radius: 7px;
    padding: 6px 12px; font-size: 13px;
}}
QPushButton:hover {{ border-color: {t['strong']}; }}
QPushButton:pressed {{ background: {t['raised']}; }}
QPushButton:disabled {{ color: {t['disabled']}; }}
QPushButton:focus {{ border: 1px solid {t['accent']}; }}

/* ----------------------------------------------------------------- menus */
QMenu {{
    background: {t['menu_bg']}; border: 1px solid {t['menu_border']};
    border-radius: 10px; padding: 6px;
}}
QMenu::item {{
    background: transparent; color: {t['text2']};
    padding: 7px 14px 7px 26px; border-radius: 7px; font-size: 13px;
}}
QMenu::item:selected {{ background: {t['menu_hover']}; }}
QMenu::item:disabled {{ color: {t['disabled']}; }}
QMenu::separator {{ height: 1px; background: {t['menu_sep']}; margin: 5px 2px; }}

/* ------------------------------------------------------------ tray menu */
#trayHeader {{ background: {t['menu_hover']}; border-radius: 7px; }}
#trayName {{ font-size: 13px; font-weight: 600; color: {t['text']}; }}
#trayTrack {{ font-size: 11px; color: {t['muted']}; }}

/* ------------------------------------------------- Add Stream dialog */
QTreeWidget, QTreeView {{
    background: {t['raised']}; color: {t['text2']};
    border: 1px solid {t['border']}; border-radius: 9px;
    alternate-background-color: {t['raised']}; outline: none;
}}
QTreeView::item {{ padding: 4px 2px; }}
QTreeView::item:selected {{ background: {t['active_row']}; color: {t['text']}; }}
QHeaderView::section {{
    background: {t['control']}; color: {t['muted']};
    border: none; border-bottom: 1px solid {t['border']};
    padding: 6px 8px; font-size: 12px;
}}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {t['border']}; border-radius: 5px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {t['strong']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: {t['border']}; border-radius: 5px; min-width: 24px;
}}
"""
