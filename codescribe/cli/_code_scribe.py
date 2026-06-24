"""Top-level Click group for CodeScribe."""

# Standard libraries
from importlib import metadata

# Feature libraries
import click


@click.group(name="code-scribe", invoke_without_command=True)
@click.pass_context
@click.option("--version", "-v", is_flag=True)
def code_scribe(ctx: click.Context, version: bool) -> None:
    """
    \b
    Software development tool for code conversion and generation
    for scientific computing applications
    """
    if version:
        click.echo(metadata.version("CodeScribe"))
        return

    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
