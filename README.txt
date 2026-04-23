City of Heroes PopMenu Editor
==============================

FILES:
  popmenuHero.py  - Main GUI application
  mnu_parser.py      - Parser/writer library for .mnu files


REQUIREMENTS:
  Python 3.9+
  PyQt6

INSTALL:
  pip install PyQt6

RUN:
  python popmenu_editor.py
  python popmenu_editor.py SampleMenu.mnu    (open a file directly)

FEATURES:
  - Open/Save .mnu files
  - Tree view showing full menu hierarchy
  - Color-coded elements (Menu=blue, Option=green, LockedOption=red, etc.)
  - Click any element to edit its properties in the right panel
  - Drag & drop to reorder — only Menu items accept children
  - Add elements via buttons: Menu, Option, LockedOption, Title, Divider, Comment
  - Delete selected elements
  - Unsaved-changes tracking (*) in title bar
  - Full round-trip fidelity including <& &> quote escaping

ELEMENT TYPES:
  📁 Menu         - Named submenu, can contain children
  ▶  Option       - Display name + command string
  🔒 LockedOption - Conditional option with badge/power requirements
  📝 Title        - Section header text
  ── Divider      - Visual separator line
  💬 Comment      - // comment line
