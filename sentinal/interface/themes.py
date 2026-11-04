"""SENTINAL's restrained graphite and blue visual theme."""

STYLESHEET = """
QWidget { background: #0b1018; color: #e5ecf5; font-family: '.AppleSystemUIFont', 'Helvetica Neue', sans-serif; font-size: 13px; }
QMainWindow { background: #0b1018; }
QFrame#header { background: #0b1018; border-bottom: 1px solid #202b3a; }
QFrame#sidebar { background: #101722; border: 1px solid #202c3d; border-radius: 12px; }
QWidget#sidebarContents { background: #101722; }
QFrame#statCard { background: #111a27; border: 1px solid #243044; border-radius: 10px; }
QLabel { background: transparent; }
QLabel#brand { font-size: 27px; font-weight: 800; }
QLabel#edition { color: #7790ad; font-size: 11px; }
QLabel#sectionTitle { font-size: 10px; font-weight: 700; color: #89a0bb; }
QLabel#muted { color: #8194ad; font-size: 11px; }
QLabel#sourceName { color: #d7e4f5; font-size: 13px; font-weight: 600; }
QLabel#metricValue { font-size: 27px; font-weight: 700; color: #edf5ff; }
QLabel#metricTitle { color: #93a9c3; font-size: 10px; }
QLabel#statusChip { color: #7faddb; border: 1px solid #294260; border-radius: 15px; padding: 7px 14px; background: #111e30; font-size: 11px; font-weight: 600; }
QLabel#banner { background: #331c25; border: 1px solid #694050; color: #f5bbc2; border-radius: 8px; padding: 12px; }
QPushButton { background: #1b283a; border: 1px solid #30435e; padding: 9px 13px; border-radius: 7px; font-weight: 600; }
QPushButton:hover { background: #253953; border-color: #4f7fb1; }
QPushButton:pressed { background: #142033; }
QPushButton:disabled { color: #53657c; background: #141d2a; border-color: #233044; }
QPushButton#primary { background: #2878df; border-color: #3c8af0; color: white; padding: 11px; }
QPushButton#primary:hover { background: #3286ed; }
QPushButton#primary:disabled { color: #7b97b5; background: #1b3b60; border-color: #28527f; }
QComboBox { background: #0c1420; border: 1px solid #2b3c53; border-radius: 6px; padding: 8px; min-height: 18px; }
QComboBox::drop-down { border: 0px; width: 22px; }
QComboBox QAbstractItemView { background: #142033; selection-background-color: #26538a; padding: 4px; }
QCheckBox { spacing: 9px; padding-top: 3px; padding-bottom: 3px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid #435773; background: #0b1320; }
QCheckBox::indicator:checked { background: #2b82e9; border-color: #6db4ff; image: none; }
QCheckBox:disabled { color: #596a80; }
QSlider::groove:horizontal { height: 5px; background: #2a384b; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #2e88ee; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; margin: -5px 0; border-radius: 7px; background: #a3d6ff; }
QToolTip { background: #1a2c44; color: #e8f3ff; border: 1px solid #3e5c7f; padding: 5px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: #111a27; width: 7px; }
QScrollBar::handle:vertical { background: #344863; border-radius: 3px; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""

STYLESHEET += """
QLineEdit { background: #0c1420; border: 1px solid #2b3c53; border-radius: 6px; padding: 8px; color: #e5ecf5; min-width: 0px; }
QLineEdit:focus { border-color: #438ce8; }
QLineEdit:disabled { color: #60758f; background: #111a27; }
QProgressBar { border: 1px solid #2b3c53; border-radius: 5px; background: #0c1420; text-align: center; min-height: 20px; }
QProgressBar::chunk { background: #2878df; border-radius: 4px; }
"""
