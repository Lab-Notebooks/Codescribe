import re
import os
import yaml

from code_scribe import lib


def extract_fortran_info(filepath):
    """Extracts module and subroutine/function names from a Fortran file."""
    info = {"modules": [], "subroutines": [], "functions": []}

    with open(filepath, "r") as file:
        for line in file:
            line = line.strip()
            line = line.lower()
            # Check for module declaration
            if line.startswith("module "):
                info["modules"].append(line.split()[1])  # Capture module name
            # Check for subroutine declaration
            elif line.startswith("subroutine "):
                # Extract the subroutine name (first word after "subroutine")
                match = re.match(r"subroutine\s+(\w+)", line)
                if match:
                    info["subroutines"].append(
                        match.group(1)
                    )  # Capture subroutine name
            # Check for function declaration
            elif line.startswith("function "):
                # Extract the function name (first word after "function")
                match = re.match(r"function\s+(\w+)", line)
                if match:
                    info["functions"].append(match.group(1))  # Capture function name

    return info


def create_scribe_yaml(root_directory):
    """Traverses the directory and creates scribe.yaml files for Fortran files."""
    for dirpath, _, filenames in os.walk(root_directory):
        scribe_data = {
            "root": root_directory,
            "directory": dirpath.replace(root_directory + os.sep, ""),
            "files": {},
        }

        for filename in filenames:
            if filename.endswith((".f", ".f90", ".F90")):
                filepath = os.path.join(dirpath, filename)
                fortran_info = extract_fortran_info(filepath)

                # Add extracted information to the scribe_data
                scribe_data["files"][filename] = fortran_info

        # Only write to scribe.yaml if there are Fortran files in the directory
        if scribe_data["files"]:
            yaml_path = os.path.join(dirpath, "scribe.yaml")
            with open(yaml_path, "w") as yaml_file:
                yaml.dump(scribe_data, yaml_file, default_flow_style=False)


def load_scribe_yaml(file_path):
    """Load the content of a scribe.yaml file."""
    with open(file_path, "r") as yaml_file:
        return yaml.safe_load(yaml_file)


def create_file_indexes():
    """
    Create a combined index for files, subroutines, functions,
    and modules from all scribe.yaml files in the directory tree.
    """

    # Start with the current working directory
    cwd = os.getcwd()

    # Load the scribe.yaml from the current directory
    yaml_path = os.path.join(cwd, "scribe.yaml")
    if not os.path.exists(yaml_path):
        raise FileNotFoundError(f"No scribe.yaml found in {cwd}")

    scribe_data = load_scribe_yaml(yaml_path)

    # Get the root directory from the scribe.yaml file
    root_directory = scribe_data.get("root", None)
    if not root_directory:
        raise ValueError(f"No 'root' entry found in {yaml_path}")

    file_index = {}

    # Traverse the directory tree starting from the root directory
    for dirpath, _, filenames in os.walk(root_directory):
        for filename in filenames:
            if filename == "scribe.yaml":
                filepath = os.path.join(dirpath, filename)
                scribe_data = load_scribe_yaml(filepath)

                # Update combined index with data from the current scribe.yaml
                for file, info in scribe_data["files"].items():
                    file_path = os.path.join(dirpath, file)  # Full file path

                    # Extract modules, subroutines, and functions
                    modules = info.get("modules", [])
                    subroutines = info.get("subroutines", [])
                    functions = info.get("functions", [])

                    # Add modules to combined index
                    for mod in modules:
                        file_index[mod] = file_path
                    # Add subroutines to combined index
                    for sub in subroutines:
                        file_index[sub] = file_path
                    # Add functions to combined index
                    for func in functions:
                        file_index[func] = file_path

    return file_index


def filter_file_indexes(sfile, file_index, scalar_functions=[]):
    """
    Extract modules, subroutines, and variable declarations used in the given Fortran source file,
    and return a subset of the file_index that corresponds to these.

    Args:
        sfile (str): The Fortran source file to analyze.
        file_index (dict): The complete item index list to filter from.

    Returns:
        dict: A subset of the file_index containing only the used modules, subroutines, and variables.
    """
    used_modules = set()
    used_subroutines = set()

    # Open and read the source file
    try:
        with open(sfile, "r") as source:
            for line in source:
                stripped_line = line.strip()

                # Check for 'use' statement to capture modules
                module_match = re.match(
                    r"^\s*use\s+(\w+)", stripped_line, re.IGNORECASE
                )
                if module_match:
                    used_modules.add(module_match.group(1).lower())

                # Check for 'call' statement to capture subroutines
                subroutine_match = re.match(
                    r"^\s*call\s+(\w+)", stripped_line, re.IGNORECASE
                )
                if subroutine_match:
                    used_subroutines.add(subroutine_match.group(1).lower())

    except FileNotFoundError:
        print(f"Error: The file '{sfile}' was not found.")
        return {}
    except Exception as e:
        print(f"An error occurred while reading the file: {e}")
        return {}

    # Filter the file_index to return only the modules, subroutines, and variables used in this file
    filtered_file_index = {
        name: path
        for name, path in file_index.items()
        if name.lower() in used_modules
        or name.lower() in used_subroutines
        or name.lower() in [sfunc.lower() for sfunc in scalar_functions]
    }

    return filtered_file_index


def isolate_scalar_functions(sfile):
    """
    Isolate variables that are declared as scalars but used as functions in the given Fortran source file.

    Args:
        sfile (str): The Fortran source file to analyze.

    Returns:
        set: A set of scalar variables that are used as functions.
    """
    scalar_variables = set()
    function_calls = set()
    defined_functions = set()

    # Open and read the source file
    with open(sfile, "r") as source:
        for line in source:
            stripped_line = line.strip()

            # Check for function definitions
            func_decl_match = re.match(
                r"^\s*function\s+(\w+)", stripped_line, re.IGNORECASE
            )
            if func_decl_match:
                defined_functions.add(func_decl_match.group(1))

            # Check for scalar variable declarations
            var_decl_match = re.match(
                r"^\s*(integer|real|double|complex\(dp\)|bool|character)\s*::\s*([^;]*)",
                stripped_line,
                re.IGNORECASE,
            )
            if var_decl_match:
                # Extract variable names
                variables_part = var_decl_match.group(2)
                variable_names = [
                    var.strip().split("(")[0] for var in variables_part.split(",")
                ]
                scalar_variables.update(name for name in variable_names)

            # Check for function calls
            function_call_match = re.findall(r"\b(\w+)\s*\(", stripped_line)
            if function_call_match:
                function_calls.update(name for name in function_call_match)

    # Identify scalar variables that are used as functions, ignoring defined functions
    scalar_used_as_functions = (
        scalar_variables.intersection(function_calls) - defined_functions
    )

    return scalar_used_as_functions


def query_construct(name, file_index):
    """Query the file path of a module, subroutine, or function."""

    # Find all matches for the given name
    matches = [
        file_path for construct, file_path in file_index.items() if name == construct
    ]

    return matches if matches else None


def extract_fortran_meta(sfile):
    """Extract function, subroutine, module names, variables, and argument lists from Fortran source."""
    meta_info = []
    current_construct = None
    variables_declared = []
    argument_list = []

    with open(sfile, "r") as source:
        for line in source.readlines():
            stripped_line = line.strip()

            # Check for subroutine, module, or function start
            construct_match = re.match(
                r"^\s*(subroutine|function|module)\s+(\w+)",
                stripped_line,
                re.IGNORECASE,
            )
            if construct_match:
                # If we were already inside a construct, save the previous one
                if current_construct:
                    meta_info.append(
                        {
                            "name": current_construct["name"],
                            "type": current_construct["type"],
                            "variables_declared": variables_declared,
                            "argument_list": argument_list,
                        }
                    )

                # Start a new construct
                current_construct = {
                    "name": construct_match.group(2),
                    "type": construct_match.group(1).lower(),
                }
                variables_declared = []  # Reset variables declared
                argument_list = []  # Reset argument list

                # If it's a function or subroutine, look for the argument list
                if current_construct["type"] in ["function", "subroutine"]:
                    args_match = re.search(r"\((.*?)\)", stripped_line)
                    if args_match:
                        arguments = [
                            arg.strip() for arg in args_match.group(1).split(",")
                        ]
                        argument_list.extend(arguments)

            # Extract variable declarations (e.g., integer, real, character, etc.)
            var_match = re.match(
                r"^\s*(integer|real|double\s*precision|character|logical)\s+([\w\s,]*)",
                stripped_line,
                re.IGNORECASE,
            )
            if var_match:
                variables = [var.strip() for var in var_match.group(2).split(",")]
                variables_declared.extend(variables)

        # Save the last construct if it exists
        if current_construct:
            meta_info.append(
                {
                    "name": current_construct["name"],
                    "type": current_construct["type"],
                    "variables_declared": variables_declared,
                    "argument_list": argument_list,
                }
            )

    return meta_info


def annotate_fortran_file(sfile, file_index):
    """
    Annotates a Fortran file, converts types to C++ equivalents,
    replaces use statements inline with namespaces, and adds headers.
    """

    scalar_functions = lib.isolate_scalar_functions(sfile)

    filtered_file_index = {}
    if file_index:
        filtered_file_index.update(
            lib.filter_file_indexes(sfile, file_index, scalar_functions)
        )

    scribe_filename = os.path.splitext(sfile)[0] + ".scribe"

    if os.path.isfile(scribe_filename):
        return f"Skipping! File exists {scribe_filename}..."

    header_includes = set(
        ("#include <cmath>", "#include <complex>")
    )  # Keep track of headers to avoid duplicates
    content_lines = []  # Store lines of modified content
    prompt_lines = []

    prompt_lines.append(
        'scribe-prompt: Write corressponding extern "C" with _wrapper added to the name. '
        + "Refer to the template for treating Farray and scalars"
    )
    prompt_lines.append(
        "scribe-prompt: When variables are used as function. They should be treated as "
        + "external or statement functions. "
        + "External functions are available in header files"
    )
    prompt_lines.append(
        "scribe-prompt: Statement functions should be converted to equivalent lambda functions in C++. "
        + "Include [&] in capture clause to use variables by reference"
    )

    for construct in scalar_functions:
        if construct.lower() in filtered_file_index.keys():
            prompt_lines.append(f"scribe-prompt: {construct} is an external function")

    # for construct in scalar_functions:
    #    if construct not in filtered_file_index.keys():
    #        prompt_lines.append(f"scribe-prompt: {construct} is an array or statement function")

    with open(sfile, "r") as source:
        source_code = source.readlines()

        for line in source_code:
            stripped_line = line.strip()

            # Skip lines that are comments starting with 'c', '!!', or '!'
            if stripped_line.lower().startswith(("c", "!!", "!")) and (
                not stripped_line.lower().startswith(("complex"))
            ):
                continue

            # Replace 'use <module_name>' with '#include' and 'using namespace'
            use_match = re.match(r"\buse\s+(\w+)", stripped_line, flags=re.IGNORECASE)
            if use_match:
                module_name = use_match.group(1)

                # Add header include globally but only once
                header_includes.add(f"#include <{module_name}.hpp>")

                # Replace 'use' with 'using namespace' inline
                content_lines.append(f"using namespace {module_name};\n")
                continue

            # Remove implict none statement
            line = re.sub(r"implicit none", "", line)

            # Handle variable declarations and conversions
            line = re.sub(r"\binteger\b\s*", "int", line, flags=re.IGNORECASE)
            line = re.sub(
                r"\breal\s*(\(\s*kind\s*=\s*\w+\s*\)|\(\s*\w+\s*\)|)?\s*",
                "double",
                line,
                flags=re.IGNORECASE,
            )
            line = re.sub(
                r"\bcomplex\s*\(\s*dp\s*\)\s*",
                "complex<double> ",
                line,
                flags=re.IGNORECASE,
            )
            line = re.sub(
                r"\bcomplex\s*\(\s*integer\s*\)\s*",
                "complex<int> ",
                line,
                flags=re.IGNORECASE,
            )
            line = re.sub(
                r"\bcomplex\s*\(\s*logical\s*\)\s*",
                "complex<bool> ",
                line,
                flags=re.IGNORECASE,
            )
            line = re.sub(r"(?<!std::)\s*::", "", line)

            # Handle complex types in variable declarations, ensuring dimensionality is handled
            line = re.sub(
                r"\bcomplex<([^>]+)>\s*(\w+)\s*\((.*?)\)\s*",
                r"FArray<std::complex<\1>> \2(\3)",
                line,
            )

            line = re.sub(
                r"\b(real|double|int|bool|complex<[^>]+>)\s*,?\s*dimension\s*\((.*?)\)\s*(\w+)\s*;",
                r"FArray<\1> \3(\2)",
                line,
                flags=re.IGNORECASE,
            )

            line = re.sub(
                r"\b(real|double|int|bool|complex<[^>]+>)\s*(\w+)\s*\((.*?)\)\s*;",
                r"FArray<\1> \2(\3)",
                line,
                flags=re.IGNORECASE,
            )

            # Treat line continuation characters. Replace them with equivalent syntax in C++
            line = re.sub(r"^\s*&", r"\\", line)
            line = re.sub(r"\s*&\s*$", r" \\", line)

            # Substitution x**y with pow(x,y)
            line = re.sub(r"(\w+)\s*\*\*\s*(\d+)", r"pow(\1,\2)", line)

            # Add a semicolon at the end of variable declarations
            # if re.match(r"^(int|double|complex<[^>]+>)\s", line.strip()):
            #    line = line.strip() + ";"

            # Append the modified line to content_lines
            content_lines.append(line.strip() + "\n")

    # Write the output to the .scribe file
    with open(scribe_filename, "w") as scribe_file:

        scribe_file.write("\n".join(prompt_lines))
        scribe_file.write("\n\n")

        # First, write all the includes at the top
        if header_includes:
            scribe_file.write("\n".join(sorted(header_includes)) + "\n\n")

        # Then, write the rest of the modified content
        scribe_file.writelines(content_lines)

    return f"Generated draft file for LLM consumption {scribe_filename}"


def create_src_mapping(filelist):
    """
    Build directory tree from neucol source code.

    Arguments
    ---------
    dest : String value of destination directory
    """
    fsource = []
    csource = []
    finterface = []
    cdraft = []
    promptfile = []

    for sfile in filelist:
        fsource.append(sfile)
        csource.append(os.path.splitext(sfile)[0] + ".cpp")
        finterface.append(os.path.splitext(sfile)[0] + "_fi.f90")
        cdraft.append(os.path.splitext(sfile)[0] + ".scribe")
        promptfile.append(os.path.splitext(sfile)[0] + ".json")

    return fsource, csource, finterface, cdraft, promptfile
