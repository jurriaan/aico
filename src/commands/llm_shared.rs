use crate::console::{display_cost_summary, is_stdin_terminal, is_stdout_terminal};
use crate::exceptions::AicoError;
use crate::models::{DerivedContent, HistoryRecord, Mode, Role};
use crate::session::Session;
use std::io::{self, Read, Write};
use time::OffsetDateTime;

pub async fn run_llm_flow(
    cli_prompt: Option<String>,
    model: Option<&str>,
    system_prompt: &str,
    no_history: bool,
    passthrough: bool,
    mode: Mode,
) -> Result<(), AicoError> {
    let mut stdin_buffer = None;
    if !is_stdin_terminal() {
        let mut buffer = String::new();
        if io::stdin().read_to_string(&mut buffer).is_ok() {
            let trimmed = buffer.trim();
            if !trimmed.is_empty() {
                stdin_buffer = Some(buffer);
            }
        }
    }

    let (prompt_text, piped_content) = match (cli_prompt, stdin_buffer) {
        (Some(p), Some(s)) => (p, Some(s)),
        (Some(p), None) => (p, None),
        (None, Some(s)) => (s, None),
        (None, None) => {
            if is_stdin_terminal() {
                print!("Prompt: ");
                io::stdout().flush()?;
                let mut buffer = String::new();
                io::stdin().read_line(&mut buffer)?;
                let input = buffer.trim().to_string();
                if input.is_empty() {
                    return Err(AicoError::InvalidInput("Prompt cannot be empty.".into()));
                }
                (input, None)
            } else {
                return Err(AicoError::InvalidInput("Prompt is required.".into()));
            }
        }
    };

    let mut session = Session::load_active()?;
    session.warn_missing_files();
    let active_model = model
        .map(|m| m.to_string())
        .unwrap_or_else(|| session.view.model.clone());

    let sys_prompt = if system_prompt.is_empty() {
        crate::consts::DEFAULT_SYSTEM_PROMPT
    } else {
        system_prompt
    };

    let config = crate::models::InteractionConfig {
        mode: mode.clone(),
        no_history,
        passthrough,
        model_override: Some(active_model.clone()),
    };

    let interaction = crate::llm::executor::execute_interaction(
        &session,
        sys_prompt,
        &prompt_text,
        &piped_content,
        config,
    )
    .await?;

    if !is_stdout_terminal() {
        if passthrough {
            print!("{}", interaction.content);
        } else {
            print!(
                "{}",
                crate::console::format_piped_output(
                    &interaction.unified_diff,
                    &interaction.content,
                    &mode
                )
            );
        }
        let _ = io::stdout().flush();
    }

    if let Some(usage) = &interaction.token_usage {
        display_cost_summary(usage, interaction.cost, &session.store, &session.view);
    }

    let user_msg = HistoryRecord {
        role: Role::User,
        content: prompt_text,
        mode: mode.clone(),
        timestamp: OffsetDateTime::now_utc(),
        passthrough,
        piped_content,
        model: None,
        token_usage: None,
        cost: None,
        duration_ms: None,
        derived: None,
        edit_of: None,
    };

    let asst_msg = HistoryRecord {
        role: Role::Assistant,
        content: interaction.content,
        mode: mode.clone(),
        timestamp: OffsetDateTime::now_utc(),
        passthrough,
        piped_content: None,
        model: Some(active_model),
        token_usage: interaction.token_usage,
        cost: interaction.cost,
        duration_ms: Some(interaction.duration_ms),
        derived: Some(DerivedContent {
            unified_diff: interaction.unified_diff,
            display_content: interaction.display_items.unwrap_or_default(),
        }),
        edit_of: None,
    };

    session.append_pair(user_msg, asst_msg)
}
