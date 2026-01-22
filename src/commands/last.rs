use crate::console::is_stdout_terminal;
use crate::exceptions::AicoError;
use crate::models::{DisplayItem, MessagePairJson, MessageWithId};
use crate::session::Session;
use std::io::Write;

pub fn run(
    index_str: String,
    prompt: bool,
    verbatim: bool,
    recompute: bool,
    json: bool,
) -> Result<(), AicoError> {
    let session = Session::load_active()?;
    let resolved_idx = session.resolve_pair_index(&index_str)?;

    let (user_rec, asst_rec, user_id, asst_id) = session.fetch_pair(resolved_idx)?;

    if json {
        let output = MessagePairJson {
            pair_index: resolved_idx,
            user: MessageWithId {
                record: user_rec,
                id: user_id,
            },
            assistant: MessageWithId {
                record: asst_rec,
                id: asst_id,
            },
        };

        let mut stdout = std::io::stdout();
        let res = if crate::console::is_stdout_terminal() {
            serde_json::to_writer_pretty(&mut stdout, &output)
        } else {
            serde_json::to_writer(&mut stdout, &output)
        };

        if let Err(e) = res
            && !e.is_io()
        {
            return Err(AicoError::Serialization(e));
        }
        let _ = writeln!(stdout);
        return Ok(());
    }

    if prompt {
        if recompute {
            return Err(AicoError::InvalidInput(
                "--recompute cannot be used with --prompt.".into(),
            ));
        }
        print!("{}", user_rec.content);
        return Ok(());
    }

    if verbatim {
        print!("{}", asst_rec.content);
        return Ok(());
    }

    let is_tty = is_stdout_terminal();

    // 1. Resolve structured content
    // We parse if recompute is requested OR if derived content is missing (fallback for legacy or broken history)
    let (unified_diff, display_items, warnings) = match (&asst_rec.derived, recompute) {
        (Some(derived), false) => (
            derived.unified_diff.clone(),
            derived
                .display_content
                .clone()
                .unwrap_or_else(|| vec![DisplayItem::Markdown(asst_rec.content.clone())]),
            vec![],
        ),
        _ => {
            use crate::diffing::parser::StreamParser;

            let mut parser = StreamParser::new(&session.context_content);
            let gated_content = if asst_rec.content.ends_with('\n') {
                asst_rec.content.clone()
            } else {
                format!("{}\n", asst_rec.content)
            };
            parser.feed(&gated_content);

            let (diff, items, warnings) = parser.final_resolve(&session.root);

            (Some(diff), items, warnings)
        }
    };

    // 2. Render based on TTY and intent
    if is_tty {
        let width = crate::console::get_terminal_width();
        let mut engine = crate::ui::markdown_streamer::MarkdownStreamer::new();
        engine.set_width(width);
        engine.set_margin(0);

        let mut stdout = std::io::stdout();
        for item in &display_items {
            match item {
                DisplayItem::Markdown(m) => {
                    let _ = engine.print_chunk(&mut stdout, m);
                }
                DisplayItem::Diff(d) => {
                    let _ = engine.print_chunk(&mut stdout, "\n~~~~~diff\n");
                    let _ = engine.print_chunk(&mut stdout, d);
                    let _ = engine.print_chunk(&mut stdout, "\n~~~~~\n");
                }
            }
        }
        let _ = engine.flush(&mut stdout);
    } else {
        // Composable output (pipes) - Piped Output Contract
        // Strict for Diff mode, Flexible for others.
        if matches!(asst_rec.mode, crate::models::Mode::Diff) {
            if let Some(diff) = unified_diff {
                print!("{}", diff);
            }
        } else {
            // Flexible: Prefer diff if parsed, else fallback to raw content.
            if let Some(diff) = unified_diff {
                if !diff.is_empty() {
                    print!("{}", diff);
                } else {
                    print!("{}", asst_rec.content);
                }
            } else {
                print!("{}", asst_rec.content);
            }
        }
    }

    if !warnings.is_empty() {
        eprintln!("\nWarnings:");
        for w in warnings {
            eprintln!("{}", w);
        }
    }

    Ok(())
}
