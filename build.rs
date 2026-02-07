use anyhow::Result;
use vergen_gitcl::{BuildBuilder, CargoBuilder, Emitter, GitclBuilder, RustcBuilder};

fn main() -> Result<(), anyhow::Error> {
    vergen()?;
    Ok(())
}

fn vergen() -> Result<(), anyhow::Error> {
    let build = BuildBuilder::default().build_timestamp(true).build()?;
    let rustc = RustcBuilder::default()
        .semver(true)
        .channel(true)
        .host_triple(true)
        .build()?;
    let cargo = CargoBuilder::default().target_triple(true).build()?;
    let mut emitter = Emitter::default();
    emitter
        .add_instructions(&build)?
        .add_instructions(&cargo)?
        .add_instructions(&rustc)?;

    // If VERGEN_GIT_SHA is passed (e.g. from Nix), skip git detection
    if std::env::var("VERGEN_GIT_SHA").is_ok() {
        // We assume timestamp is also passed if SHA is passed
    } else {
        let gitcl = GitclBuilder::default()
            .commit_timestamp(true)
            .sha(true)
            .build()?;
        emitter.add_instructions(&gitcl)?;
    }

    emitter.emit()?;

    Ok(())
}
