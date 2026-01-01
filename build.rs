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
    let gitcl = GitclBuilder::default()
        .commit_timestamp(true)
        .branch(true)
        .sha(true)
        .build()?;

    Emitter::default()
        .add_instructions(&build)?
        .add_instructions(&gitcl)?
        .add_instructions(&cargo)?
        .add_instructions(&rustc)?
        .emit()?;

    Ok(())
}
