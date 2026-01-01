use crate::consts::*;
use crate::diffing::parser::StreamParser;
use crate::exceptions::AicoError;
use crate::historystore::reconstruct::reconstruct_history;
use crate::llm::api_models::{ChatCompletionRequest, Message, StreamOptions};
use crate::llm::client::{LlmClient, parse_sse_line};
use crate::models::{DisplayItem, InteractionResult, TokenUsage};
use crate::session::Session;
use futures_util::TryStreamExt;
use std::time::Instant;

pub fn extract_reasoning_header(reasoning_buffer: &str) -> Option<String> {
    static RE: std::sync::LazyLock<regex::Regex> = std::sync::LazyLock::new(|| {
        regex::Regex::new(r"(?m)(?:^#{1,6}\s+(?P<header>.+?)$)|(?:^[*]{2}(?P<bold>.+?)[*]{2})")
            .unwrap()
    });

    RE.captures_iter(reasoning_buffer)
        .last()
        .and_then(|cap| {
            cap.name("header")
                .or_else(|| cap.name("bold"))
                .map(|m| m.as_str().trim().to_string())
        })
        .filter(|s| !s.is_empty())
}

fn format_user_content(content: &str, piped: &Option<String>) -> String {
    if let Some(p) = piped {
        format!(
            "<stdin_content>\n{}\n</stdin_content>\n<prompt>\n{}\n</prompt>",
            p.trim(),
            content.trim()
        )
    } else {
        content.to_string()
    }
}

pub async fn build_request(
    session: &Session,
    system_prompt: &str,
    user_prompt: &str,
    mode: crate::models::Mode,
    no_history: bool,
    passthrough: bool,
) -> Result<ChatCompletionRequest, AicoError> {
    let client = LlmClient::new(&session.view.model)?;
    let config = crate::models::InteractionConfig {
        mode,
        no_history,
        passthrough,
        model_override: None,
    };
    build_request_with_piped(&client, session, system_prompt, user_prompt, &None, &config).await
}

fn format_file_block(mut files: Vec<(String, String)>, intro: &str, anchor: &str) -> Vec<Message> {
    if files.is_empty() {
        return vec![];
    }
    // Ensure deterministic ordering (alphabetical by path)
    files.sort_by(|a, b| a.0.cmp(&b.0));

    let mut block = "<context>\n".to_string();
    for (path, content) in files {
        block.push_str(&crate::models::format_file_context_xml(&path, &content));
    }
    block.push_str("</context>");

    vec![
        Message {
            role: "user".to_string(),
            content: format!("{}\n\n{}", intro, block),
        },
        Message {
            role: "assistant".to_string(),
            content: anchor.to_string(),
        },
    ]
}

pub async fn execute_interaction(
    session: &Session,
    system_prompt: &str,
    prompt_text: &str,
    piped_content: &Option<String>,
    config: crate::models::InteractionConfig,
) -> Result<InteractionResult, AicoError> {
    let model_id = config
        .model_override
        .clone()
        .unwrap_or_else(|| session.view.model.clone());
    let client = LlmClient::new(&model_id)?;

    let req = build_request_with_piped(
        &client,
        session,
        system_prompt,
        prompt_text,
        piped_content,
        &config,
    )
    .await?;

    let start_time = Instant::now();

    let response = client.stream_chat(req).await?;

    let mut full_response = String::new();
    let mut reasoning_buffer = String::new();
    let mut usage_data: Option<TokenUsage> = None;

    let should_show_live = (config.mode == crate::models::Mode::Conversation
        || config.mode == crate::models::Mode::Diff)
        && crate::console::is_stdout_terminal();

    let mut live_display: Option<crate::ui::live_display::LiveDisplay> = if should_show_live {
        let mut ld =
            crate::ui::live_display::LiveDisplay::new(crate::console::get_terminal_width() as u16);
        // Eagerly show the initial status
        ld.render(&[]);
        Some(ld)
    } else {
        None
    };

    let mut parser = StreamParser::new(&session.context_content);
    let mut cumulative_yields = Vec::new();

    use tokio::io::AsyncBufReadExt;
    let stream = response.bytes_stream().map_err(std::io::Error::other);
    let reader = tokio_util::io::StreamReader::new(stream);
    let mut lines = tokio::io::BufReader::new(reader).lines();

    while let Some(line) = lines
        .next_line()
        .await
        .map_err(|e| AicoError::Provider(format!("Stream error: {}", e)))?
    {
        if let Some(parsed) = parse_sse_line(&line) {
            if let Some(choice) = parsed.choices.first() {
                let mut reasoning_delta = String::new();
                if let Some(ref r) = choice.delta.reasoning_content {
                    reasoning_delta.push_str(r);
                }
                if let Some(ref details) = choice.delta.reasoning_details {
                    for detail in details {
                        match detail {
                            crate::llm::api_models::ReasoningDetail::Text { text } => {
                                reasoning_delta.push_str(text)
                            }
                            crate::llm::api_models::ReasoningDetail::Summary { summary } => {
                                reasoning_delta.push_str(summary)
                            }
                            _ => {}
                        }
                    }
                }

                if !reasoning_delta.is_empty() {
                    reasoning_buffer.push_str(&reasoning_delta);
                    if let Some(ref mut ld) = live_display
                        && full_response.is_empty()
                    {
                        let status = extract_reasoning_header(&reasoning_buffer)
                            .unwrap_or_else(|| "Thinking...".to_string());
                        ld.update_status(&status);
                    }
                }

                if let Some(ref content) = choice.delta.content {
                    full_response.push_str(content);

                    let yields = parser.parse_and_resolve(content, &session.root);

                    if let Some(ref mut ld) = live_display {
                        let mut ui_items: Vec<DisplayItem> = yields
                            .iter()
                            .cloned()
                            .filter_map(|i| i.to_display_item(false))
                            .collect();

                        let pending = parser.get_pending_content();
                        // Only show pending content if it doesn't look like we're about to switch
                        // to a FileHeader or a Search block, to avoid double-printing markers.
                        if !pending.is_empty() {
                            let maybe_header = pending.trim_start().starts_with("File:");
                            let maybe_marker = pending.trim_start().starts_with("<<<");
                            if !maybe_header && !maybe_marker {
                                ui_items.push(DisplayItem::Markdown(pending));
                            }
                        }

                        if !ui_items.is_empty() {
                            ld.render(&ui_items);
                        }
                    }
                    cumulative_yields.extend(yields);
                }
            }
            if let Some(u) = parsed.usage {
                let cached = u
                    .prompt_tokens_details
                    .and_then(|d| d.cached_tokens)
                    .or(u.cached_tokens);

                let reasoning = u
                    .completion_tokens_details
                    .and_then(|d| d.reasoning_tokens)
                    .or(u.reasoning_tokens);

                usage_data = Some(TokenUsage {
                    prompt_tokens: u.prompt_tokens,
                    completion_tokens: u.completion_tokens,
                    total_tokens: u.total_tokens,
                    cached_tokens: cached,
                    reasoning_tokens: reasoning,
                    cost: u.cost,
                });
            }
        }
    }

    let duration_ms = start_time.elapsed().as_millis() as u64;

    if let Some(mut ld) = live_display {
        // Finalize the live display using whatever was yielded incrementally.
        ld.finish(&[]);
    }

    // --- Finalization Pass for Storage ---
    let (unified_diff, mut final_display_items, final_warnings) =
        parser.final_resolve(&session.root);

    // Collect all warnings from incremental resolution and the final pass
    let mut all_warnings = parser.collect_warnings(&cumulative_yields);
    all_warnings.extend(final_warnings);

    // Merge incremental yields with final resolution items
    let mut all_display_items: Vec<DisplayItem> = cumulative_yields
        .into_iter()
        .filter_map(|i| i.to_display_item(true))
        .collect();
    all_display_items.append(&mut final_display_items);

    if !all_warnings.is_empty() {
        eprintln!("\nWarnings:");
        for w in &all_warnings {
            eprintln!("{}", w);
        }
    }

    let mut message_cost = None;
    if let Some(ref usage) = usage_data {
        message_cost = crate::llm::tokens::calculate_cost(&model_id, usage).await;
    }

    Ok(InteractionResult {
        content: full_response,
        display_items: Some(all_display_items),
        token_usage: usage_data,
        cost: message_cost,
        duration_ms,
        unified_diff: if unified_diff.is_empty() {
            None
        } else {
            Some(unified_diff)
        },
    })
}

pub async fn build_request_with_piped(
    client: &LlmClient,
    session: &Session,
    system_prompt: &str,
    user_prompt: &str,
    piped_content: &Option<String>,
    config: &crate::models::InteractionConfig,
) -> Result<ChatCompletionRequest, AicoError> {
    // 1. System Prompt
    let mut full_system_prompt = system_prompt.to_string();
    if config.mode == crate::models::Mode::Diff {
        full_system_prompt.push_str(DIFF_MODE_INSTRUCTIONS);
    }

    let mut messages = vec![Message {
        role: "system".to_string(),
        content: full_system_prompt,
    }];

    let history_to_use = if config.no_history {
        vec![]
    } else {
        reconstruct_history(&session.store, &session.view, false)?
    };

    if config.passthrough {
        for item in &history_to_use {
            messages.push(Message {
                role: item.record.role.to_string(),
                content: if item.record.passthrough {
                    item.record.content.clone()
                } else {
                    format_user_content(&item.record.content, &item.record.piped_content)
                },
            });
        }

        let final_user_content = if let Some(p) = piped_content {
            format!(
                "<stdin_content>\n{}\n</stdin_content>\n<prompt>\n{}\n</prompt>",
                p.trim(),
                user_prompt.trim()
            )
        } else {
            user_prompt.to_string()
        };
        messages.push(Message {
            role: "user".to_string(),
            content: final_user_content,
        });
    } else {
        // --- 2. Resolve Context State ---
        let state = session.resolve_context_state(&history_to_use)?;

        // --- 3. Linear Assembly ---
        // A. Static Context (Ground Truth)
        messages.extend(format_file_block(
            state.static_files,
            STATIC_CONTEXT_INTRO,
            STATIC_CONTEXT_ANCHOR,
        ));

        // B. History Segment 1 (Before Updates)
        for item in &history_to_use[..state.splice_idx] {
            messages.push(Message {
                role: item.record.role.to_string(),
                content: if item.record.passthrough {
                    item.record.content.clone()
                } else {
                    format_user_content(&item.record.content, &item.record.piped_content)
                },
            });
        }

        // C. Floating Context (The Update)
        messages.extend(format_file_block(
            state.floating_files,
            FLOATING_CONTEXT_INTRO,
            FLOATING_CONTEXT_ANCHOR,
        ));

        // D. History Segment 2 (After Updates)
        for item in &history_to_use[state.splice_idx..] {
            messages.push(Message {
                role: item.record.role.to_string(),
                content: if item.record.passthrough {
                    item.record.content.clone()
                } else {
                    format_user_content(&item.record.content, &item.record.piped_content)
                },
            });
        }

        // --- 5. Final Alignment and User Prompt ---
        let (align_user, align_asst) = if config.mode == crate::models::Mode::Diff {
            (ALIGNMENT_DIFF_USER, ALIGNMENT_DIFF_ASSISTANT)
        } else {
            (
                ALIGNMENT_CONVERSATION_USER,
                ALIGNMENT_CONVERSATION_ASSISTANT,
            )
        };
        messages.push(Message {
            role: "user".to_string(),
            content: align_user.to_string(),
        });
        messages.push(Message {
            role: "assistant".to_string(),
            content: align_asst.to_string(),
        });

        let final_user_content = format_user_content(user_prompt, piped_content);
        messages.push(Message {
            role: "user".to_string(),
            content: final_user_content,
        });
    }

    // --- 6. Turn Alignment (Merge consecutive same-role messages) ---
    // This provides robustness against dangling messages and ensures Turn-Based API compliance.
    let mut aligned_messages: Vec<Message> = Vec::new();
    for msg in messages {
        let trimmed_content = msg.content.trim();
        if trimmed_content.is_empty() {
            continue;
        }

        if let Some(last) = aligned_messages.last_mut()
            && last.role == msg.role
        {
            last.content.push_str("\n\n");
            last.content.push_str(trimmed_content);
            continue;
        }
        aligned_messages.push(Message {
            role: msg.role,
            content: trimmed_content.to_string(),
        });
    }

    Ok(ChatCompletionRequest {
        model: client.model_id.clone(),
        messages: aligned_messages,
        stream: true,
        stream_options: Some(StreamOptions {
            include_usage: true,
        }),
        extra_body: client.get_extra_params(),
    })
}
