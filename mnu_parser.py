"""
Parser for City of Heroes PopMenu (.mnu) files.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Any


# --- Data Model ---

class MnuNode:
    """Base class for all menu elements."""
    pass


@dataclass
class Comment(MnuNode):
    text: str

    def __repr__(self):
        return f"Comment({self.text!r})"


@dataclass
class Divider(MnuNode):
    def __repr__(self):
        return "Divider()"


@dataclass
class Title(MnuNode):
    text: str

    def __repr__(self):
        return f"Title({self.text!r})"


@dataclass
class Option(MnuNode):
    display_name: str
    command: str

    def __repr__(self):
        return f"Option({self.display_name!r}, {self.command!r})"


@dataclass
class LockedOption(MnuNode):
    display_name: str = ""
    command: str = ""
    icon: str = ""
    badge: str = ""           # space-separated list
    power_ready: str = ""
    power_owned: str = ""
    authbit: str = ""         # deprecated
    reward_token: str = ""    # deprecated
    store_product: str = ""   # deprecated

    def __repr__(self):
        return f"LockedOption({self.display_name!r})"


@dataclass
class Menu(MnuNode):
    name: str
    children: List[MnuNode] = field(default_factory=list)

    def __repr__(self):
        return f"Menu({self.name!r}, [{len(self.children)} children])"


@dataclass
class MnuFile:
    """Represents a parsed .mnu file."""
    root_comments: List[Comment] = field(default_factory=list)
    root_menu: Optional[Menu] = None


# --- Tokenizer / Lexer ---

def _unquote(token: str) -> str:
    """Remove quotes or <& &> delimiters from a token."""
    token = token.strip()
    if token.startswith('<&') and token.endswith('&>'):
        return token[2:-2].strip()
    if token.startswith('"') and token.endswith('"'):
        return token[1:-1]
    return token


def _tokenize_line(line: str) -> List[str]:
    """
    Tokenize a single line, handling quoted strings and <& &> blocks.
    Returns list of raw tokens (still quoted).
    """
    tokens = []
    i = 0
    line = line.strip()
    while i < len(line):
        # Skip whitespace
        if line[i].isspace():
            i += 1
            continue
        # Comment - rest of line is one token
        if line[i:i+2] == '//':
            tokens.append(line[i:])
            break
        # <& ... &> token
        if line[i:i+2] == '<&':
            end = line.find('&>', i + 2)
            if end == -1:
                tokens.append(line[i:])
                break
            tokens.append(line[i:end+2])
            i = end + 2
            continue
        # Quoted string
        if line[i] == '"':
            j = i + 1
            while j < len(line) and line[j] != '"':
                if line[j] == '\\':
                    j += 1  # skip escaped char
                j += 1
            tokens.append(line[i:j+1])
            i = j + 1
            continue
        # Bare word (keyword, DIVIDER, {, })
        j = i
        while j < len(line) and not line[j].isspace() and line[j] not in ('"',):
            if line[j:j+2] in ('<&',):
                break
            j += 1
        tokens.append(line[i:j])
        i = j
    return tokens


# --- Parser ---

class MnuParser:
    def __init__(self):
        self._lines: List[str] = []
        self._pos: int = 0

    def parse(self, text: str) -> MnuFile:
        self._lines = text.splitlines()
        self._pos = 0
        result = MnuFile()

        while self._pos < len(self._lines):
            line = self._lines[self._pos].strip()
            tokens = _tokenize_line(line)

            if not tokens or not line:
                self._pos += 1
                continue

            kw = tokens[0].upper()

            if kw.startswith('//'):
                result.root_comments.append(Comment(line[2:].strip()))
                self._pos += 1
            elif kw == 'TITLE':
                # A Title just before the root Menu gets absorbed into the menu as first child
                # We'll parse it here temporarily; the next Menu will absorb it.
                title_node = Title(_unquote(tokens[1]) if len(tokens) > 1 else "")
                self._pos += 1
                # Peek for the root Menu
                root_menu = self._try_parse_root_menu(title_node)
                if root_menu:
                    result.root_menu = root_menu
                # else title is orphaned - just ignore
            elif kw == 'MENU':
                result.root_menu = self._parse_menu(tokens)
            else:
                # Unknown top-level token
                self._pos += 1

        return result

    def _try_parse_root_menu(self, preceding_title: Title) -> Optional[Menu]:
        """After seeing a top-level Title, look for the following Menu."""
        saved = self._pos
        while self._pos < len(self._lines):
            line = self._lines[self._pos].strip()
            if not line:
                self._pos += 1
                continue
            tokens = _tokenize_line(line)
            if tokens and tokens[0].upper() == 'MENU':
                menu = self._parse_menu(tokens)
                # Insert preceding_title as first child
                menu.children.insert(0, preceding_title)
                return menu
            break
        self._pos = saved
        return None

    def _parse_menu(self, header_tokens: List[str]) -> Menu:
        name = _unquote(header_tokens[1]) if len(header_tokens) > 1 else ""
        menu = Menu(name=name)
        self._pos += 1

        # Expect opening brace (may be on same line or next)
        self._consume_open_brace()

        # Parse children until closing brace
        while self._pos < len(self._lines):
            line = self._lines[self._pos].strip()
            if not line:
                self._pos += 1
                continue
            tokens = _tokenize_line(line)
            if not tokens:
                self._pos += 1
                continue

            kw = tokens[0].upper()

            if kw == '}':
                self._pos += 1
                break
            elif kw.startswith('//'):
                menu.children.append(Comment(line[2:].strip()))
                self._pos += 1
            elif kw == 'DIVIDER':
                menu.children.append(Divider())
                self._pos += 1
            elif kw == 'TITLE':
                text = _unquote(tokens[1]) if len(tokens) > 1 else ""
                menu.children.append(Title(text))
                self._pos += 1
            elif kw == 'OPTION':
                dn = _unquote(tokens[1]) if len(tokens) > 1 else ""
                cmd = _unquote(tokens[2]) if len(tokens) > 2 else ""
                menu.children.append(Option(display_name=dn, command=cmd))
                self._pos += 1
            elif kw == 'LOCKEDOPTION':
                menu.children.append(self._parse_locked_option())
            elif kw == 'MENU':
                menu.children.append(self._parse_menu(tokens))
            else:
                # Unknown - skip
                self._pos += 1

        return menu

    def _consume_open_brace(self):
        """Advance past an opening '{', which may be on the current or next line."""
        while self._pos < len(self._lines):
            line = self._lines[self._pos].strip()
            if '{' in line:
                self._pos += 1
                return
            if line:
                # Non-empty line without { - maybe it's something else, don't consume
                return
            self._pos += 1

    def _parse_locked_option(self) -> LockedOption:
        lo = LockedOption()
        self._pos += 1  # consume 'LockedOption'
        self._consume_open_brace()

        while self._pos < len(self._lines):
            line = self._lines[self._pos].strip()
            if not line:
                self._pos += 1
                continue
            tokens = _tokenize_line(line)
            if not tokens:
                self._pos += 1
                continue

            kw = tokens[0].upper()

            if kw == '}':
                self._pos += 1
                break
            elif kw == 'DISPLAYNAME':
                lo.display_name = _unquote(tokens[1]) if len(tokens) > 1 else ""
                self._pos += 1
            elif kw == 'COMMAND':
                lo.command = _unquote(tokens[1]) if len(tokens) > 1 else ""
                self._pos += 1
            elif kw == 'ICON':
                lo.icon = _unquote(tokens[1]) if len(tokens) > 1 else ""
                self._pos += 1
            elif kw == 'BADGE':
                # Unquoted, space-separated list
                lo.badge = " ".join(tokens[1:])
                self._pos += 1
            elif kw == 'POWERREADY':
                lo.power_ready = tokens[1] if len(tokens) > 1 else ""
                self._pos += 1
            elif kw == 'POWEROWNED':
                lo.power_owned = tokens[1] if len(tokens) > 1 else ""
                self._pos += 1
            elif kw == 'AUTHBIT':
                lo.authbit = tokens[1] if len(tokens) > 1 else ""
                self._pos += 1
            elif kw == 'REWARDTOKEN':
                lo.reward_token = tokens[1] if len(tokens) > 1 else ""
                self._pos += 1
            elif kw == 'STOREPRODUCT':
                lo.store_product = tokens[1] if len(tokens) > 1 else ""
                self._pos += 1
            else:
                self._pos += 1

        return lo


# --- Writer ---

def _quote_value(text: str) -> str:
    """Quote a value, using <& &> if it contains double-quotes."""
    if '"' in text:
        return f'<& {text} &>'
    return f'"{text}"'


class MnuWriter:
    def write(self, mnu_file: MnuFile) -> str:
        lines = []

        # Root-level comments
        for comment in mnu_file.root_comments:
            lines.append(f"// {comment.text}")

        # Always ensure a blank line before the root menu (required by spec)
        if mnu_file.root_menu:
            lines.append("")
            lines.extend(self._write_menu(mnu_file.root_menu, indent=0))

        return "\n".join(lines) + "\n"

    def _write_menu(self, menu: Menu, indent: int) -> List[str]:
        tab = "\t" * indent
        lines = []

        # Check if first child is a Title that should be hoisted above the Menu
        # Per spec: Title just before root Menu gets written INSIDE the menu.
        # We just write it as the first child (no hoisting on write).

        lines.append(f'{tab}Menu {_quote_value(menu.name)}')
        lines.append(f'{tab}{{')
        for child in menu.children:
            lines.extend(self._write_node(child, indent + 1))
        lines.append(f'{tab}}}')
        return lines

    def _write_node(self, node: MnuNode, indent: int) -> List[str]:
        tab = "\t" * indent
        if isinstance(node, Comment):
            return [f'{tab}// {node.text}']
        elif isinstance(node, Divider):
            return [f'{tab}DIVIDER']
        elif isinstance(node, Title):
            return [f'{tab}Title {_quote_value(node.text)}']
        elif isinstance(node, Option):
            return [f'{tab}Option {_quote_value(node.display_name)} {_quote_value(node.command)}']
        elif isinstance(node, LockedOption):
            return self._write_locked_option(node, indent)
        elif isinstance(node, Menu):
            return self._write_menu(node, indent)
        return []

    def _write_locked_option(self, lo: LockedOption, indent: int) -> List[str]:
        tab = "\t" * indent
        inner = "\t" * (indent + 1)
        lines = [f'{tab}LockedOption', f'{tab}{{']
        lines.append(f'{inner}DisplayName {_quote_value(lo.display_name)}')
        lines.append(f'{inner}Command {_quote_value(lo.command)}')
        if lo.icon:
            lines.append(f'{inner}Icon {_quote_value(lo.icon)}')
        if lo.badge:
            lines.append(f'{inner}Badge {lo.badge}')
        if lo.power_ready:
            lines.append(f'{inner}PowerReady {lo.power_ready}')
        if lo.power_owned:
            lines.append(f'{inner}PowerOwned {lo.power_owned}')
        # Deprecated but preserved if present
        if lo.authbit:
            lines.append(f'{inner}Authbit {lo.authbit}')
        if lo.reward_token:
            lines.append(f'{inner}RewardToken {lo.reward_token}')
        if lo.store_product:
            lines.append(f'{inner}StoreProduct {lo.store_product}')
        lines.append(f'{tab}}}')
        return lines


def parse_file(filepath: str) -> MnuFile:
    with open(filepath, 'r', encoding='utf-8') as f:
        text = f.read()
    return MnuParser().parse(text)


def write_file(mnu_file: MnuFile, filepath: str):
    text = MnuWriter().write(mnu_file)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)
