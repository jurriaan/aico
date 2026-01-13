use aico::ui::live_display::LiveDisplay;

#[test]
fn test_update_status_unicode_truncation_no_panic() {
    // Tests that truncation for status lines respects character boundaries.
    let mut ld = LiveDisplay::new(20);
    // width=20, limit=10. "123456789" (9 bytes) + "✨" (3 bytes).
    // A byte-slice at index 10 would hit the middle of the sparkle and panic.
    let input = "123456789✨";
    ld.update_status(input);
}
