from typing import final, override

from rich._loop import loop_last
from rich.console import Console, ConsoleOptions, RenderResult
from rich.live_render import LiveRender
from rich.segment import Segment
from rich.text import Text


# Based on https://github.com/Textualize/rich/pull/3311
# Renders with a custom overflow behavior
@final
class AicoLiveRender(LiveRender):
    @override
    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        renderable = self.renderable
        style = console.get_style(self.style)
        lines = console.render_lines(renderable, options, style=style, pad=False)
        shape = Segment.get_shape(lines)

        _, height = shape
        if height > options.size.height and self.vertical_overflow != "visible":
            overflow_text = Text(
                "...",
                overflow="crop",
                justify="center",
                end="",
                style="live.ellipsis",
            )
            lines = lines[-(options.size.height) : -1]
            lines.insert(0, list(console.render(overflow_text)))
            shape = Segment.get_shape(lines)

        self._shape = shape

        new_line = Segment.line()
        for last, line in loop_last(lines):
            yield from line
            if not last:
                yield new_line
