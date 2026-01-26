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

pub fn append_reasoning_delta(
    buffer: &mut String,
    delta: &crate::llm::api_models::ChunkDelta,
) -> bool {
    let start_len = buffer.len();

    // Priority 1: Direct reasoning_content
    if let Some(ref r) = delta.reasoning_content
        && !r.is_empty()
    {
        buffer.push_str(r);
        return true;
    }

    // Priority 2: Structured reasoning_details
    if let Some(ref details) = delta.reasoning_details {
        for detail in details {
            match detail {
                crate::llm::api_models::ReasoningDetail::Text { text } => buffer.push_str(text),
                crate::llm::api_models::ReasoningDetail::Summary { summary } => {
                    buffer.push_str(summary)
                }
                _ => {}
            }
        }
    }

    buffer.len() > start_len
}

pub fn extract_reasoning_header(reasoning_buffer: &str) -> Option<&str> {
    static RE: std::sync::LazyLock<regex::Regex> = std::sync::LazyLock::new(|| {
        regex::Regex::new(r"(?m)(?:^#{1,6}\s+(?P<header>.+?)[\r\n])|(?:^[*]{2}(?P<bold>.+?)[*]{2})")
            .unwrap()
    });

    RE.captures_iter(reasoning_buffer)
        .last()
        .and_then(|cap| {
            cap.name("header")
                .or_else(|| cap.name("bold"))
                .map(|m| m.as_str().trim())
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

pub fn append_file_context_xml(buffer: &mut String, path: &str, content: &str) {
    use std::fmt::Write;
    // write! handles the formatting directly into the buffer
    let _ = writeln!(buffer, "  <file path=\"{}\">", path);
    buffer.push_str(content);
    if !content.ends_with('\n') {
        buffer.push('\n');
    }
    buffer.push_str("  </file>\n");
}

fn merge_display_items(items: Vec<DisplayItem>) -> Vec<DisplayItem> {
    let mut merged = Vec::with_capacity(items.len());
    for item in items {
        match (merged.last_mut(), item) {
            (Some(DisplayItem::Markdown(last)), DisplayItem::Markdown(next)) => {
                last.push_str(&next);
            }
            (_, item) => merged.push(item),
        }
    }
    merged
}

fn format_file_block(mut files: Vec<(&str, &str)>, intro: &str, anchor: &str) -> Vec<Message> {
    if files.is_empty() {
        return vec![];
    }
    // Ensure deterministic ordering (alphabetical by path)
    files.sort_by(|a, b| a.0.cmp(b.0));

    let mut block = "<context>\n".to_string();
    for (path, content) in files {
        append_file_context_xml(&mut block, path, content);
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

    loop {
        match lines.next_line().await {
            Ok(Some(line)) => {
                if let Some(parsed) = parse_sse_line(&line) {
                    if let Some(choice) = parsed.choices.first() {
                        let did_update =
                            append_reasoning_delta(&mut reasoning_buffer, &choice.delta);

                        if did_update
                            && let Some(ref mut ld) = live_display
                            && full_response.is_empty()
                        {
                            let status = extract_reasoning_header(&reasoning_buffer)
                                .unwrap_or("Thinking...");
                            ld.update_status(status);
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

                                if parser.is_pending_displayable() {
                                    let pending = parser.get_pending_content();
                                    ui_items.push(DisplayItem::Markdown(pending));
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
            Ok(None) => break,
            Err(e) => {
                if !full_response.is_empty() {
                    eprintln!(
                        "\n[WARN] Stream interrupted: {}. Saving partial response.",
                        e
                    );
                    break;
                } else {
                    return Err(AicoError::Provider(format!("Stream error: {}", e)));
                }
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
    let mut raw_display_items: Vec<DisplayItem> = cumulative_yields
        .into_iter()
        .filter_map(|i| i.to_display_item(true))
        .collect();
    raw_display_items.append(&mut final_display_items);

    let all_display_items = merge_display_items(raw_display_items);

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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::DisplayItem;

    #[test]
    fn test_merge_display_items_collapses_consecutive_markdown() {
        let items = vec![
            DisplayItem::Markdown("Hello ".into()),
            DisplayItem::Markdown("World".into()),
            DisplayItem::Diff("diff1".into()),
            DisplayItem::Markdown("Part 1".into()),
            DisplayItem::Markdown("Part 2".into()),
            DisplayItem::Diff("diff2".into()),
        ];

        let merged = merge_display_items(items);

        assert_eq!(merged.len(), 4);
        assert_eq!(merged[0], DisplayItem::Markdown("Hello World".into()));
        assert_eq!(merged[1], DisplayItem::Diff("diff1".into()));
        assert_eq!(merged[2], DisplayItem::Markdown("Part 1Part 2".into()));
        assert_eq!(merged[3], DisplayItem::Diff("diff2".into()));
    }

    #[test]
    fn test_merge_display_items_handles_empty_or_single() {
        let items: Vec<DisplayItem> = vec![];
        assert_eq!(merge_display_items(items).len(), 0);

        let items = vec![DisplayItem::Markdown("one".into())];
        assert_eq!(merge_display_items(items).len(), 1);
    }
}
