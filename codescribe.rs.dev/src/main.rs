mod commands;

use clap::{CommandFactory, Parser};
use commands::{index, draft, translate, generate, update, inspect, format};

#[derive(Parser)]
#[command(name = "scribe-rs")]
#[command(version = "0.1.0")]
#[command(about = "A Rust application inspired by the reference Python CLI")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(clap::Subcommand)]
enum Commands {
    Index { root_dir: String },
    Draft { fortran_files: Vec<String> },
    Translate {
        fortran_files: Vec<String>,
        seed_prompt: String,
        model: Option<String>,
    },
    Generate {
        seed_prompt: String,
        model: Option<String>,
        reference_existing: Vec<String>,
    },
    Update {
        filelist: Vec<String>,
        seed_prompt: String,
        model: String,
        reference_existing: Vec<String>,
    },
    Inspect {
        fortran_files: Vec<String>,
        query_prompt: String,
        model: Option<String>,
    },
    Format { seed_prompt_list: Vec<String> },
}

fn main() {
    let cli = Cli::parse();

    match cli.command {
        Commands::Index { root_dir } => index(root_dir),
        Commands::Draft { fortran_files } => draft(fortran_files),
        Commands::Translate {
            fortran_files,
            seed_prompt,
            model,
        } => translate(fortran_files, seed_prompt, model),
        Commands::Generate {
            seed_prompt,
            model,
            reference_existing,
        } => generate(seed_prompt, model, reference_existing),
        Commands::Update {
            filelist,
            seed_prompt,
            model,
            reference_existing,
        } => update(filelist, seed_prompt, model, reference_existing),
        Commands::Inspect {
            fortran_files,
            query_prompt,
            model,
        } => inspect(fortran_files, query_prompt, model),
        Commands::Format { seed_prompt_list } => format(seed_prompt_list),
    }
}
