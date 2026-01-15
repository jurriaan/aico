#[cfg(not(target_arch = "riscv64"))]
use rustls::crypto::aws_lc_rs;
#[cfg(target_arch = "riscv64")]
use rustls::crypto::ring;
use std::{sync::LazyLock, time::Duration};

pub fn setup_crypto_provider() {
    static DONE: LazyLock<()> = LazyLock::new(|| {
        if rustls::crypto::CryptoProvider::get_default().is_none() {
            #[cfg(target_arch = "riscv64")]
            let provider = ring::default_provider();

            #[cfg(not(target_arch = "riscv64"))]
            let provider = aws_lc_rs::default_provider();

            let _ = provider.install_default();
        }
    });
    *DONE;
}

pub fn setup_http_client() -> reqwest::Client {
    setup_crypto_provider();

    reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(10))
        .pool_idle_timeout(Duration::from_secs(90))
        .tcp_keepalive(Duration::from_secs(30))
        .build()
        .unwrap_or_else(|_| reqwest::Client::new())
}
