use crate::exceptions::AicoError;
use crate::models::Mode;

pub async fn run(
    cli_prompt: Option<String>,
    model: Option<String>,
    system_prompt: String,
    no_history: bool,
    passthrough: bool,
) -> Result<(), AicoError> {
    crate::commands::llm_shared::run_llm_flow(
        cli_prompt,
        model,
        system_prompt,
        no_history,
        passthrough,
        Mode::Diff,
    )
    .await
}
