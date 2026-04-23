"""
City of Heroes PopMenu Hero
A graphical editor for .mnu files with drag-and-drop tree view and property panel.
"""

import sys
import os
import configparser
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTreeWidget, QTreeWidgetItem,
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QTextEdit, QLabel, QSplitter, QPushButton, QComboBox,
    QFileDialog, QMessageBox, QToolBar, QFrame, QScrollArea,
    QSizePolicy, QGroupBox, QCheckBox, QStyledItemDelegate, QStyle
)
from PyQt6.QtCore import Qt, QMimeData, QByteArray, QRectF, QSize
from PyQt6.QtGui import QAction, QFont, QColor, QIcon, QDrag, QTextDocument

from mnu_parser import (
    MnuFile, MnuNode, Menu, Option, LockedOption,
    Title, Divider, Comment, MnuParser, MnuWriter,
    parse_file, write_file
)

# --- Icons (text-based fallbacks) ---
ICON_MAP = {
    'Menu':         '📁',
    'Option':       '▶',
    'LockedOption': '🔒',
    'Title':        '📝',
    'Divider':      '─',
    'Comment':      '💬',
}

NODE_COLORS = {
    'Menu':         QColor('#1e3a5f'),
    'Option':       QColor('#1a3a1a'),
    'LockedOption': QColor('#3a1a1a'),
    'Title':        QColor('#2a2a00'),
    'Divider':      QColor('#2a2a2a'),
    'Comment':      QColor('#1a1a2e'),
}

BG_COLORS = {
    'Menu':         QColor('#dceeff'),
    'Option':       QColor('#dcffdc'),
    'LockedOption': QColor('#ffdcdc'),
    'Title':        QColor('#ffffd0'),
    'Divider':      QColor('#ebebeb'),
    'Comment':      QColor('#e8e8f0'),
}


def node_type_name(node: MnuNode) -> str:
    return type(node).__name__


def node_label(node: MnuNode) -> str:
    if isinstance(node, Menu):
        return f"📁 {node.name}"
    elif isinstance(node, Option):
        return f"▶ {node.display_name}"
    elif isinstance(node, LockedOption):
        return f"🔒 {node.display_name or '(no name)'}"
    elif isinstance(node, Title):
        return f"📝 {node.text}"
    elif isinstance(node, Divider):
        return "──────────────────────────"
    elif isinstance(node, Comment):
        return f"💬 {node.text[:100]}{'…' if len(node.text) > 100 else ''}"
    return "?"


def hotkey_to_html(text: str) -> str:
    """
    Convert &X hotkey markers to <b>X</b> for display.
    & followed by a space is treated as a literal ampersand.
    """
    result = []
    i = 0
    while i < len(text):
        if text[i] == '&' and i + 1 < len(text) and text[i + 1] != ' ':
            # Hotkey: bold the next character, suppress the &
            c = text[i + 1]
            if c == '<':
                result.append('<b>&lt;</b>')
            elif c == '>':
                result.append('<b>&gt;</b>')
            else:
                result.append(f'<b>{c}</b>')
            i += 2
        else:
            c = text[i]
            if c == '<':
                result.append('&lt;')
            elif c == '>':
                result.append('&gt;')
            elif c == '&':
                result.append('&amp;')
            else:
                result.append(c)
            i += 1
    return ''.join(result)


class HotkeyDelegate(QStyledItemDelegate):
    """Renders tree item text with &X hotkeys shown as a bolded letter."""

    def paint(self, painter, option, index):
        self.initStyleOption(option, index)

        painter.save()

        # Draw standard background/selection without text
        style = option.widget.style() if option.widget else QApplication.style()
        text = option.text
        option.text = ""
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget)

        # Build the HTML document with zero margins so it fits exactly
        doc = QTextDocument()
        doc.setDefaultFont(option.font)
        doc.setDocumentMargin(0)
        doc.setHtml(hotkey_to_html(text))

        # Get the rect Qt allocates for the text
        text_rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText, option, option.widget
        )

        # Vertically centre within the row
        doc_height = doc.size().height()
        top_offset = max(0, (text_rect.height() - doc_height) / 2)

        painter.translate(text_rect.left(), text_rect.top() + top_offset)
        doc.drawContents(painter, QRectF(0, 0, text_rect.width(), doc_height + 2))

        painter.restore()

    def sizeHint(self, option, index):
        # Ensure enough vertical room for the font
        sh = super().sizeHint(option, index)
        fm_height = option.fontMetrics.height()
        if sh.height() < fm_height + 8:
            sh.setHeight(fm_height + 8)
        return sh


class PopMenuTree(QTreeWidget):
    """Tree widget with drag-and-drop that enforces menu-only nesting rules."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabel("Menu Structure")
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
        self.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.setAnimated(True)
        self.setIndentation(20)
        self.setFont(QFont("Segoe UI", 10))
        self.setMinimumWidth(300)
        self.setItemDelegate(HotkeyDelegate(self))
        self.setStyleSheet("""
            QTreeWidget {
                border: 1px solid #ccc;
                border-radius: 4px;
                background: #fafafa;
            }
            QTreeWidget::item {
                padding: 4px 2px;
            }
            QTreeWidget::item:selected {
                background: #0078d4;
                color: white;
            }
            QTreeWidget::item:hover {
                background: #e8f4fd;
            }
        """)

    def dropEvent(self, event):
        """Override to enforce: only Menu items can have children."""
        target_item = self.itemAt(event.position().toPoint())
        drop_indicator = self.dropIndicatorPosition()

        # Determine destination parent
        if drop_indicator == QTreeWidget.DropIndicatorPosition.OnItem:
            # Dropping INTO an item - that item must be a Menu
            if target_item:
                node = target_item.data(0, Qt.ItemDataRole.UserRole)
                if not isinstance(node, Menu):
                    event.ignore()
                    return
        elif drop_indicator in (
            QTreeWidget.DropIndicatorPosition.AboveItem,
            QTreeWidget.DropIndicatorPosition.BelowItem
        ):
            # Dropping beside an item - parent must be Menu or root
            if target_item:
                parent = target_item.parent()
                if parent:
                    node = parent.data(0, Qt.ItemDataRole.UserRole)
                    if not isinstance(node, Menu):
                        event.ignore()
                        return

        super().dropEvent(event)
        # Only expand the item that was dropped onto, not the whole tree
        target_item = self.itemAt(event.position().toPoint())
        if target_item:
            target_item.setExpanded(True)


class PropertyPanel(QWidget):
    """Right-side panel showing editable properties for the selected node."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_item = None
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.type_label = QLabel("No item selected")
        self.type_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.type_label.setStyleSheet("color: #333; padding: 4px;")
        layout.addWidget(self.type_label)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #ccc;")
        layout.addWidget(sep)

        # Scroll area for properties
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none;")
        layout.addWidget(scroll)

        self.form_container = QWidget()
        self.form_layout = QFormLayout(self.form_container)
        self.form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.form_layout.setSpacing(8)
        scroll.setWidget(self.form_container)

        # Pre-create all possible fields
        self._fields = {}
        self._build_all_fields()

        layout.addStretch()
        self.setMinimumWidth(280)
        self.setMaximumWidth(420)

        self.setStyleSheet("""
            QWidget { background: #f5f5f5; }
            QLineEdit, QTextEdit {
                background: white;
                border: 1px solid #ccc;
                border-radius: 3px;
                padding: 3px;
            }
            QLabel { color: #555; }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #ccc;
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 8px;
            }
        """)

    def _create_icon_field(self):
        """Create a widget with line edit and help button for icon field."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        line_edit = QLineEdit()
        line_edit.textChanged.connect(self._on_field_changed)
        layout.addWidget(line_edit)

        help_btn = QPushButton("?")
        help_btn.setFixedSize(24, 24)
        help_btn.setToolTip("Open icon reference")
        help_btn.clicked.connect(self._open_icon_help)
        layout.addWidget(help_btn)

        # Store reference to line edit for later access
        widget.line_edit = line_edit
        return widget

    def _open_icon_help(self):
        """Open the icon help webpage."""
        import webbrowser
        webbrowser.open("https://homecoming.wiki/wiki/Macro_image_(Slash_Command)")

    def _create_badge_field(self):
        """Create a widget with line edit and help button for badge field."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        line_edit = QLineEdit()
        line_edit.setPlaceholderText("Space-separated badge list")
        line_edit.textChanged.connect(self._on_field_changed)
        layout.addWidget(line_edit)

        help_btn = QPushButton("?")
        help_btn.setFixedSize(24, 24)
        help_btn.setToolTip("Open badge reference")
        help_btn.clicked.connect(self._open_badge_help)
        layout.addWidget(help_btn)

        # Store reference to line edit for later access
        widget.line_edit = line_edit
        return widget

    def _create_power_field(self, type_):
        """Create a widget with line edit and help button for power fields."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        line_edit = QLineEdit()
        line_edit.setPlaceholderText("Power name")
        line_edit.textChanged.connect(self._on_field_changed)
        layout.addWidget(line_edit)

        help_btn = QPushButton("?")
        help_btn.setFixedSize(24, 24)
        help_btn.setToolTip("Open power reference")
        help_btn.clicked.connect(lambda: self._open_power_help())
        layout.addWidget(help_btn)

        # Store reference to line edit for later access
        widget.line_edit = line_edit
        return widget

    def _open_badge_help(self):
        """Open the badge help webpage."""
        import webbrowser
        webbrowser.open("https://homecoming.wiki/wiki/Badges")

    def _open_power_help(self):
        """Open the power help webpage."""
        import webbrowser
        webbrowser.open("https://cod.uberguy.net")

    def _build_all_fields(self):
        """Build field widgets for all node types."""
        fl = self.form_layout

        # Common
        self._fields['name'] = QLineEdit()
        self._fields['name'].setPlaceholderText("Menu name")
        self._fields['name'].textChanged.connect(self._on_field_changed)

        self._fields['display_name'] = QLineEdit()
        self._fields['display_name'].setPlaceholderText("Display name")
        self._fields['display_name'].textChanged.connect(self._on_field_changed)

        self._fields['command'] = QTextEdit()
        self._fields['command'].setPlaceholderText("Command string (use $$ to chain)")
        self._fields['command'].setMaximumHeight(160)
        self._fields['command'].textChanged.connect(self._on_field_changed)

        self._fields['text'] = QLineEdit()
        self._fields['text'].setPlaceholderText("Title text")
        self._fields['text'].textChanged.connect(self._on_field_changed)

        self._fields['comment_text'] = QTextEdit()
        self._fields['comment_text'].setPlaceholderText("Comment text")
        self._fields['comment_text'].setMaximumHeight(80)
        self._fields['comment_text'].textChanged.connect(self._on_field_changed)

        # LockedOption extras
        self._fields['icon'] = self._create_icon_field()
        # Note: textChanged connect will be on the line edit inside

        self._fields['badge'] = self._create_badge_field()
        # Note: textChanged connect will be on the line edit inside

        self._fields['power_ready'] = self._create_power_field("ready")
        # Note: textChanged connect will be on the line edit inside

        self._fields['power_owned'] = self._create_power_field("owned")
        # Note: textChanged connect will be on the line edit inside

        # Deprecated (read-only display)
        self._fields['authbit'] = QLineEdit()
        self._fields['authbit'].setPlaceholderText("(deprecated)")
        self._fields['authbit'].textChanged.connect(self._on_field_changed)

        self._fields['reward_token'] = QLineEdit()
        self._fields['reward_token'].setPlaceholderText("(deprecated)")
        self._fields['reward_token'].textChanged.connect(self._on_field_changed)

        self._fields['store_product'] = QLineEdit()
        self._fields['store_product'].setPlaceholderText("(deprecated)")
        self._fields['store_product'].textChanged.connect(self._on_field_changed)

        # Add all rows (hidden by default)
        fl.addRow("Name:", self._fields['name'])
        fl.addRow("Display Name:", self._fields['display_name'])
        fl.addRow("Command:", self._fields['command'])
        fl.addRow("Title Text:", self._fields['text'])
        fl.addRow("Comment:", self._fields['comment_text'])
        fl.addRow("Icon:", self._fields['icon'])
        fl.addRow("Badge(s):", self._fields['badge'])
        fl.addRow("Power Ready:", self._fields['power_ready'])
        fl.addRow("Power Owned:", self._fields['power_owned'])
        fl.addRow("Authbit:", self._fields['authbit'])
        fl.addRow("Reward Token:", self._fields['reward_token'])
        fl.addRow("Store Product:", self._fields['store_product'])

        self._hide_all()

    def _hide_all(self):
        for row in range(self.form_layout.rowCount()):
            label = self.form_layout.itemAt(row, QFormLayout.ItemRole.LabelRole)
            field = self.form_layout.itemAt(row, QFormLayout.ItemRole.FieldRole)
            if label:
                label.widget().setVisible(False)
            if field:
                field.widget().setVisible(False)

    def _show_fields(self, *keys):
        self._hide_all()
        fl = self.form_layout
        for key in keys:
            widget = self._fields.get(key)
            if widget:
                for row in range(fl.rowCount()):
                    field_item = fl.itemAt(row, QFormLayout.ItemRole.FieldRole)
                    if field_item and field_item.widget() is widget:
                        label_item = fl.itemAt(row, QFormLayout.ItemRole.LabelRole)
                        if label_item:
                            label_item.widget().setVisible(True)
                        field_item.widget().setVisible(True)
                        break

    def load_node(self, item: QTreeWidgetItem):
        self._updating = True
        self.current_item = item
        node = item.data(0, Qt.ItemDataRole.UserRole)
        tn = node_type_name(node)

        self.type_label.setText(f"  {ICON_MAP.get(tn, '')}  {tn}")
        self.type_label.setStyleSheet(
            f"color: white; background: {NODE_COLORS.get(tn, QColor('#333')).name()}; "
            f"padding: 6px; border-radius: 4px; font-size: 12pt; font-weight: bold;"
        )

        if isinstance(node, Menu):
            self._show_fields('name')
            self._fields['name'].setText(node.name)

        elif isinstance(node, Option):
            self._show_fields('display_name', 'command')
            self._fields['display_name'].setText(node.display_name)
            self._fields['command'].setPlainText(node.command)

        elif isinstance(node, LockedOption):
            fields = ['display_name', 'command', 'icon', 'badge',
                      'power_ready', 'power_owned']
            if node.authbit:
                fields.append('authbit')
            if node.reward_token:
                fields.append('reward_token')
            if node.store_product:
                fields.append('store_product')
            self._show_fields(*fields)
            self._fields['display_name'].setText(node.display_name)
            self._fields['command'].setPlainText(node.command)
            self._fields['icon'].line_edit.setText(node.icon)
            self._fields['badge'].line_edit.setText(node.badge)
            self._fields['power_ready'].line_edit.setText(node.power_ready)
            self._fields['power_owned'].line_edit.setText(node.power_owned)
            self._fields['authbit'].setText(node.authbit)
            self._fields['reward_token'].setText(node.reward_token)
            self._fields['store_product'].setText(node.store_product)

        elif isinstance(node, Title):
            self._show_fields('text')
            self._fields['text'].setText(node.text)

        elif isinstance(node, Divider):
            self._hide_all()
            self.type_label.setText("  ── Divider ──\n  (No properties)")

        elif isinstance(node, Comment):
            self._show_fields('comment_text')
            self._fields['comment_text'].setPlainText(node.text)

        self._updating = False

    def clear(self):
        self._updating = True
        self.current_item = None
        self.type_label.setText("No item selected")
        self.type_label.setStyleSheet("color: #333; padding: 4px;")
        self._hide_all()
        self._updating = False

    def _on_field_changed(self):
        if self._updating or not self.current_item:
            return

        node = self.current_item.data(0, Qt.ItemDataRole.UserRole)

        if isinstance(node, Menu):
            node.name = self._fields['name'].text()
        elif isinstance(node, Option):
            node.display_name = self._fields['display_name'].text()
            node.command = self._fields['command'].toPlainText()
        elif isinstance(node, LockedOption):
            node.display_name = self._fields['display_name'].text()
            node.command = self._fields['command'].toPlainText()
            node.icon = self._fields['icon'].line_edit.text()
            node.badge = self._fields['badge'].line_edit.text()
            node.power_ready = self._fields['power_ready'].line_edit.text()
            node.power_owned = self._fields['power_owned'].line_edit.text()
            node.authbit = self._fields['authbit'].text()
            node.reward_token = self._fields['reward_token'].text()
            node.store_product = self._fields['store_product'].text()
        elif isinstance(node, Title):
            node.text = self._fields['text'].text()
        elif isinstance(node, Comment):
            node.text = self._fields['comment_text'].toPlainText()

        # Update tree label
        self.current_item.setText(0, node_label(node))

        # Notify parent that document changed
        main = self.window()
        if hasattr(main, 'mark_modified'):
            main.mark_modified()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("City of Heroes PopMenu Hero")
        self.setGeometry(100, 100, 1100, 700)
        self.current_file = None
        self.modified = False

        self.config = configparser.ConfigParser()
        self.config_path = self._get_config_path()
        self._load_config()

        game_dir = self.config.get('DEFAULT', 'game_directory', fallback='')
        if game_dir:
            self._check_menus_directory(game_dir)

        self._build_ui()
        self._build_menu_bar()
        self._build_toolbar()

    def _get_config_path(self):
        if getattr(sys, 'frozen', False):
            # Running as compiled exe
            exe_dir = Path(sys.executable).parent
        else:
            # Running as script
            exe_dir = Path(__file__).parent
        return exe_dir / 'config.ini'

    def _load_config(self):
        if self.config_path.exists():
            self.config.read(self.config_path)

    def _save_config(self):
        with open(self.config_path, 'w') as f:
            self.config.write(f)

    def _set_game_directory(self):
        current = self.config.get('DEFAULT', 'game_directory', fallback='')
        path = QFileDialog.getExistingDirectory(self, "Select City of Heroes Game Directory", current)
        if path:
            if 'DEFAULT' not in self.config:
                self.config.add_section('DEFAULT')
            self.config.set('DEFAULT', 'game_directory', path)
            self._save_config()
            self._check_menus_directory(path)

    def _check_menus_directory(self, game_dir):
        menus_dir = Path(game_dir) / 'data' / 'texts' / 'English' / 'menus'
        if menus_dir.exists():
            return  # Already exists
        reply = QMessageBox.question(
            self, "Create Menus Directory",
            f"The menus directory does not exist:\n{menus_dir}\n\nCreate it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                menus_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to create directory: {e}")

    def _get_default_directory(self):
        game_dir = self.config.get('DEFAULT', 'game_directory', fallback='')
        if game_dir:
            menus_dir = Path(game_dir) / 'data' / 'texts' / 'English' / 'menus'
            if menus_dir.exists():
                return str(menus_dir)
        return ""

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # --- Left: Tree + buttons ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.tree = PopMenuTree()
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.model().rowsInserted.connect(self._on_tree_changed)
        self.tree.model().rowsMoved.connect(self._on_tree_changed)
        self.tree.model().rowsRemoved.connect(self._on_tree_changed)
        left_layout.addWidget(self.tree)

        # Add element buttons
        btn_row = QHBoxLayout()
        btn_style = """
            QPushButton {
                font-size: 9pt;
                padding: 3px 8px;
                border-radius: 3px;
                border: 1px solid #aaa;
                background: #f0f0f0;
            }
            QPushButton:hover { background: #d0e8ff; border-color: #0078d4; }
            QPushButton:pressed { background: #b0d0ff; }
        """
        for label, fn in [
            ("+ Menu", self._add_menu),
            ("+ Option", self._add_option),
            ("+ LockedOpt", self._add_locked_option),
            ("+ Title", self._add_title),
            ("+ Divider", self._add_divider),
            ("+ Comment", self._add_comment),
        ]:
            btn = QPushButton(label)
            btn.setStyleSheet(btn_style)
            btn.clicked.connect(fn)
            btn_row.addWidget(btn)

        left_layout.addLayout(btn_row)

        del_btn = QPushButton("🗑 Delete Selected")
        del_btn.setStyleSheet("""
            QPushButton {
                font-size: 9pt; padding: 4px;
                border-radius: 3px; border: 1px solid #c00;
                background: #fff0f0; color: #900;
            }
            QPushButton:hover { background: #fdd; }
        """)
        del_btn.clicked.connect(self._delete_selected)
        left_layout.addWidget(del_btn)

        splitter.addWidget(left_widget)

        # --- Right: Property panel ---
        self.prop_panel = PropertyPanel()
        splitter.addWidget(self.prop_panel)

        splitter.setSizes([680, 380])

    def _build_menu_bar(self):
        mb = self.menuBar()

        file_menu = mb.addMenu("&File")
        file_menu.addAction(self._action("&New", self._new_file, "Ctrl+N"))
        file_menu.addAction(self._action("&Open...", self._open_file, "Ctrl+O"))
        file_menu.addSeparator()
        file_menu.addAction(self._action("&Save", self._save_file, "Ctrl+S"))
        file_menu.addAction(self._action("Save &As...", self._save_file_as, "Ctrl+Shift+S"))
        file_menu.addSeparator()
        file_menu.addAction(self._action("Set &Game Directory...", self._set_game_directory))
        file_menu.addSeparator()
        file_menu.addAction(self._action("E&xit", self.close, "Alt+F4"))

        edit_menu = mb.addMenu("&Edit")
        edit_menu.addAction(self._action("&Delete Selected", self._delete_selected, "Delete"))
        edit_menu.addSeparator()
        edit_menu.addAction(self._action("Expand &All", self.tree.expandAll))
        edit_menu.addAction(self._action("&Collapse All", self.tree.collapseAll))

    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setMovable(False)
        tb.setStyleSheet("""
            QToolBar { background: #f0f0f0; border-bottom: 1px solid #ccc; padding: 2px; }
            QToolButton { padding: 4px 8px; border-radius: 3px; }
            QToolButton:hover { background: #d0e8ff; }
        """)
        tb.addAction(self._action("🆕 New", self._new_file))
        tb.addAction(self._action("📂 Open", self._open_file))
        tb.addAction(self._action("💾 Save", self._save_file))
        tb.addSeparator()
        tb.addAction(self._action("⊞ Expand All", self.tree.expandAll))
        tb.addAction(self._action("⊡ Collapse to Root", self._collapse_to_root))
        tb.addAction(self._action("⊟ Collapse All", self.tree.collapseAll))

    def _collapse_to_root(self):
        """Collapse all items but keep the root menu expanded."""
        self.tree.collapseAll()
        # Find and expand the root menu
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            node = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(node, Menu):
                item.setExpanded(True)
                break

    def _action(self, label, slot, shortcut=None):
        a = QAction(label, self)
        a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(shortcut)
        return a

    # --- Tree Building ---

    def _build_tree_from_mnu(self, mnu: MnuFile):
        # Block model signals so adding items during load doesn't fire mark_modified
        self.tree.model().blockSignals(True)
        self.tree.clear()
        for comment in mnu.root_comments:
            item = self._build_tree_item(comment)
            self.tree.addTopLevelItem(item)
        if mnu.root_menu:
            # If the first child of the root Menu is a Title, hoist it to root level for display
            children = mnu.root_menu.children
            if children and isinstance(children[0], Title):
                title_item = self._build_tree_item(children[0])
                self.tree.addTopLevelItem(title_item)
                # Remove it from the menu's children so it isn't shown twice
                mnu.root_menu.children = children[1:]
            root_item = self._build_tree_item(mnu.root_menu)
            self.tree.addTopLevelItem(root_item)
            self.tree.expandAll()
        self.tree.model().blockSignals(False)

    def _build_tree_item(self, node: MnuNode) -> QTreeWidgetItem:
        item = QTreeWidgetItem([node_label(node)])
        item.setData(0, Qt.ItemDataRole.UserRole, node)

        tn = node_type_name(node)
        bg = BG_COLORS.get(tn, QColor('white'))
        item.setBackground(0, bg)

        if isinstance(node, Menu):
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDropEnabled)
            for child in node.children:
                item.addChild(self._build_tree_item(child))
        else:
            # Non-menu items cannot receive drops
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)

        return item

    # --- MnuFile reconstruction from tree ---

    def _tree_to_mnu(self) -> MnuFile:
        mnu = MnuFile()
        pending_title = None
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            node = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(node, Comment):
                mnu.root_comments.append(node)
            elif isinstance(node, Title):
                # Root-level Title gets absorbed as first child of the Menu on save
                pending_title = node
            elif isinstance(node, Menu):
                menu_node = self._item_to_node(item)
                if pending_title:
                    menu_node.children.insert(0, pending_title)
                    pending_title = None
                mnu.root_menu = menu_node
        return mnu

    def _item_to_node(self, item: QTreeWidgetItem) -> MnuNode:
        node = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(node, Menu):
            node.children = []
            for i in range(item.childCount()):
                node.children.append(self._item_to_node(item.child(i)))
        return node

    # --- Selections ---

    def _on_selection_changed(self):
        items = self.tree.selectedItems()
        if items:
            self.prop_panel.load_node(items[0])
        else:
            self.prop_panel.clear()

    def _on_tree_changed(self, *args):
        self.mark_modified()

    # --- Add element helpers ---

    def _find_root_menu_index(self) -> int:
        """Return the top-level index of the root Menu item, or -1 if not found."""
        for i in range(self.tree.topLevelItemCount()):
            node = self.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
            if isinstance(node, Menu):
                return i
        return -1

    def _selection_is_root_level(self) -> bool:
        """Return True if the selected item (if any) is a direct child of the invisible root."""
        sel = self.tree.selectedItems()
        if not sel:
            return False
        return sel[0].parent() is None

    def _get_insert_target(self):
        """Return (parent_item, insert_index) for adding a node inside a Menu."""
        selected = self.tree.selectedItems()
        if not selected:
            # Nothing selected — append to end of root Menu
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if isinstance(item.data(0, Qt.ItemDataRole.UserRole), Menu):
                    return item, item.childCount()
            return None, 0

        sel = selected[0]
        sel_node = sel.data(0, Qt.ItemDataRole.UserRole)

        # If a Menu is selected and expanded, insert as its first child
        if isinstance(sel_node, Menu) and sel.isExpanded():
            return sel, 0

        # Otherwise insert after the selected item in its parent
        parent = sel.parent()
        if parent is None:
            parent = self.tree.invisibleRootItem()
        idx = parent.indexOfChild(sel)
        return parent, idx + 1

    def _insert_node(self, node: MnuNode):
        # --- Root-level Comment: only go to root if selection is root-level or empty ---
        if isinstance(node, Comment):
            sel = self.tree.selectedItems()
            if sel and sel[0].parent() is None:
                # Selected item is at root — insert after it at root level
                idx = self.tree.indexOfTopLevelItem(sel[0])
                item = self._build_tree_item(node)
                self.tree.insertTopLevelItem(idx + 1, item)
                self.tree.setCurrentItem(item)
                self.mark_modified()
                return
            elif not sel:
                # Nothing selected — insert before the root Menu at root level
                menu_idx = self._find_root_menu_index()
                item = self._build_tree_item(node)
                insert_at = menu_idx if menu_idx >= 0 else self.tree.topLevelItemCount()
                self.tree.insertTopLevelItem(insert_at, item)
                self.tree.setCurrentItem(item)
                self.mark_modified()
                return
            # Otherwise fall through to normal nested insertion below

        # --- Root-level Title: immediately before the root Menu ---
        if isinstance(node, Title) and self._selection_is_root_level():
            menu_idx = self._find_root_menu_index()
            if menu_idx < 0:
                QMessageBox.warning(self, "No Root Menu",
                    "Add a root Menu before adding a root-level Title.")
                return
            for i in range(self.tree.topLevelItemCount()):
                existing = self.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                if isinstance(existing, Title):
                    QMessageBox.warning(self, "Title Already Exists",
                        "There is already a root-level Title immediately before the Menu.\n"
                        "Edit it in the properties panel, or delete it first.")
                    return
            item = self._build_tree_item(node)
            self.tree.insertTopLevelItem(menu_idx, item)
            self.tree.setCurrentItem(item)
            self.mark_modified()
            return

        # --- All other nodes go inside a Menu ---
        parent_item, idx = self._get_insert_target()
        if parent_item is None:
            if isinstance(node, Menu):
                item = self._build_tree_item(node)
                self.tree.addTopLevelItem(item)
                self.tree.setCurrentItem(item)
                self.mark_modified()
            else:
                QMessageBox.warning(self, "No Root Menu",
                    "Please create a Menu element first — it must be the root.")
            return

        parent_node = parent_item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(parent_node, Menu):
            QMessageBox.warning(self, "Invalid Parent",
                "Only Menu elements can contain children.")
            return

        item = self._build_tree_item(node)
        parent_item.insertChild(idx, item)
        parent_item.setExpanded(True)
        self.tree.setCurrentItem(item)
        self.mark_modified()

    def _add_menu(self):
        self._insert_node(Menu(name="New Menu"))

    def _add_option(self):
        self._insert_node(Option(display_name="New Option", command=""))

    def _add_locked_option(self):
        self._insert_node(LockedOption(display_name="New LockedOption", command=""))

    def _add_title(self):
        self._insert_node(Title(text="New Title"))

    def _add_divider(self):
        self._insert_node(Divider())

    def _add_comment(self):
        self._insert_node(Comment(text="New comment"))

    def _delete_selected(self):
        items = self.tree.selectedItems()
        if not items:
            return
        item = items[0]
        node = item.data(0, Qt.ItemDataRole.UserRole)
        # Only confirm when deleting the root Menu (would remove all children too)
        if item.parent() is None and isinstance(node, Menu):
            reply = QMessageBox.question(self, "Delete Root Menu",
                "Delete the root menu and all its children?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
        parent = item.parent()
        if parent:
            parent.removeChild(item)
        else:
            idx = self.tree.indexOfTopLevelItem(item)
            self.tree.takeTopLevelItem(idx)
        self.prop_panel.clear()
        self.mark_modified()

    # --- File Operations ---

    def _new_file(self):
        if not self._confirm_discard():
            return
        self.tree.clear()
        self.prop_panel.clear()
        self.current_file = None
        self.modified = False
        self._update_title()

        # Create default structure
        root = Menu(name="NewMenu")
        mnu = MnuFile(root_menu=root)
        self._build_tree_from_mnu(mnu)
        # Leave modified = False so opening a file right away doesn't prompt

    def _open_file(self):
        if not self._confirm_discard():
            return
        default_dir = self._get_default_directory()
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PopMenu File", default_dir,
            "PopMenu Files (*.mnu);;All Files (*.*)"
        )
        if not path:
            return
        try:
            mnu = parse_file(path)
            self._build_tree_from_mnu(mnu)
            self.current_file = path
            self.modified = False
            self._update_title()
        except Exception as e:
            QMessageBox.critical(self, "Error Opening File", str(e))

    def _save_file(self):
        if self.current_file:
            self._do_save(self.current_file)
        else:
            self._save_file_as()

    def _save_file_as(self):
        # Suggest filename based on root menu name
        suggestion = ""
        for i in range(self.tree.topLevelItemCount()):
            node = self.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
            if isinstance(node, Menu):
                suggestion = node.name + ".mnu"
                break
        default_dir = self._get_default_directory()
        if default_dir and suggestion:
            suggestion = str(Path(default_dir) / suggestion)
        elif default_dir:
            suggestion = default_dir
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PopMenu File", suggestion,
            "PopMenu Files (*.mnu);;All Files (*.*)"
        )
        if path:
            self._do_save(path)

    def _do_save(self, path: str):
        try:
            mnu = self._tree_to_mnu()
            write_file(mnu, path)
            self.current_file = path
            self.modified = False
            self._update_title()
        except Exception as e:
            QMessageBox.critical(self, "Error Saving File", str(e))

    def _confirm_discard(self) -> bool:
        if not self.modified:
            return True
        reply = QMessageBox.question(
            self, "Unsaved Changes",
            "There are unsaved changes. Discard them?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        return reply == QMessageBox.StandardButton.Yes

    def mark_modified(self):
        self.modified = True
        self._update_title()

    def _update_title(self):
        name = os.path.basename(self.current_file) if self.current_file else "Untitled"
        mod = " *" if self.modified else ""
        self.setWindowTitle(f"CoH PopMenu Hero — {name}{mod}")

    def closeEvent(self, event):
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("CoH PopMenu Hero")

    window = MainWindow()
    window.show()

    # If a .mnu file was passed as argument, open it
    if len(sys.argv) > 1 and sys.argv[1].endswith('.mnu'):
        path = sys.argv[1]
        if os.path.exists(path):
            try:
                mnu = parse_file(path)
                window._build_tree_from_mnu(mnu)
                window.current_file = path
                window.modified = False
                window._update_title()
            except Exception as e:
                QMessageBox.critical(window, "Error", str(e))
        else:
            window._new_file()
    else:
        window._new_file()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
