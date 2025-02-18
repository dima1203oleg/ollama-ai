#!/usr/bin/env python3
"""
Dependencies checker script
Save as scripts/check_dependencies.py
"""

import sys
import pkg_resources
import platform
import requests
from rich.console import Console
from rich.table import Table

console = Console()

def check_python_version():
    version = sys.version_info
    return version.major == 3 and version.minor >= 9

def check_packages():
    required = {}
    for req in pkg_resources.parse_requirements(open('requirements.txt')):
        required[req.key] = str(req.specifier).replace('==', '')
    
    installed = {pkg.key: pkg.version for pkg in pkg_resources.working_set}
    
    missing = []
    outdated = []
    
    for package, version in required.items():
        if package not in installed:
            missing.append(f"{package}=={version}")
        elif installed[package] != version:
            outdated.append(f"{package} (installed: {installed[package]}, required: {version})")
    
    return missing, outdated

def check_ollama():
    try:
        response = requests.get("http://localhost:11434/api/tags")
        return response.status_code == 200
    except:
        return False

def check_opensearch():
    try:
        response = requests.get("http://localhost:9200")
        return response.status_code == 200
    except:
        return False

def main():
    table = Table(title="Dependencies Check")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Details", style="yellow")

    # Check Python version
    python_ok = check_python_version()
    table.add_row(
        "Python Version",
        "✓" if python_ok else "✗",
        f"{platform.python_version()} ({'OK' if python_ok else 'Need 3.9+'})"
    )

    # Check packages
    missing, outdated = check_packages()
    table.add_row(
        "Python Packages",
        "✓" if not (missing or outdated) else "✗",
        f"Missing: {', '.join(missing) if missing else 'None'}\nOutdated: {', '.join(outdated) if outdated else 'None'}"
    )

    # Check Ollama
    ollama_ok = check_ollama()
    table.add_row(
        "Ollama",
        "✓" if ollama_ok else "✗",
        "Running" if ollama_ok else "Not available"
    )

    # Check OpenSearch
    opensearch_ok = check_opensearch()
    table.add_row(
        "OpenSearch",
        "✓" if opensearch_ok else "✗",
        "Running" if opensearch_ok else "Not available"
    )

    console.print(table)

    if not all([python_ok, not missing, not outdated, ollama_ok, opensearch_ok]):
        console.print("\n[red]Some dependencies are missing or services are not running![/red]")
        sys.exit(1)
    else:
        console.print("\n[green]All dependencies are satisfied and services are running![/green]")

if __name__ == "__main__":
    main()