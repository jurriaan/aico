use axum::{
    Router,
    extract::Json,
    response::sse::{Event, KeepAlive, Sse},
    routing::post,
};
use futures::stream::{self, Stream};
use serde_json::{Value, json};
use std::convert::Infallible;
use std::env;
use std::process::Stdio;
use tokio::net::TcpListener;
use tokio::process::Command;

#[tokio::main(flavor = "current_thread")]
async fn main() {
    // 1. Parse CLI arguments
    let args: Vec<String> = env::args().skip(1).collect();
    if args.is_empty() {
        eprintln!("Usage: mock-server <command> [args...]");
        std::process::exit(1);
    }
    let command_name = &args[0];
    let command_args = &args[1..];

    // 2. Setup Router
    let app = Router::new().route("/v1/chat/completions", post(chat_completions));

    // 3. Bind to Port 0 (Random Available Port)
    // The OS will automatically pick a free port, preventing conflicts.
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("Failed to bind to random port");
    let local_addr = listener.local_addr().unwrap();
    let actual_port = local_addr.port();

    println!(
        "[Mock Wrapper] Server bound to random port: {}",
        actual_port
    );

    // 4. Spawn the server task
    let server_handle = tokio::spawn(async move {
        if let Err(e) = axum::serve(listener, app).await {
            eprintln!("[Mock Wrapper] Server error: {}", e);
        }
    });

    // 5. Construct the base URL
    let base_url = format!("http://127.0.0.1:{}/v1", actual_port);
    println!("[Mock Wrapper] Injecting OPENAI_BASE_URL={}", base_url);

    // 6. Run the user's command with the new environment variable
    // Note: Command::new() inherits the parent's env vars by default.
    // We only need to explicitly add/overwrite the specific ones we care about.
    let mut child = Command::new(command_name)
        .args(command_args)
        .env("OPENAI_BASE_URL", base_url) // Inject the dynamic URL
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .kill_on_drop(true)
        .spawn()
        .expect("Failed to spawn command");

    // 7. Wait and cleanup
    let status = child.wait().await.expect("Failed to wait for command");
    server_handle.abort();

    let code = status.code().unwrap_or(1);
    println!("[Mock Wrapper] Command finished with exit code: {}", code);
    std::process::exit(code);
}

async fn chat_completions(
    Json(payload): Json<Value>,
) -> Sse<impl Stream<Item = Result<Event, Infallible>>> {
    println!("  \x1b[2m[LLM Call]\x1b[0m");
    let content = generate_response_text(&payload);

    let chunk_content = json!({
        "id": "chatcmpl-123",
        "object": "chat.completion.chunk",
        "created": 123456789,
        "model": "test-model",
        "choices": [{"delta": {"content": content}, "index": 0, "finish_reason": null}]
    })
    .to_string();

    let chunk_usage = json!({
        "id": "chatcmpl-123",
        "object": "chat.completion.chunk",
        "created": 123456789,
        "model": "test-model",
        "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    })
    .to_string();

    let stream = stream::iter(vec![
        Ok(Event::default().data(chunk_content)),
        Ok(Event::default().data(chunk_usage)),
        Ok(Event::default().data("[DONE]")),
    ]);

    Sse::new(stream).keep_alive(KeepAlive::default())
}

fn generate_response_text(body: &Value) -> String {
    let messages = body.get("messages").and_then(|v| v.as_array());
    let last_content = messages
        .and_then(|m| m.last())
        .and_then(|m| m.get("content"))
        .and_then(|c| c.as_str())
        .unwrap_or("");

    if last_content.contains("<critique>") {
        if last_content.contains("Rust script") {
            return "This is a Rust script.\n".to_string();
        }
        return "Refined response based on critique.\n".to_string();
    }

    let responses = [
        (
            "Your task is to create a commit message",
            "feat: add hello print to main.py\n",
        ),
        (
            "Output the complete markdown document",
            "### Recent Developments\n- Refactored `math.py` to use type hints.\n### Comprehensive Project Summary\nA collection of utilities including math functions.\n",
        ),
        (
            "Rename 'do' to 'add_numbers'",
            "File: math_utils.py\n<<<<<<< SEARCH\ndef do(a, b):\n    return a + b\n=======\ndef add_nums(a: int, b: int) -> int:\n    return a + b\n>>>>>>> REPLACE\n",
        ),
        (
            "add a comment",
            "File: hello.txt\n<<<<<<< SEARCH\nhello world\n=======\n# a comment\nhello world\n>>>>>>> REPLACE\n",
        ),
        (
            "Rename 'add' to 'sum_values' and add type hints",
            "File: math.py\n<<<<<<< SEARCH\ndef add(a, b): return a + b\n=======\ndef sum_values(a: int, b: int) -> int:\n    return a + b\n>>>>>>> REPLACE\n",
        ),
        ("Explain this code", "This code is a Python script.\n"),
        (
            "Propose Solution A",
            "Implementing Solution A using a loop.\n",
        ),
        (
            "Propose Solution B",
            "Implementing Solution B using recursion.\n",
        ),
        ("Say hello to World", "Hello, World! I am an addon.\n"),
        ("Turn 1", "Response 1\n"),
        ("Turn 2", "Response 2\n"),
        ("Turn 3", "Response 3\n"),
    ];

    for (trigger, text) in responses {
        if last_content.contains(trigger) {
            return text.to_string();
        }
    }

    "Standard mock response.".to_string()
}
