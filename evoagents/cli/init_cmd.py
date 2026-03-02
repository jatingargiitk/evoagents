"""evoagents init — scaffold a new EvoAgents project."""

from __future__ import annotations

import shutil
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(invoke_without_command=True)
console = Console()


@app.callback(invoke_without_command=True)
def init(
    preset: str = typer.Option("research", help="Preset template: research | demo | blank"),
    directory: str = typer.Argument(".", help="Target directory."),
) -> None:
    """Initialize a new EvoAgents project with skill scaffolding."""
    target = Path(directory).resolve()
    target.mkdir(parents=True, exist_ok=True)

    preset_dir = Path(__file__).parent.parent / "presets" / preset
    if not preset_dir.exists():
        console.print(f"[red]Unknown preset: {preset}[/red]")
        raise typer.Exit(1)

    _copy_preset(preset_dir, target)

    selfheal = target / ".selfheal"
    selfheal.mkdir(exist_ok=True)

    console.print(f"\n[bold green]✓[/bold green] Initialized EvoAgents project at [cyan]{target}[/cyan]")
    console.print(f"  Preset: [yellow]{preset}[/yellow]")
    console.print()
    console.print("  Next steps:")
    console.print("    1. Set your API key:  [dim]export OPENAI_API_KEY=sk-...[/dim]")
    console.print('    2. Run the pipeline:  [dim]evoagents run "your query here"[/dim]')
    console.print("    3. Inspect results:   [dim]evoagents trace last[/dim]")
    console.print("    4. Auto-improve:      [dim]evoagents autofix last[/dim]")


def _copy_preset(src: Path, dst: Path) -> None:
    """Recursively copy preset files, skipping __pycache__."""
    for item in src.rglob("*"):
        if "__pycache__" in item.parts:
            continue
        rel = item.relative_to(src)
        dest_path = dst / rel
        if item.is_dir():
            dest_path.mkdir(parents=True, exist_ok=True)
        else:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            if not dest_path.exists():
                shutil.copy2(item, dest_path)
