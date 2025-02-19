#!/usr/bin/env python3
"""
Dependencies checker script
Save as scripts/check_dependencies.py
"""

import sys
from importlib.metadata import version, distributions
import platform
import requests
from rich.console import Console
from rich.table import Table

console = Console()

def check_python_version():
    version_info = sys.version_info
    return version_info.major == 3 and version_info.minor >= 9

def check_packages():
    required = {}
    with open('requirements.txt') as f:
        for line in f:
            # Пропускаем пустые строки и комментарии
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # Очищаем комментарии в конце строки
            if '#' in line:
                line = line.split('#')[0].strip()
            
            # Парсим имя пакета и версию
            parts = line.split('>=') if '>=' in line else line.split('==')
            if len(parts) == 2:
                package = parts[0].strip().replace('-', '_').lower()
                version = parts[1].strip()
                required[package] = {
                    'version': version,
                    'operator': '>=' if '>=' in line else '=='
                }

    # Получаем установленные пакеты
    installed = {
        dist.metadata['Name'].lower().replace('-', '_'): dist.version 
        for dist in distributions()
    }

    # Проверяем версии
    status = []
    for package, req in required.items():
        installed_version = installed.get(package, None)
        if not installed_version:
            status.append((package, False, f"Missing (required: {req['version']})"))
        else:
            status.append((
                package,
                True,
                f"Installed: {installed_version} (required: {req['operator']}{req['version']})"
            ))
    
    return status

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
    try:
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
        package_status = check_packages()
        for package, is_ok, details in package_status:
            table.add_row(
                package,
                "✓" if is_ok else "✗",
                details
            )

        # Check services
        ollama_ok = check_ollama()
        table.add_row(
            "Ollama",
            "✓" if ollama_ok else "✗",
            "Running" if ollama_ok else "Not available"
        )

        opensearch_ok = check_opensearch()
        table.add_row(
            "OpenSearch",
            "✓" if opensearch_ok else "✗",
            "Running" if opensearch_ok else "Not available"
        )

        # Ensure table is actually displayed
        console.print("\n")
        console.print(table)
        console.print("\n")

        # Add flush to ensure output is displayed
        sys.stdout.flush()

        # Check overall status
        all_ok = python_ok and all(ok for _, ok, _ in package_status) and ollama_ok and opensearch_ok
        if not all_ok:
            console.print("[red]Some dependencies are missing or services are not running![/red]")
            sys.exit(1)
        else:
            console.print("[green]All dependencies are satisfied and services are running![/green]")
            
    except Exception as e:
        print(f"Error during dependency check: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()