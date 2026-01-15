use aico::utils::setup_crypto_provider;
use clap::CommandFactory;
use clap::{Parser, Subcommand};
use clap_complete::ArgValueCompleter;
use clap_complete::CompletionCandidate;
use std::path::PathBuf;

// Use jemalloc on musl x86_64 for better performance
#[cfg(all(target_env = "musl", target_arch = "x86_64"))]
#[global_allocator]
static ALLOC: tikv_jemallocator::Jemalloc = tikv_jemallocator::Jemalloc;

#[derive(Parser)]
#[command(
    name = "aico",
    about = "Scriptable control over LLMs from the terminal",
    long_about = None,
    version = env!("CARGO_PKG_VERSION"),
    long_version = concat!(
        env!("CARGO_PKG_VERSION"),
        "\n\n",
        "Build Information:\n",
        "  Timestamp:         ", env!("VERGEN_BUILD_TIMESTAMP"), "\n",
        "  Target Triple:     ", env!("VERGEN_CARGO_TARGET_TRIPLE"), "\n",
        "\n",
        "Source Control:\n",
        "  Commit SHA:        ", env!("VERGEN_GIT_SHA"), "\n",
        "  Commit Timestamp:  ", env!("VERGEN_GIT_COMMIT_TIMESTAMP"), "\n",
        "  Branch:            ", env!("VERGEN_GIT_BRANCH"), "\n",
        "\n",
        "Compiler:\n",
        "  Rustc Version:     ", env!("VERGEN_RUSTC_SEMVER"), "\n",
        "  Rustc Channel:     ", env!("VERGEN_RUSTC_CHANNEL"), "\n",
        "  Host Triple:       ", env!("VERGEN_RUSTC_HOST_TRIPLE"), "\n"
    ),
    disable_help_subcommand = true
)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(clap::Args)]
struct LlmArgs {
    prompt: Option<String>,
    #[arg(short, long)]
    model: Option<String>,
    #[arg(long, default_value = "")]
    system_prompt: String,
    #[arg(long)]
    no_history: bool,
    #[arg(long)]
    passthrough: bool,
}

#[derive(Subcommand)]
enum Commands {
    /// Initialize a new session in the current directory.
    Init {
        #[arg(short, long, default_value = "openrouter/google/gemini-3-pro-preview")]
        model: String,
    },
    /// Add file(s) to the session context.
    Add {
        #[arg(required = true, value_hint = clap::ValueHint::FilePath)]
        file_paths: Vec<PathBuf>,
    },
    /// Remove file(s) from the session context.
    Drop {
        #[arg(required = true, add = ArgValueCompleter::new(session_completer))]
        file_paths: Vec<PathBuf>,
    },

    /// Exclude one or more message pairs from the context [default: last].
    ///
    /// This command performs a "soft delete" on the pairs at the given INDICES.
    /// The messages are not removed from the history, but are flagged to be
    /// ignored when building the context for the next prompt.
    Undo {
        #[arg(allow_hyphen_values = true)]
        indices: Vec<String>,
    },
    /// Re-include one or more message pairs in context.
    Redo {
        #[arg(allow_hyphen_values = true)]
        indices: Vec<String>,
    },
    /// Set the active window of the conversation history.
    ///
    /// Use `aico log` to see available pair indices.
    /// - `aico set-history 0` makes the full history active.
    /// - `aico set-history clear` clears the context for the next prompt.
    SetHistory {
        #[arg(allow_hyphen_values = true)]
        index: String,
    },
    /// Display the active conversation log.
    Log,

    /// Surgically splice a pair of global message IDs into history (plumbing)
    HistorySplice {
        user_id: usize,
        assistant_id: usize,
        #[arg(long)]
        at_index: usize,
    },

    /// Create a new session branch.
    ///
    /// Basic Usage:
    ///   aico session-fork my-feature
    ///   (Creates 'my-feature' and switches to it)
    ///
    /// Execute Command in Fork (Persistent):
    ///   aico session-fork my-feature -- aico gen "Experiment"
    ///   (Creates 'my-feature', runs command inside it, keeps it, does NOT switch active session)
    ///
    /// Execute Command in Ephemeral Fork:
    ///   aico session-fork my-temp-job --ephemeral -- aico prompt "Quick Check"
    ///   (Creates 'my-temp-job', runs command, deletes 'my-temp-job' on exit)
    SessionFork {
        new_name: String,
        #[arg(long)]
        until_pair: Option<usize>,
        #[arg(long)]
        ephemeral: bool,
        /// Command to execute in the forked session
        #[arg(last = true)]
        exec_args: Vec<String>,
    },

    /// Open a message in your default editor ($EDITOR) to make corrections.
    Edit {
        #[arg(default_value = "-1", allow_hyphen_values = true)]
        index: String,
        /// Edit the user prompt instead of the assistant response
        #[arg(long)]
        prompt: bool,
    },

    /// Output the last response or diff to stdout.
    ///
    /// By default, it shows the assistant response from the last pair.
    /// Use INDEX to select a specific pair (e.g., 0 for the first, -1 for the last).
    /// Use --prompt to see the user's prompt instead of the AI's response.
    /// Use --recompute to re-apply an AI's instructions to the current file state.
    Last {
        #[arg(default_value = "-1", allow_hyphen_values = true)]
        index: String,
        /// Show the user prompt instead of the assistant response
        #[arg(long)]
        prompt: bool,
        /// Print the verbatim LLM response
        #[arg(long)]
        verbatim: bool,
        /// Recompute diffs using current on-disk state
        #[arg(long)]
        recompute: bool,
        /// Output the message pair as JSON
        #[arg(long)]
        json: bool,
    },

    /// List available session views (branches) for a shared-history session.
    SessionList,

    /// Switch the active session pointer to another existing view (branch).
    SessionSwitch { name: String },

    /// Send a raw prompt to the AI.
    Prompt(LlmArgs),

    /// Create a new, empty session view (branch) and switch to it.
    SessionNew {
        name: String,
        #[arg(short, long)]
        model: Option<String>,
    },

    /// Show session status and token usage
    Status {
        #[arg(long)]
        json: bool,
    },

    /// Show instructions for enabling shell completions.
    Completions,

    /// Export the active chat history to stdout
    DumpHistory,

    /// Manage trusted projects for addon execution
    Trust {
        /// The project path to trust. Defaults to current directory.
        #[arg(value_hint = clap::ValueHint::DirPath)]
        path: Option<PathBuf>,
        /// Revoke trust for the specified path.
        #[arg(long, aliases = ["untrust"])]
        revoke: bool,
        /// List all trusted project paths.
        #[arg(long = "list")]
        show_list: bool,
    },

    /// Any other command is treated as an addon
    #[command(external_subcommand)]
    Addon(Vec<String>),

    // Prompt commands
    /// Have a conversation for planning and discussion.
    Ask(LlmArgs),
    /// Generate code modifications as a unified diff.
    #[command(alias = "generate-patch")]
    Gen(LlmArgs),
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    setup_crypto_provider();

    clap_complete::CompleteEnv::with_factory(Cli::command).complete();

    // Intercept help to show addons
    let args: Vec<String> = std::env::args().collect();
    if args.len() == 2 && (args[1] == "--help" || args[1] == "-h") {
        print_help_with_addons();
        return;
    }

    let cli = Cli::parse();

    let result = match cli.command {
        Commands::Init { model } => aico::commands::init::run(model),
        Commands::Add { file_paths } => aico::commands::add::run(file_paths),
        Commands::Drop { file_paths } => aico::commands::drop::run(file_paths),
        Commands::Undo { indices } => aico::commands::history_cmds::undo(indices),
        Commands::Redo { indices } => aico::commands::history_cmds::redo(indices),
        Commands::SetHistory { index } => aico::commands::history_cmds::set_history(index),
        Commands::Log => aico::commands::log::run(),
        Commands::HistorySplice {
            user_id,
            assistant_id,
            at_index,
        } => aico::commands::history_plumbing::run(user_id, assistant_id, at_index),
        Commands::SessionFork {
            new_name,
            until_pair,
            ephemeral,
            exec_args,
        } => aico::commands::session_fork::run(new_name, until_pair, ephemeral, exec_args),
        Commands::Edit { index, prompt } => aico::commands::edit::run(index, prompt),
        Commands::Last {
            index,
            prompt,
            verbatim,
            recompute,
            json,
        } => aico::commands::last::run(index, prompt, verbatim, recompute, json),
        Commands::Ask(ref args) | Commands::Gen(ref args) | Commands::Prompt(ref args) => {
            let mode = match &cli.command {
                Commands::Ask(_) => aico::models::Mode::Conversation,
                Commands::Gen(_) => aico::models::Mode::Diff,
                _ => aico::models::Mode::Raw,
            };
            aico::commands::llm_shared::run_llm_flow(
                args.prompt.clone(),
                args.model.clone(),
                args.system_prompt.clone(),
                args.no_history,
                args.passthrough,
                mode,
            )
            .await
        }
        Commands::SessionList => aico::commands::session_cmds::list(),
        Commands::SessionSwitch { name } => aico::commands::session_cmds::switch(name),
        Commands::SessionNew { name, model } => {
            aico::commands::session_cmds::new_session(name, model)
        }
        Commands::Status { json } => aico::commands::status::run(json).await,
        Commands::Completions => {
            println!(
                "Bash:\n\
                echo \"source <(COMPLETE=bash aico)\" >> ~/.bashrc\n\
                \n\
                Elvish:\n\
                echo \"eval (E:COMPLETE=elvish aico | slurp)\" >> ~/.elvish/rc.elv\n\
                \n\
                Fish:\n\
                echo \"COMPLETE=fish aico | source\" >> ~/.config/fish/config.fish\n\
                \n\
                Zsh:\n\
                echo \"source <(COMPLETE=zsh aico)\" >> ~/.zshrc\n"
            );
            Ok(())
        }
        Commands::DumpHistory => aico::commands::dump_history::run(),
        Commands::Trust {
            path,
            revoke,
            show_list,
        } => aico::commands::trust::run(path, revoke, show_list),
        Commands::Addon(args) => {
            let addon_name = &args[0];
            let addon_args = args[1..].to_vec();
            let addons = aico::addons::discover_addons();
            if let Some(addon) = addons.iter().find(|a| a.name == *addon_name) {
                aico::addons::execute_addon(addon, addon_args)
            } else {
                Err(aico::exceptions::AicoError::InvalidInput(format!(
                    "Unknown command or addon: {}",
                    addon_name
                )))
            }
        }
    };

    if let Err(e) = result {
        eprintln!("Error: {}", e);
        std::process::exit(1);
    }
}

fn print_help_with_addons() {
    let mut cmd = Cli::command();
    let _ = cmd.write_help(&mut std::io::stdout());

    let addons = aico::addons::discover_addons();
    if !addons.is_empty() {
        println!("\nAddons:");
        for addon in addons {
            println!("  {:<15} {}", addon.name, addon.help_text);
        }
    }
}

fn session_completer(current: &std::ffi::OsStr) -> Vec<CompletionCandidate> {
    if let Ok(session) = aico::session::Session::load_active() {
        let current_input = current.to_string_lossy();
        session
            .get_context_files()
            .into_iter()
            .filter(|f| f.starts_with(current_input.as_ref()))
            .map(CompletionCandidate::new)
            .collect()
    } else {
        vec![]
    }
}
