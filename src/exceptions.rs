use thiserror::Error;

#[derive(Error, Debug)]
pub enum AicoError {
    #[error("Configuration error: {0}")]
    Configuration(String),

    #[error("Session error: {0}")]
    Session(String),

    #[error("Session integrity error: {0}")]
    SessionIntegrity(String),

    #[error("Invalid input: {0}")]
    InvalidInput(String),

    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),

    #[error("LLM Provider error: {0}")]
    Provider(String),
}
