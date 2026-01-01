#[cfg(not(target_arch = "riscv64"))]
use rustls::crypto::aws_lc_rs;
#[cfg(target_arch = "riscv64")]
use rustls::crypto::ring;

pub fn setup_crypto_provider() {
    static DONE: std::sync::OnceLock<()> = std::sync::OnceLock::new();
    DONE.get_or_init(|| {
        if rustls::crypto::CryptoProvider::get_default().is_none() {
            #[cfg(target_arch = "riscv64")]
            let provider = ring::default_provider();

            #[cfg(not(target_arch = "riscv64"))]
            let provider = aws_lc_rs::default_provider();

            let _ = provider.install_default();
        }
    });
}

pub fn setup_http_client() -> reqwest::Client {
    setup_crypto_provider();
    reqwest::Client::new()
}
