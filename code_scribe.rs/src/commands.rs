pub fn index(root_dir: String) {
    println!("Indexing Fortran files in directory: {}", root_dir);
}

pub fn draft(fortran_files: Vec<String>) {
    println!("Drafting conversion for Fortran files: {:?}", fortran_files);
}

pub fn translate(
    fortran_files: Vec<String>,
    seed_prompt: String,
    model: Option<String>,
    save_prompts: bool,
) {
    println!(
        "Translating Fortran files: {:?} with seed prompt: {}, model: {:?}, save prompts: {}",
        fortran_files, seed_prompt, model, save_prompts
    );
}

pub fn generate(
    seed_prompt: String,
    model: Option<String>,
    save_prompts: bool,
    reference_existing: Vec<String>,
) {
    println!(
        "Generating code with seed prompt: {}, model: {:?}, save prompts: {}, reference files: {:?}",
        seed_prompt, model, save_prompts, reference_existing
    );
}

pub fn update(
    filelist: Vec<String>,
    seed_prompt: String,
    model: String,
    reference_existing: Vec<String>,
) {
    println!(
        "Updating files: {:?} with seed prompt: {}, model: {}, reference files: {:?}",
        filelist, seed_prompt, model, reference_existing
    );
}

pub fn inspect(
    fortran_files: Vec<String>,
    query_prompt: String,
    model: Option<String>,
    save_prompts: bool,
) {
    println!(
        "Inspecting Fortran files: {:?} with query prompt: {}, model: {:?}, save prompts: {}",
        fortran_files, query_prompt, model, save_prompts
    );
}

pub fn format(seed_prompt_list: Vec<String>) {
    println!("Formatting seed prompt files: {:?}", seed_prompt_list);
}
