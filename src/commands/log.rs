// src/commands/log.rs

use crate::console::strip_ansi_codes;
use crate::exceptions::AicoError;
use crate::historystore::reconstruct::reconstruct_history;
use crate::models::Role;
use crate::session::Session;
use comfy_table::presets::NOTHING;
use comfy_table::*;

/// Helper to create and style a log row
fn create_log_row(id: &str, role: &str, snippet: &str, color: Color, is_excluded: bool) -> Row {
    let cells = vec![
        Cell::new(id).set_alignment(CellAlignment::Right),
        Cell::new(role).fg(color),
        Cell::new(snippet),
    ];

    if is_excluded {
        Row::from(
            cells
                .into_iter()
                .map(|cell| cell.add_attribute(Attribute::Dim)),
        )
    } else {
        Row::from(cells)
    }
}

pub fn run() -> Result<(), AicoError> {
    let session = Session::load_active()?;
    let width = crate::console::get_terminal_width();

    // Log needs to see excluded messages to show them as dimmed [-] entries
    let history_vec = reconstruct_history(&session.store, &session.view, true)?;

    let mut paired_history = Vec::new();
    let mut dangling_history = Vec::new();

    // Separate paired vs dangling for Python parity
    let mut i = 0;
    while i < history_vec.len() {
        let current = &history_vec[i];
        let next = history_vec.get(i + 1);

        if current.record.role == Role::User
            && next.is_some_and(|n| {
                n.record.role == Role::Assistant && n.pair_index == current.pair_index
            })
        {
            paired_history.push(current);
            paired_history.push(next.unwrap());
            i += 2;
        } else {
            dangling_history.push(current);
            i += 1;
        }
    }

    if paired_history.is_empty() && dangling_history.is_empty() {
        println!("No message pairs found in active history.");
        return Ok(());
    }

    let mut table = Table::new();
    table
        .load_preset(NOTHING)
        .set_width(width as u16)
        .set_content_arrangement(ContentArrangement::Dynamic);

    // Match Python header: bold ID, Role, Message Snippet
    table.set_header(vec![
        Cell::new("ID")
            .add_attribute(Attribute::Bold)
            .set_alignment(CellAlignment::Right),
        Cell::new("Role").add_attribute(Attribute::Bold),
        Cell::new("Message Snippet").add_attribute(Attribute::Bold),
    ]);

    // Set constraints to let the snippet column take the majority of the room
    table
        .column_mut(0)
        .unwrap()
        .set_constraint(ColumnConstraint::ContentWidth);
    table
        .column_mut(1)
        .unwrap()
        .set_constraint(ColumnConstraint::ContentWidth);
    let snippet_col = table.column_mut(2).unwrap();
    snippet_col.set_constraint(ColumnConstraint::LowerBoundary(Width::Fixed(20)));

    for item in paired_history {
        let pair_idx = item.pair_index;
        let is_excluded = item.is_excluded;

        let id_display = if is_excluded {
            format!("{}[-]", pair_idx)
        } else {
            pair_idx.to_string()
        };

        let get_snippet = |content: &str| content.lines().next().unwrap_or("").trim().to_string();

        let (role_name, role_color) = match item.record.role {
            Role::User => ("user", Color::Blue),
            Role::Assistant => ("assistant", Color::Green),
            Role::System => ("system", Color::Grey),
        };

        table.add_row(create_log_row(
            if item.record.role == Role::User {
                &id_display
            } else {
                ""
            },
            role_name,
            &get_snippet(&item.record.content),
            role_color,
            is_excluded,
        ));
    }

    let table_output = table.to_string();

    // Calculate table width excluding ANSI codes to center title correctly
    let plain_output = strip_ansi_codes(&table_output);
    let table_full_width = plain_output.lines().next().unwrap_or("").len();

    let title = "Active Context Log";
    if table_full_width > title.len() {
        let padding = (table_full_width - title.len()) / 2;
        println!("{}{}{}", " ".repeat(padding), title, " ".repeat(padding));
    } else {
        println!("{}", title);
    }

    println!("{}", table_output);

    if !dangling_history.is_empty() {
        println!("\nDangling messages in active context:");
        for item in dangling_history {
            let role_name = match item.record.role {
                Role::User => "user",
                Role::Assistant => "assistant",
                Role::System => "system",
            };
            let snippet = item.record.content.lines().next().unwrap_or("").trim();
            println!("{}: {}", role_name, snippet);
        }
    }

    Ok(())
}
