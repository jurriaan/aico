use crate::models::DisplayItem;
use crate::ui::markdown_streamer::MarkdownStreamer;
use std::io::Write;

pub struct LiveDisplay {
    engine: MarkdownStreamer,
    last_rendered_tail: String,
    has_started_content: bool,
    last_status_len: usize,
    width: u16,
}

impl LiveDisplay {
    pub fn new(width: u16) -> Self {
        let mut engine = MarkdownStreamer::new();
        engine.set_width(width as usize);
        engine.set_margin(2);
        Self {
            engine,
            last_rendered_tail: String::new(),
            has_started_content: false,
            last_status_len: 0,
            width,
        }
    }

    pub fn update_status(&mut self, text: &str) {
        if self.has_started_content {
            return;
        }
        let width = self.width as usize;
        let limit = width.saturating_sub(10);

        let truncated_owned: String;
        let truncated = if text.chars().count() > limit {
            truncated_owned = text.chars().take(limit).collect();
            &truncated_owned
        } else {
            text
        };

        let mut stdout = std::io::stdout();
        // Clear previous status line: CR, then spaces, then CR
        let _ = write!(stdout, "\r{}\r", " ".repeat(self.last_status_len));

        let status = format!("\x1b[2m{}...\x1b[0m", truncated);
        let _ = write!(stdout, "{}", status);
        let _ = stdout.flush();
        self.last_status_len = truncated.chars().count() + 3;
    }

    pub fn render(&mut self, items: &[DisplayItem]) {
        if items.is_empty() {
            return;
        }

        if !self.has_started_content {
            self.has_started_content = true;
            let mut stdout = std::io::stdout();
            // Final clear of reasoning status before starting markdown
            let _ = write!(stdout, "\r{}\r", " ".repeat(self.last_status_len));
            let _ = stdout.flush();
        }

        let mut stdout = std::io::stdout();

        for item in items {
            match item {
                DisplayItem::Markdown(m) => {
                    // Overlap check: if this new item starts with what we rendered last time
                    // (which was the unstable tail), render only the new part.
                    let to_print = if m.starts_with(&self.last_rendered_tail)
                        && !self.last_rendered_tail.is_empty()
                    {
                        &m[self.last_rendered_tail.len()..]
                    } else {
                        m.as_str()
                    };

                    if !to_print.is_empty() {
                        let _ = self.engine.print_chunk(&mut stdout, to_print);
                    }
                    self.last_rendered_tail = m.clone();
                }
                DisplayItem::Diff(d) => {
                    let _ = self.engine.print_chunk(&mut stdout, "\n`````diff\n");
                    let _ = self.engine.print_chunk(&mut stdout, d);
                    let _ = self.engine.print_chunk(&mut stdout, "\n`````\n");
                    // A diff block breaks the text overlap chain
                    self.last_rendered_tail.clear();
                }
            }
        }
        let _ = stdout.flush();
    }

    pub fn finish(&mut self, items: &[DisplayItem]) {
        // Just delegate to render to flush out the final state of text.
        // We pass the full confirmation list, render() logic handles deduplication.
        self.render(items);

        let mut stdout = std::io::stdout();
        let _ = self.engine.flush(&mut stdout);
        let _ = stdout.flush();
    }
}
