# pyright: standard

import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class MockLLMHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        _ = self.wfile.write(b"OK")

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(content_length))

        # Determine response based on the last user message
        messages = body.get("messages", [])
        last_content = messages[-1].get("content", "") if messages else ""

        responses = {
            "Output the complete markdown document": (
                "### Recent Developments\n"
                "- Refactored `math_utils.py` to use type hints.\n"
                "### Comprehensive Project Summary\n"
                "A collection of utilities including math functions.\n"
            ),
            "Rename 'do' to 'add_numbers'": (
                "File: math_utils.py\n"
                "<<<<<<< SEARCH\n"
                "def do(a, b):\n"
                "    return a + b\n"
                "=======\n"
                "def add_nums(a: int, b: int) -> int:\n"
                "    return a + b\n"
                ">>>>>>> REPLACE\n"
            ),
            "add a comment": (
                "File: hello.txt\n<<<<<<< SEARCH\nhello world\n=======\n# a comment\nhello world\n>>>>>>> REPLACE\n"
            ),
            "Explain this code": "This code is a Python script.\n",
        }

        response_text = "Standard mock response."
        for trigger, text in responses.items():
            if trigger in last_content:
                response_text = text
                break

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        # Stream chunks (one for content, one for usage)
        chunk = {
            "id": "chatcmpl-123",
            "object": "chat.completion.chunk",
            "created": 123456789,
            "model": "test-model",
            "choices": [{"delta": {"content": response_text}, "index": 0, "finish_reason": None}],
        }
        _ = self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())

        usage_chunk = {
            "id": "chatcmpl-123",
            "object": "chat.completion.chunk",
            "created": 123456789,
            "model": "test-model",
            "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        _ = self.wfile.write(f"data: {json.dumps(usage_chunk)}\n\n".encode())
        _ = self.wfile.write(b"data: [DONE]\n\n")


def run():
    server_address = ("", 5005)
    httpd = HTTPServer(server_address, MockLLMHandler)
    httpd.serve_forever()


if __name__ == "__main__":
    run()
