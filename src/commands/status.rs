use crate::exceptions::AicoError;
use crate::llm::tokens::count_heuristic;
use crate::model_registry::get_model_info;
use crate::models::TokenInfo;
use crate::session::Session;
use comfy_table::ColumnConstraint;
use comfy_table::Row;
use comfy_table::Width;
use comfy_table::{Attribute, Cell, CellAlignment, Table};
use crossterm::style::Stylize;
use std::fmt::Write as _;
use std::io::Write;

pub async fn run(json_output: bool) -> Result<(), AicoError> {
    let session = Session::load_active()?;
    let model_id = &session.view.model;
    let model_info = get_model_info(model_id).await;
    let width = crate::console::get_terminal_width();

    // 1 & 2. System and Alignment Prompts
    let components = vec![
        TokenInfo {
            description: "system prompt".into(),
            tokens: crate::llm::tokens::SYSTEM_TOKEN_COUNT,
            cost: None,
        },
        TokenInfo {
            description: "alignment prompts (worst-case)".into(),
            tokens: crate::llm::tokens::MAX_ALIGNMENT_TOKENS,
            cost: None,
        },
    ];

    // 3. Chat History
    let history_vec = session.history(true)?;
    let mut history_counter = crate::llm::tokens::HeuristicCounter::new();

    for item in &history_vec {
        if item.is_excluded {
            continue;
        }

        let rec = &item.record;
        if rec.role == crate::models::Role::User && !rec.passthrough {
            if let Some(ref piped) = rec.piped_content {
                let _ = write!(
                    history_counter,
                    "<stdin_content>\n{}\n</stdin_content>\n<prompt>\n{}\n</prompt>",
                    piped.trim(),
                    rec.content.trim()
                );
            } else {
                history_counter.add_str(&rec.content);
            }
        } else {
            history_counter.add_str(&rec.content);
        }
    }

    let history_comp = TokenInfo {
        description: "chat history".into(),
        tokens: history_counter.count(),
        cost: None,
    };

    // 4. Context Files
    let mut sorted_keys: Vec<_> = session.context_content.keys().collect();
    sorted_keys.sort();

    let mut file_components: Vec<TokenInfo> = sorted_keys
        .into_iter()
        .map(|rel_path| {
            let content = &session.context_content[rel_path];
            let mut buffer = String::new();
            crate::llm::executor::append_file_context_xml(&mut buffer, rel_path, content);
            TokenInfo {
                description: rel_path.clone(),
                tokens: count_heuristic(&buffer),
                cost: None,
            }
        })
        .collect();

    // Calculate Costs and Totals
    let has_context_files = !file_components.is_empty();
    let mut all_included = components;
    all_included.push(history_comp);
    all_included.append(&mut file_components);

    let mut total_tokens = 0;
    let mut total_cost = 0.0;
    let mut has_cost_info = false;

    for comp in &mut all_included {
        total_tokens += comp.tokens;
        if let Some(ref info) = model_info {
            let usage = crate::models::TokenUsage {
                prompt_tokens: comp.tokens,
                completion_tokens: 0,
                total_tokens: comp.tokens,
                cached_tokens: None,
                reasoning_tokens: None,
                cost: None,
            };
            if let Some(cost) = crate::llm::tokens::calculate_cost_prefetched(info, &usage) {
                comp.cost = Some(cost);
                total_cost += cost;
                has_cost_info = true;
            }
        }
    }

    if json_output {
        let mut files = session.view.context_files.clone();
        files.sort();

        let session_name = session
            .view_path
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("main")
            .to_string();

        let resp = crate::models::StatusResponse {
            session_name,
            model: model_id.clone(),
            context_files: files,
            total_tokens: if total_tokens > 0 {
                Some(total_tokens)
            } else {
                None
            },
            total_cost: if has_cost_info {
                Some(total_cost)
            } else {
                None
            },
        };
        {
            let mut stdout = std::io::stdout();
            if let Err(e) = serde_json::to_writer(&mut stdout, &resp)
                && !e.is_io()
            {
                return Err(AicoError::Session(e.to_string()));
            }
            let _ = writeln!(stdout);
        }
        return Ok(());
    }

    // Header Panel
    let session_name = session
        .view_path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("main");

    session.warn_missing_files();

    crate::console::draw_panel(
        &format!("Session '{}'", session_name),
        std::slice::from_ref(model_id),
        width,
    );
    println!();

    // Table configured for parity with Python's rich
    let mut table = Table::new();
    table
        .load_preset(comfy_table::presets::NOTHING)
        .set_content_arrangement(comfy_table::ContentArrangement::DynamicFullWidth)
        .set_style(comfy_table::TableComponent::HeaderLines, '─')
        .set_style(comfy_table::TableComponent::MiddleHeaderIntersections, ' ')
        .set_width(width as u16)
        .set_truncation_indicator("");

    table.set_header(vec![
        Cell::new("Tokens\n(approx.)").add_attribute(Attribute::Bold),
        Cell::new("Cost").add_attribute(Attribute::Bold),
        Cell::new("Component").add_attribute(Attribute::Bold),
    ]);

    // Apply constraints to ensure predictable alignment with panels
    table
        .column_mut(0)
        .unwrap()
        .set_constraint(ColumnConstraint::UpperBoundary(Width::Fixed(10)));
    table
        .column_mut(1)
        .unwrap()
        .set_constraint(ColumnConstraint::UpperBoundary(Width::Fixed(10)));

    // 1 & 2. System and Alignment
    for comp in all_included.iter().take(2) {
        let cost_str = comp.cost.map(|c| format!("${:.5}", c)).unwrap_or_default();
        table.add_row(vec![
            Cell::new(crate::console::format_thousands(comp.tokens)),
            Cell::new(cost_str),
            Cell::new(&comp.description),
        ]);
    }

    // 3. History
    let history_cost_str = all_included[2]
        .cost
        .map(|c| format!("${:.5}", c))
        .unwrap_or_default();
    table.add_row(vec![
        Cell::new(crate::console::format_thousands(all_included[2].tokens)),
        Cell::new(history_cost_str),
        Cell::new(&all_included[2].description),
    ]);

    // History Summary Line
    if let Ok(Some(summary)) = session.summarize_active_window(&history_vec) {
        if summary.active_pairs > 0 {
            let mut line1 = format!(
                "└─ Active window: {} pair{} (IDs {}-{}), {} sent",
                summary.active_pairs,
                if summary.active_pairs == 1 { "" } else { "s" },
                summary.active_start_id,
                summary.active_end_id,
                summary.pairs_sent
            );

            if summary.excluded_in_window > 0 {
                line1.push_str(&format!(" ({} excluded)", summary.excluded_in_window));
            }
            line1.push('.');

            let line2 = "(Use `aico log`, `undo`, and `set-history` to manage)";

            let (fmt1, fmt2) = if crate::console::is_stdout_terminal() {
                (
                    format!("   {}", line1).dim().to_string(),
                    format!("      {}", line2).dim().italic().to_string(),
                )
            } else {
                (format!("   {}", line1), format!("      {}", line2))
            };

            table.add_row(vec![Cell::new(""), Cell::new(""), Cell::new(fmt1)]);
            table.add_row(vec![Cell::new(""), Cell::new(""), Cell::new(fmt2)]);
        }

        if summary.has_dangling {
            table.add_row(vec![
                Cell::new(""),
                Cell::new(""),
                Cell::new(
                    "Active context contains partial/dangling messages."
                        .yellow()
                        .to_string(),
                ),
            ]);
        }
    }

    // 4. Context Files
    if has_context_files {
        let mut separator = Row::from(vec![
            Cell::new("─".repeat(width)),
            Cell::new("─".repeat(width)),
            Cell::new("─".repeat(width)),
        ]);
        separator.max_height(1);
        table.add_row(separator);

        for comp in all_included.iter().skip(3) {
            let cost_str = comp.cost.map(|c| format!("${:.5}", c)).unwrap_or_default();
            table.add_row(vec![
                Cell::new(crate::console::format_thousands(comp.tokens)),
                Cell::new(cost_str),
                Cell::new(&comp.description),
            ]);
        }
    }

    // Final Total Row
    let mut separator = Row::from(vec![
        Cell::new("─".repeat(width)),
        Cell::new("─".repeat(width)),
        Cell::new("─".repeat(width)),
    ]);
    separator.max_height(1);
    table.add_row(separator);

    let total_cost_str = if has_cost_info {
        format!("${:.5}", total_cost)
    } else {
        "".to_string()
    };
    table.add_row(vec![
        Cell::new(format!(
            "~{}",
            crate::console::format_thousands(total_tokens)
        ))
        .add_attribute(Attribute::Bold),
        Cell::new(total_cost_str).add_attribute(Attribute::Bold),
        Cell::new("Total").add_attribute(Attribute::Bold),
    ]);

    table
        .column_mut(0)
        .unwrap()
        .set_padding((0, 0))
        .set_cell_alignment(CellAlignment::Right);
    table
        .column_mut(1)
        .unwrap()
        .set_padding((0, 0))
        .set_cell_alignment(CellAlignment::Right);
    table
        .column_mut(2)
        .unwrap()
        .set_padding((0, 0))
        .set_cell_alignment(CellAlignment::Left);

    println!("{}", table);

    // Context Window Panel
    if let Some(info) = model_info
        && let Some(max) = info.max_input_tokens
    {
        println!();
        let pct = (total_tokens as f64 / max as f64).min(1.0);
        let bar_max_width = width.saturating_sub(4);
        let filled = (pct * bar_max_width as f64) as usize;

        let bar_filled = "━".repeat(filled);
        let bar = format!(
            "{}{}",
            if crate::console::is_stdout_terminal() {
                bar_filled.cyan().bold().to_string()
            } else {
                bar_filled
            },
            " ".repeat(bar_max_width.saturating_sub(filled))
        );

        let summary = format!(
            "({} of {} used - {:.0}% remaining)",
            crate::console::format_thousands(total_tokens),
            crate::console::format_thousands(max),
            (1.0 - pct) * 100.0
        );

        crate::console::draw_panel("Context Window", &[summary, bar], width);
    }

    Ok(())
}
