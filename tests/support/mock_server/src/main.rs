use axum::{
    Router,
    extract::Json,
    response::sse::{Event, KeepAlive, Sse},
    routing::post,
};
use futures::stream::{self, Stream};
use serde_json::{Value, json};
use std::convert::Infallible;
use tokio::net::TcpListener;

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let app = Router::new().route("/v1/chat/completions", post(chat_completions));
    let listener = TcpListener::bind("127.0.0.1:5005").await.unwrap();
    println!(
        "Mock LLM Server listening on {}",
        listener.local_addr().unwrap()
    );
    axum::serve(listener, app).await.unwrap();
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
    ];

    for (trigger, text) in responses {
        if last_content.contains(trigger) {
            return text.to_string();
        }
    }

    "Standard mock response.".to_string()
}
