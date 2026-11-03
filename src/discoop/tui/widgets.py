"""Small keyboard-first widgets of the discoop TUI.

Every control here is exactly one line high and has no border. The dialogs in modals.py can use them too:
- `ChoiceRow`: a value picked with ←/→ (`Mode       < safe >`),
- `InputRow`: a label and a compact `Input`,
- `ActionRow`: a focusable one-line button,
- `ConfirmRow`: an `ActionRow` that asks before it acts,
- `FormPanel`: a scrolling column of rows; ↑/↓ move between them, also out of an `Input`,
- `TextView`: read-only text of any length,
- `ChannelTree`: the server tree, with a right-aligned badge on a node,
- `SelectedList`: the list of selected channels,
- `FilterInput`: the tree filter,
- `display_name()`: a server or channel name made safe for the terminal.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Self

from rich.cells import cell_len, chop_cells
from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.geometry import Size
from textual.message import Message
from textual.reactive import reactive
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Input, Label, OptionList, Static, Tree
from textual.widgets.tree import TreeNode

LABEL_WIDTH = 13
_INVISIBLE = str.maketrans("", "", "\ufe0e\ufe0f\u200d")
_BADGE_STYLE = Style(dim=True)


def display_name(name: str) -> str:
    """A name without the characters that break column alignment in Windows Terminal.

    Removes the variation selectors U+FE0E and U+FE0F and the zero-width joiner U+200D. For display only: IDs, stored
    data and the CLI command keep the original name.
    """
    return name.translate(_INVISIBLE)


class ChoiceRow(Widget, can_focus=True):
    """One line with a label and a value picked from `options`: `Mode         < safe >`.

    Keyboard: ←/→ or Space step through the options and wrap around. Mouse: a click on `<` steps back, a click on the
    value or `>` steps forward, a click on the label only focuses the row.

    A user's change posts `ChoiceRow.Changed`. `set_value()` changes the value quietly and also accepts a value
    outside `options`, e.g. "custom" when the form holds something no option describes.
    """

    DEFAULT_CSS = """
    ChoiceRow {
        width: 100%;
        height: 1;

        &:focus {
            background: $block-cursor-background;
            color: $block-cursor-foreground;
            text-style: bold;
        }
    }
    """

    BINDINGS = [
        Binding("left", "step(-1)", "Change", show=False),
        Binding("right", "step(1)", "Change", key_display="←→"),
        Binding("space", "step(1)", "Change", show=False),
    ]

    value: reactive[str] = reactive("", init=False)
    """The current value."""

    class Changed(Message):
        """The user picked another value."""

        def __init__(self, row: ChoiceRow, value: str) -> None:
            super().__init__()
            self.row = row
            self.value = value

        @property
        def control(self) -> ChoiceRow:
            return self.row

    def __init__(
        self,
        label: str,
        options: Sequence[str],
        value: str | None = None,
        *,
        label_width: int = LABEL_WIDTH,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(id=id, classes=classes, disabled=disabled)
        if not options:
            raise ValueError("ChoiceRow needs at least one option.")
        self.label = label
        self.options = tuple(options)
        self.label_width = label_width
        self.set_reactive(ChoiceRow.value, self.options[0] if value is None else value)

    def render(self) -> Text:
        return Text(f"{self.label:<{self.label_width}}< {self.value} >", no_wrap=True, overflow="ellipsis")

    def set_value(self, value: str) -> None:
        """Show `value` without posting `Changed`."""
        with self.prevent(ChoiceRow.Changed):
            self.value = value

    def watch_value(self, value: str) -> None:
        self.post_message(self.Changed(self, value))

    def action_step(self, delta: int) -> None:
        try:
            index = self.options.index(self.value) + delta
        except ValueError:  # outside `options`: start from the matching end
            index = 0 if delta > 0 else -1
        self.value = self.options[index % len(self.options)]

    def on_click(self, event: events.Click) -> None:
        self.focus()
        if event.x >= self.label_width:
            self.action_step(-1 if event.x <= self.label_width + 1 else 1)


class InputRow(Horizontal):
    """One line with a label and a compact `Input`. An empty value is always valid."""

    DEFAULT_CSS = """
    InputRow {
        width: 100%;
        height: 1;

        & > Label {
            height: 1;
        }
        & > Input {
            width: 1fr;
        }
        &:focus-within > Label {
            background: $block-cursor-background;
            color: $block-cursor-foreground;
            text-style: bold;
        }
    }
    """

    def __init__(
        self,
        label: str,
        input_id: str,
        *,
        value: str = "",
        placeholder: str = "",
        input_type: str = "text",
        password: bool = False,
        label_width: int = LABEL_WIDTH,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.label = label
        self.input_id = input_id
        self.value = value
        self.placeholder = placeholder
        self.input_type = input_type
        self.password = password
        self.label_width = label_width

    def compose(self) -> ComposeResult:
        yield Label(f"{self.label:<{self.label_width}}", markup=False)
        yield Input(
            value=self.value,
            placeholder=self.placeholder,
            type=self.input_type,  # type: ignore[arg-type]
            password=self.password,
            valid_empty=True,
            compact=True,
            id=self.input_id,
        )


class ActionRow(Static, can_focus=True):
    """A focusable one-line button. Enter or a click posts `ActionRow.Pressed`; `update()` changes its text."""

    DEFAULT_CSS = """
    ActionRow {
        width: 100%;
        height: 1;

        &:focus {
            background: $block-cursor-background;
            color: $block-cursor-foreground;
            text-style: bold;
        }
    }
    """

    BINDINGS = [Binding("enter", "press", "Run", show=False)]

    class Pressed(Message):
        """The row was activated."""

        def __init__(self, row: ActionRow) -> None:
            super().__init__()
            self.row = row

        @property
        def control(self) -> ActionRow:
            return self.row

    def __init__(self, text: str, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(text, markup=False, id=id, classes=classes)

    def action_press(self) -> None:
        self.post_message(self.Pressed(self))

    def on_click(self) -> None:
        self.focus()
        self.action_press()


class ConfirmRow(ActionRow):
    """An `ActionRow` that asks first: one press shows `question`, the next posts `Pressed`. Moving away takes it back."""

    def __init__(self, text: str, question: str, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(text, id=id, classes=classes)
        self.idle_text = text
        self.question = question
        self.asking = False

    def action_press(self) -> None:
        if self.asking:
            super().action_press()
        self._ask(not self.asking)

    def on_blur(self) -> None:
        self._ask(False)

    def _ask(self, asking: bool) -> None:
        self.asking = asking
        self.update(self.question if asking else self.idle_text)


class FormPanel(VerticalScroll, can_focus=False):
    """A scrolling column of rows. ↑/↓ move the focus between them, also from an `Input` (which leaves them alone).

    Enter in an `Input` confirms it and goes to the next row. With `enter_moves=False` the panel leaves
    `Input.Submitted` to its parent, for a dialog that saves on Enter. Rows hidden with `display` are skipped.
    """

    BINDINGS = [
        Binding("up", "move(-1)", show=False),
        Binding("down", "move(1)", show=False),
    ]

    def __init__(self, *, enter_moves: bool = True, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self.enter_moves = enter_moves
        self._last_focused: Widget | None = None

    def rows(self) -> list[Widget]:
        """The focusable widgets of the form in focus order, hidden rows left out."""
        return [widget for widget in self.screen.focus_chain if self in widget.ancestors]

    def focus_row(self) -> None:
        """Focus the row that had the focus last, else the first one."""
        rows = self.rows()
        if self._last_focused in rows:
            self._last_focused.focus()
        elif rows:
            rows[0].focus()

    def action_move(self, delta: int) -> None:
        rows = self.rows()
        focused = self.screen.focused
        if focused in rows:
            index = rows.index(focused) + delta
            if 0 <= index < len(rows):
                rows[index].focus()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        self._last_focused = event.widget

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self.enter_moves:
            event.stop()
            self.action_move(1)


def wrapped(line: str, width: int) -> list[tuple[int, int]]:
    """The (start, end) of each row `line` takes in `width` cells, broken after a space where it can be."""
    cells = cell_len(line)
    if cells <= width:
        return [(0, len(line))]
    rows = []
    start = 0
    if cells != len(line):  # wide characters: a row is not `width` characters here
        for chunk in chop_cells(line, width):
            rows.append((start, start + len(chunk)))
            start += len(chunk)
        return rows
    while len(line) - start > width:
        space = line.rfind(" ", start + 1, start + width + 1)
        end = space + 1 if space != -1 else start + width
        rows.append((start, end))
        start = end
    rows.append((start, len(line)))
    return rows


class TextView(ScrollView, can_focus=False):
    """Read-only text of any length, a string (never read as markup) or a `Text`.

    Only the rows in view get rendered. A `Static` wraps and styles the whole text on every change, which freezes the
    UI for seconds with thousands of messages. The dialog owns the scroll keys, so this widget takes no focus.
    """

    DEFAULT_CSS = """
    TextView {
        overflow-x: hidden;
        scrollbar-gutter: stable;
    }
    """

    def __init__(self, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self.content: str | Text = ""
        self._lines: list[str] | list[Text] = []
        self._rows: list[tuple[int, int, int]] = []  # line number, and where the row starts and ends in that line
        self._wrap_width = 0

    def update(self, content: str | Text) -> None:
        """Show `content` from its start."""
        self.content = content
        if isinstance(content, Text):
            text = content.copy()
            text.expand_tabs(4)
            self._lines = list(text.split("\n", allow_blank=True))
        else:
            self._lines = content.expandtabs(4).split("\n")
        self._wrap()
        self.scroll_home(animate=False)

    def _wrap(self) -> None:
        width = self.scrollable_content_region.width
        if width <= 0:  # not laid out yet: `on_resize` brings us back
            return
        self._wrap_width = width
        rows = []
        for number, line in enumerate(self._lines):
            plain = line.plain if isinstance(line, Text) else line
            rows.extend((number, start, end) for start, end in wrapped(plain, width))
        self._rows = rows
        self.virtual_size = Size(width, len(rows))
        self.refresh()

    def on_resize(self) -> None:
        if self.scrollable_content_region.width != self._wrap_width:
            self._wrap()

    def render_line(self, y: int) -> Strip:
        width = self.scrollable_content_region.width
        row = self.scroll_offset.y + y
        if row >= len(self._rows):
            return Strip.blank(width, self.rich_style)
        number, start, end = self._rows[row]
        line = self._lines[number]
        text = line[start:end] if isinstance(line, Text) else Text(line[start:end])
        return Strip(text.render(self.app.console)).apply_style(self.rich_style).crop_extend(0, width, self.rich_style)


class FilterInput(Input):
    """The tree filter: ↓ gives the focus back to the tree. The app handles Enter and Esc."""

    BINDINGS = [Binding("down", "app.pane(1)", show=False)]

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(placeholder="/ filter", compact=True, id=id)


class SelectedList(OptionList):
    """The selected channels."""

    BINDINGS = [
        Binding("x,delete", "app.remove_selected", "Remove"),
        Binding("X", "app.clear_selected", "Clear all"),
        Binding("e", "app.edit_selected_window", "Window"),
    ]

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(compact=True, id=id)


class ChannelTree(Tree[Any]):
    """Servers, categories and channels. Nothing here selects or loads anything: the app owns that.

    →/← open and close nodes and walk the tree. Enter and a click post the usual `Tree.NodeSelected`, which no longer
    expands on its own (`auto_expand` is off), so the app decides per node type. Rows fill the width of the tree and
    long names end with `…`, so it never scrolls sideways. A top-level node can carry a dimmed badge at its right edge.
    """

    ICON_NODE = "▸ "
    ICON_NODE_EXPANDED = "▾ "

    BINDINGS = [
        Binding("right", "expand_or_child", "Open", key_display="→", show=False),
        Binding("left", "collapse_or_parent", "Close", key_display="←", show=False),
        Binding("space", "app.toggle_cursor", "Select", key_display="Space"),
        Binding("a", "app.select_shown", "All"),
        Binding("r", "app.reload_channels", "Reload"),
        Binding("e", "app.edit_tree_window", "Window"),
    ]

    def __init__(self, label: str, *, id: str | None = None) -> None:
        super().__init__(label, id=id)
        self.show_root = False
        self.show_guides = False
        self.guide_depth = 2
        self.auto_expand = False
        self._badges: dict[int, str] = {}

    def clear(self) -> Self:
        self._badges.clear()
        return super().clear()

    def add_top(self, label: Text, *, data: Any, badge: str, expand: bool = False) -> TreeNode[Any]:
        """Add a top-level node with a badge at the right edge of its row."""
        node = self.root.add(label, data=data, expand=expand)
        self._badges[node.id] = badge
        return node

    def set_badge(self, node: TreeNode[Any], badge: str) -> None:
        """Change the badge of a node."""
        self._badges[node.id] = badge
        node.refresh()

    def get_label_width(self, node: TreeNode[Any]) -> int:
        return 0  # `render_label` fits every row into the tree, so the content is never wider than the tree

    def render_label(self, node: TreeNode[Any], base_style: Style, style: Style) -> Text:
        text = super().render_label(node, base_style, style)
        depth = 0
        parent = node.parent
        while parent is not None and not parent.is_root:
            depth += 1
            parent = parent.parent
        width = self.scrollable_content_region.width - depth * self.guide_depth
        if width <= 0:  # not laid out yet
            return text
        badge = self._badges.get(node.id, "")
        badge_width = cell_len(badge)
        room = max(1, width - badge_width - 1) if badge else width
        text.truncate(room, overflow="ellipsis")
        text.append(" " * max(0, width - text.cell_len - badge_width), style)
        if badge:
            text.append(badge, style + _BADGE_STYLE)
        return text

    def action_expand_or_child(self) -> None:
        """Open a closed node; on an open one, go to its first child."""
        node = self.cursor_node
        if node is None or not node.allow_expand:
            return
        if not node.is_expanded:
            node.expand()
        elif node.children:
            self._move_to(node.children[0])

    def action_collapse_or_parent(self) -> None:
        """Close an open node; on a closed one or a leaf, go to its parent."""
        node = self.cursor_node
        if node is None:
            return
        if node.allow_expand and node.is_expanded:
            node.collapse()
        elif node.parent is not None and not node.parent.is_root:
            self._move_to(node.parent)

    def _move_to(self, node: TreeNode[Any]) -> None:
        _ = self.last_line  # builds the lines if needed, `move_cursor` relies on their numbers
        self.move_cursor(node)
