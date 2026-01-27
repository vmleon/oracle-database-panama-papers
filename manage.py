#!/usr/bin/env python3
"""
Panama Papers PoC Management CLI

Orchestrates deployment of Oracle Database infrastructure, schema,
and data loading for the Panama Papers analysis demonstration.

Usage:
    ./manage.py cloud setup      # Configure OCI credentials
    ./manage.py cloud deploy     # Deploy schema via Liquibase
    ./manage.py data download    # Download ICIJ CSV files
    ./manage.py data ingest      # Load data into Oracle
    ./manage.py mcp setup        # Configure SQLcl MCP connections
    ./manage.py full clean       # Complete cleanup
"""

import argparse
import configparser
import json
import os
import secrets
import shutil
import string
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Optional

import requests
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt, Confirm
from rich.table import Table

try:
    import questionary
except ImportError:
    questionary = None

try:
    from jinja2 import Template
except ImportError:
    Template = None

try:
    from dotenv import load_dotenv, set_key
except ImportError:
    load_dotenv = None
    set_key = None

# Initialize Rich console for pretty output
console = Console()

# Project paths
PROJECT_ROOT = Path(__file__).parent.resolve()
DEPLOY_DIR = PROJECT_ROOT / "deploy" / "terraform"
DATABASE_DIR = PROJECT_ROOT / "database"
DATA_DIR = PROJECT_ROOT / "data"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
WALLET_DIR = PROJECT_ROOT / ".wallet"
ENV_FILE = PROJECT_ROOT / ".env"


# ============================================================================
# ENVIRONMENT CONFIGURATION (using .env file)
# ============================================================================

def env_load():
    """Load environment variables from .env file."""
    if load_dotenv and ENV_FILE.exists():
        load_dotenv(ENV_FILE)


def env_save(key: str, value: str):
    """Save a key to .env file."""
    if not set_key:
        console.print("[yellow]Warning: python-dotenv not installed, cannot save to .env[/yellow]")
        return
    if not ENV_FILE.exists():
        ENV_FILE.touch()
    set_key(str(ENV_FILE), key, value)


def env_get(key: str, default: str = None) -> str:
    """Get environment variable (loads .env first)."""
    env_load()
    return os.getenv(key, default)


def run_command(cmd: list, cwd: Optional[Path] = None,
                capture: bool = False) -> subprocess.CompletedProcess:
    """Run a shell command with error handling."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=capture,
            text=True,
            check=True
        )
        return result
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Command failed: {' '.join(cmd)}[/red]")
        if e.stderr:
            console.print(f"[red]{e.stderr}[/red]")
        raise


# ============================================================================
# OCI HELPERS
# ============================================================================

def get_oci_profiles():
    """Get list of available OCI profiles from ~/.oci/config."""
    config_path = Path.home() / ".oci" / "config"
    if not config_path.exists():
        return ["DEFAULT"]

    config = configparser.ConfigParser()
    config.read(config_path)

    profiles = config.sections()
    if config.defaults():
        profiles.insert(0, "DEFAULT")

    return profiles if profiles else ["DEFAULT"]


def read_oci_config(profile="DEFAULT"):
    """Read OCI config for specified profile."""
    config_path = Path.home() / ".oci" / "config"
    if not config_path.exists():
        return {}

    config = configparser.ConfigParser()
    config.read(config_path)

    if profile == "DEFAULT":
        return dict(config.defaults())
    elif profile in config:
        result = dict(config.defaults())
        result.update(dict(config[profile]))
        return result
    return {}


def select_profile():
    """Interactive OCI profile selection."""
    profiles = get_oci_profiles()

    if questionary:
        return questionary.select(
            "Select OCI Profile:",
            choices=profiles,
            default="DEFAULT" if "DEFAULT" in profiles else profiles[0]
        ).ask()
    else:
        console.print("Available profiles:", ", ".join(profiles))
        return Prompt.ask("Select profile", default="DEFAULT")


def select_compartment(config_file_profile: str, tenancy_ocid: str) -> str:
    """Interactive compartment selection using OCI SDK."""
    try:
        import oci
    except ImportError:
        console.print("[yellow]OCI SDK not installed. Install with: pip install oci[/yellow]")
        return Prompt.ask("Enter Compartment OCID")

    try:
        config = oci.config.from_file(profile_name=config_file_profile)
        identity_client = oci.identity.IdentityClient(config)

        compartments = []

        # Add root compartment (tenancy)
        with console.status("Fetching tenancy info..."):
            tenancy = identity_client.get_tenancy(tenancy_ocid).data
            compartments.append({
                "name": f"{tenancy.name} (root)",
                "id": tenancy.id
            })

        # Add child compartments
        with console.status("Fetching compartments..."):
            list_response = identity_client.list_compartments(
                compartment_id=tenancy_ocid,
                compartment_id_in_subtree=True,
                lifecycle_state="ACTIVE"
            )

            for comp in list_response.data:
                compartments.append({
                    "name": comp.name,
                    "id": comp.id
                })

        if compartments:
            choices = [c["name"] for c in compartments]
            if questionary:
                selected = questionary.select(
                    "Select Compartment:",
                    choices=choices
                ).ask()
            else:
                console.print("\nAvailable compartments:")
                for i, c in enumerate(choices, 1):
                    console.print(f"  {i}. {c}")
                idx = Prompt.ask("Select compartment number", default="1")
                selected = choices[int(idx) - 1]

            return next(c["id"] for c in compartments if c["name"] == selected)
        else:
            return Prompt.ask("Enter Compartment OCID")

    except Exception as e:
        console.print(f"[yellow]Error listing compartments: {e}[/yellow]")
        return Prompt.ask("Enter Compartment OCID")


def select_region(config_file_profile: str, current_region: str) -> str:
    """Interactive region selection using OCI SDK."""
    try:
        import oci
    except ImportError:
        return Prompt.ask("Enter Region", default=current_region)

    try:
        config = oci.config.from_file(profile_name=config_file_profile)
        identity_client = oci.identity.IdentityClient(config)

        with console.status("Fetching subscribed regions..."):
            # Get subscribed regions for the tenancy
            tenancy_ocid = config.get("tenancy")
            regions_response = identity_client.list_region_subscriptions(tenancy_ocid)

            regions = []
            for region in regions_response.data:
                regions.append({
                    "name": region.region_name,
                    "display": f"{region.region_name} ({region.region_key})",
                    "is_home": region.is_home_region
                })

        regions.sort(key=lambda x: (not x["is_home"], x["name"]))

        if regions:
            choices = [r["display"] for r in regions]
            default = next(
                (r["display"] for r in regions if r["name"] == current_region),
                choices[0]
            )
            if questionary:
                selected = questionary.select(
                    "Select Region:",
                    choices=choices,
                    default=default
                ).ask()
            else:
                console.print("\nSubscribed regions:")
                for i, r in enumerate(regions, 1):
                    home = " (home)" if r["is_home"] else ""
                    console.print(f"  {i}. {r['display']}{home}")
                idx = Prompt.ask("Select region number", default="1")
                selected = choices[int(idx) - 1]

            return next(r["name"] for r in regions if r["display"] == selected)
        else:
            return Prompt.ask("Enter Region", default=current_region)

    except Exception as e:
        console.print(f"[yellow]Error listing regions: {e}[/yellow]")
        return Prompt.ask("Enter Region", default=current_region)


def generate_password(length: int = 16) -> str:
    """Generate a secure password meeting Oracle requirements."""
    chars = string.ascii_letters + string.digits + "#_"
    while True:
        pwd = ''.join(secrets.choice(chars) for _ in range(length))
        if (any(c.isupper() for c in pwd) and
            any(c.islower() for c in pwd) and
            any(c.isdigit() for c in pwd) and
            any(c in "#_" for c in pwd)):
            return pwd


# ============================================================================
# CLOUD COMMANDS
# ============================================================================

def cloud_setup():
    """Interactive setup for OCI configuration."""
    console.print("\n[bold blue]═══ Oracle Cloud Infrastructure Setup ═══[/bold blue]\n")

    # Check OCI CLI configuration
    oci_config_path = Path.home() / ".oci" / "config"
    if not oci_config_path.exists():
        console.print("[yellow]Warning: OCI CLI config not found at ~/.oci/config[/yellow]")
        console.print("Please configure OCI CLI first: [cyan]oci setup config[/cyan]\n")
        return

    console.print("[green]✓[/green] OCI CLI configuration found\n")

    # Select OCI profile
    config_file_profile = select_profile()
    if not config_file_profile:
        return

    console.print(f"[green]✓[/green] Using profile: {config_file_profile}\n")

    # Read config for selected profile
    oci_config = read_oci_config(config_file_profile)
    tenancy_ocid = oci_config.get("tenancy")
    if not tenancy_ocid:
        console.print(f"[red]Error: No tenancy OCID found in profile '{config_file_profile}'[/red]")
        return

    console.print(f"Tenancy: {tenancy_ocid[:50]}...")

    # Gather configuration interactively
    config = {}
    config['config_file_profile'] = config_file_profile

    # Interactive compartment selection
    config['compartment_id'] = select_compartment(config_file_profile, tenancy_ocid)
    if not config['compartment_id']:
        return
    console.print(f"[green]✓[/green] Compartment selected\n")

    # Interactive region selection
    current_region = oci_config.get("region", "eu-frankfurt-1")
    config['region'] = select_region(config_file_profile, current_region)
    if not config['region']:
        return
    console.print(f"[green]✓[/green] Region: {config['region']}\n")

    # Database configuration
    config['adb_display_name'] = Prompt.ask(
        "ADB Display Name",
        default="PanamaPapersPoC"
    )

    config['adb_db_name'] = Prompt.ask(
        "ADB Database Name (alphanumeric, max 14 chars)",
        default="PANAMAPOC"
    )

    # Generate secure password or let user provide one
    if Confirm.ask("Generate secure ADMIN password?", default=True):
        config['adb_admin_password'] = generate_password()
        console.print(f"[green]✓[/green] Password generated (will be saved to config)")
    else:
        config['adb_admin_password'] = Prompt.ask(
            "ADB ADMIN password (min 12 chars, upper+lower+number)",
            password=True
        )

    config['adb_cpu_count'] = Prompt.ask(
        "ECPU count",
        default="2"
    )

    config['adb_storage_tb'] = Prompt.ask(
        "Storage in TB",
        default="1"
    )

    # Save configuration to .env
    env_save("OCI_PROFILE", config['config_file_profile'])
    env_save("OCI_COMPARTMENT_ID", config['compartment_id'])
    env_save("OCI_REGION", config['region'])
    env_save("ADB_DISPLAY_NAME", config['adb_display_name'])
    env_save("ADB_DB_NAME", config['adb_db_name'])
    env_save("ADB_ADMIN_PASSWORD", config['adb_admin_password'])
    env_save("ADB_CPU_COUNT", config['adb_cpu_count'])
    env_save("ADB_STORAGE_TB", config['adb_storage_tb'])

    console.print(f"[green]✓[/green] Configuration saved to .env")

    # Generate terraform.tfvars using Jinja2 template
    tfvars_path = DEPLOY_DIR / "terraform.tfvars"
    tfvars_template_path = DEPLOY_DIR / "terraform.tfvars.j2"

    if Template and tfvars_template_path.exists():
        template = Template(tfvars_template_path.read_text())
        tfvars_content = template.render(**config)
    else:
        # Fallback if Jinja2 not available or template missing
        tfvars_content = f'''# Auto-generated by manage.py cloud setup
# Panama Papers PoC - Terraform Variables

compartment_id     = "{config['compartment_id']}"
region             = "{config['region']}"
adb_display_name   = "{config['adb_display_name']}"
adb_db_name        = "{config['adb_db_name']}"
adb_admin_password = "{config['adb_admin_password']}"
adb_cpu_count      = {config['adb_cpu_count']}
adb_storage_tb     = {config['adb_storage_tb']}
'''

    tfvars_path.write_text(tfvars_content)
    console.print(f"[green]✓[/green] Generated {tfvars_path}")
    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. cd deploy/terraform")
    console.print("  2. terraform init")
    console.print("  3. terraform plan -out=tfplan")
    console.print("  4. terraform apply tfplan")
    console.print("  5. ./manage.py cloud deploy")


def cloud_deploy():
    """Deploy schema to cloud ADB after Terraform provisioning."""
    console.print("\n[bold blue]═══ Cloud Database Deployment ═══[/bold blue]\n")

    # Check Terraform state
    tfstate_path = DEPLOY_DIR / "terraform.tfstate"
    if not tfstate_path.exists():
        console.print("[red]Error: Terraform state not found.[/red]")
        console.print("Run terraform apply first in deploy/terraform/")
        return

    # Get outputs from Terraform
    console.print("Extracting Terraform outputs...")
    result = run_command(
        ["terraform", "output", "-json"],
        cwd=DEPLOY_DIR,
        capture=True
    )
    outputs = json.loads(result.stdout)

    db_name = outputs.get('adb_db_name', {}).get('value')

    if not db_name:
        console.print("[red]Error: Could not get database name from Terraform outputs[/red]")
        return

    console.print(f"[green]✓[/green] Found ADB: {db_name}")

    # Check for wallet created by Terraform
    wallet_zip = WALLET_DIR / "wallet.zip"
    wallet_password_file = WALLET_DIR / "wallet_password.txt"

    if not wallet_zip.exists():
        console.print("[red]Error: Wallet not found at .wallet/wallet.zip[/red]")
        console.print("Terraform should have created the wallet. Run 'terraform apply' again.")
        return

    console.print(f"[green]✓[/green] Found wallet created by Terraform")

    # Extract wallet
    with zipfile.ZipFile(wallet_zip, 'r') as zf:
        zf.extractall(WALLET_DIR)

    console.print(f"[green]✓[/green] Wallet extracted to {WALLET_DIR}")

    # Read wallet password
    wallet_password = wallet_password_file.read_text().strip()

    # Fix ojdbc.properties for Java 17+ (use JKS instead of SSO wallet)
    ojdbc_props_path = WALLET_DIR / "ojdbc.properties"
    ojdbc_props = f'''# Connection properties for Oracle wallet (JKS mode for Java 17+)
javax.net.ssl.trustStore=${{TNS_ADMIN}}/truststore.jks
javax.net.ssl.trustStorePassword={wallet_password}
javax.net.ssl.keyStore=${{TNS_ADMIN}}/keystore.jks
javax.net.ssl.keyStorePassword={wallet_password}
'''
    ojdbc_props_path.write_text(ojdbc_props)
    console.print(f"[green]✓[/green] Updated ojdbc.properties for JKS mode")

    # Update TNS_ADMIN
    os.environ['TNS_ADMIN'] = str(WALLET_DIR)

    # Get connection string
    tnsnames_path = WALLET_DIR / "tnsnames.ora"
    with open(tnsnames_path) as f:
        tns_content = f.read()

    # Parse service name (use _low for batch operations)
    service_name = f"{db_name.lower()}_low"

    console.print(f"\nUsing service: {service_name}")

    # Run Liquibase deployment
    console.print("\n[bold]Running Liquibase schema deployment...[/bold]\n")

    # Generate liquibase.properties
    admin_password = env_get('ADB_ADMIN_PASSWORD')
    liquibase_props = f'''driver=oracle.jdbc.OracleDriver
url=jdbc:oracle:thin:@{service_name}?TNS_ADMIN={WALLET_DIR}
username=ADMIN
password={admin_password}
changeLogFile=changelog-master.yaml
liquibase.hub.mode=off
'''

    liquibase_props_path = DATABASE_DIR / "liquibase" / "liquibase.properties"
    with open(liquibase_props_path, 'w') as f:
        f.write(liquibase_props)

    # Run Liquibase update
    run_command(
        ["liquibase", "update"],
        cwd=DATABASE_DIR / "liquibase"
    )

    console.print("\n[green]✓[/green] Schema deployment complete!")

    # Save connection info to .env
    env_save('WALLET_DIR', str(WALLET_DIR))
    env_save('SERVICE_NAME', service_name)


def cloud_clean():
    """Clean up cloud deployment artifacts."""
    console.print("\n[bold blue]═══ Cloud Cleanup ═══[/bold blue]\n")

    items_to_clean = [
        (WALLET_DIR, "Wallet directory"),
        (DEPLOY_DIR / "terraform.tfvars", "Terraform variables"),
        (DATABASE_DIR / "liquibase" / "liquibase.properties", "Liquibase properties"),
        (ENV_FILE, "Environment file (.env)"),
    ]

    for path, description in items_to_clean:
        if path.exists():
            if Confirm.ask(f"Delete {description} ({path})?"):
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                console.print(f"[green]✓[/green] Deleted {description}")

    console.print("\n[yellow]Note:[/yellow] Run 'terraform destroy' in deploy/terraform/ to remove cloud resources")


# ============================================================================
# DATA COMMANDS
# ============================================================================

def data_download():
    """Download ICIJ Offshore Leaks CSV files."""
    console.print("\n[bold blue]═══ Download ICIJ Data ═══[/bold blue]\n")

    DATA_DIR.mkdir(exist_ok=True)

    url = "https://offshoreleaks-data.icij.org/offshoreleaks/csv/full-oldb.LATEST.zip"
    zip_path = DATA_DIR / "full-oldb.zip"

    if zip_path.exists():
        if not Confirm.ask("Data already downloaded. Re-download?"):
            return

    console.print(f"Downloading from {url}...")
    console.print("[yellow]Note: This is a large file (~500MB), please wait...[/yellow]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("Downloading...", total=None)

        response = requests.get(url, stream=True)
        response.raise_for_status()

        with open(zip_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        progress.update(task, description="Extracting...")

        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(DATA_DIR)

    console.print(f"\n[green]✓[/green] Data downloaded and extracted to {DATA_DIR}")

    # List files
    csv_files = list(DATA_DIR.glob("*.csv"))
    table = Table(title="Downloaded Files")
    table.add_column("File", style="cyan")
    table.add_column("Size", justify="right")

    for f in csv_files:
        size_mb = f.stat().st_size / (1024 * 1024)
        table.add_row(f.name, f"{size_mb:.1f} MB")

    console.print(table)


def data_ingest():
    """Ingest CSV data into Oracle database."""
    console.print("\n[bold blue]═══ Data Ingestion ═══[/bold blue]\n")

    # Check for CSV files
    csv_files = list(DATA_DIR.glob("*.csv"))
    if not csv_files:
        console.print("[red]Error: No CSV files found in data/[/red]")
        console.print("Run './manage.py data download' first")
        return

    # Run ingestion script
    console.print("Starting data ingestion (this may take 30-60 minutes)...\n")

    run_command([
        sys.executable,
        str(SCRIPTS_DIR / "ingest_data.py"),
        "--data-dir", str(DATA_DIR),
        "--wallet-dir", env_get('WALLET_DIR', str(WALLET_DIR)),
        "--service", env_get('SERVICE_NAME', 'panamapoc_low')
    ])

    console.print("\n[green]✓[/green] Data ingestion complete!")


def data_embeddings():
    """Generate vector embeddings for name fields."""
    console.print("\n[bold blue]═══ Generate Embeddings ═══[/bold blue]\n")

    console.print("Generating vector embeddings (this may take several hours)...\n")

    run_command([
        sys.executable,
        str(SCRIPTS_DIR / "generate_embeddings.py"),
        "--wallet-dir", env_get('WALLET_DIR', str(WALLET_DIR)),
        "--service", env_get('SERVICE_NAME', 'panamapoc_low'),
        "--batch-size", "500"
    ])

    console.print("\n[green]✓[/green] Embedding generation complete!")


# ============================================================================
# MCP COMMANDS
# ============================================================================

def mcp_setup():
    """Configure SQLcl saved connections for MCP server."""
    console.print("\n[bold blue]═══ MCP Connection Setup ═══[/bold blue]\n")

    wallet_dir = env_get('WALLET_DIR', str(WALLET_DIR))
    service_name = env_get('SERVICE_NAME', 'panamapoc_low')

    # Use default password for PANAMA_PAPERS user (created by Liquibase)
    password = 'PanamaPapers2024!'
    console.print("Using PANAMA_PAPERS schema with default credentials")

    # Create SQLcl connection using conn command
    # SQLcl stores connections in ~/.sqlcl/connections.xml

    connection_name = "panama_papers"

    console.print(f"\nSaving SQLcl connection: {connection_name}")

    # Use SQLcl to save the connection
    sqlcl_cmd = f'''
conn -save {connection_name} -savepwd PANAMA_PAPERS/{password}@{service_name}
exit
'''

    # Set TNS_ADMIN for wallet
    env = os.environ.copy()
    env['TNS_ADMIN'] = wallet_dir

    process = subprocess.Popen(
        ['sql', '/nolog'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env
    )
    stdout, stderr = process.communicate(input=sqlcl_cmd)

    if process.returncode != 0:
        console.print(f"[red]Error saving connection: {stderr}[/red]")
        return

    console.print(f"[green]✓[/green] Connection '{connection_name}' saved")

    # Generate .mcp.json
    mcp_config = {
        "mcpServers": {
            "oracle-database": {
                "command": "sql",
                "args": [
                    "-oci",
                    "-nohistory",
                    "-nomcp",
                    f"{connection_name}"
                ],
                "env": {
                    "TNS_ADMIN": wallet_dir
                }
            }
        }
    }

    mcp_json_path = PROJECT_ROOT / ".mcp.json"
    with open(mcp_json_path, 'w') as f:
        json.dump(mcp_config, f, indent=2)

    console.print(f"[green]✓[/green] MCP configuration saved to {mcp_json_path}")

    console.print("\n[bold]MCP server configured![/bold]")
    console.print("You can now use Claude Code to query the Panama Papers database.")
    console.print("\nExample prompts:")
    console.print('  "List the top 10 jurisdictions by entity count"')
    console.print('  "Find officers with names similar to Putin"')
    console.print('  "Show the graph schema for panama_graph"')


def mcp_test():
    """Test MCP connection."""
    console.print("\n[bold blue]═══ Test MCP Connection ═══[/bold blue]\n")

    wallet_dir = env_get('WALLET_DIR', str(WALLET_DIR))

    env = os.environ.copy()
    env['TNS_ADMIN'] = wallet_dir

    test_query = "SELECT COUNT(*) AS entity_count FROM entities;"

    result = subprocess.run(
        ['sql', '-S', 'panama_papers', '-c', test_query],
        capture_output=True,
        text=True,
        env=env
    )

    if result.returncode == 0:
        console.print("[green]✓[/green] Connection successful!")
        console.print(f"\nQuery result:\n{result.stdout}")
    else:
        console.print(f"[red]Connection failed: {result.stderr}[/red]")


# ============================================================================
# FULL WORKFLOW COMMANDS
# ============================================================================

def full_setup():
    """Complete end-to-end setup."""
    console.print("\n[bold blue]═══ Full Setup Workflow ═══[/bold blue]\n")

    steps = [
        ("Cloud Configuration", cloud_setup),
        ("Data Download", data_download),
    ]

    for step_name, step_func in steps:
        console.print(f"\n[bold]Step: {step_name}[/bold]")
        step_func()

    console.print("\n[bold green]═══ Setup Phase Complete ═══[/bold green]")
    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. cd deploy/terraform && terraform init && terraform apply")
    console.print("  2. ./manage.py cloud deploy")
    console.print("  3. ./manage.py data ingest")
    console.print("  4. ./manage.py data embeddings  (optional)")
    console.print("  5. ./manage.py mcp setup")


def full_clean():
    """Complete cleanup of all resources."""
    console.print("\n[bold blue]═══ Full Cleanup ═══[/bold blue]\n")

    if not Confirm.ask("[red]This will delete ALL local artifacts. Continue?[/red]"):
        return

    cloud_clean()

    # Clean data directory
    if DATA_DIR.exists() and Confirm.ask("Delete downloaded data?"):
        shutil.rmtree(DATA_DIR)
        DATA_DIR.mkdir()
        (DATA_DIR / ".gitkeep").touch()
        console.print("[green]✓[/green] Data directory cleaned")

    console.print("\n[bold green]═══ Cleanup Complete ═══[/bold green]")
    console.print("\n[yellow]Don't forget to run 'terraform destroy' if needed[/yellow]")


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Panama Papers PoC Management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ./manage.py cloud setup      Configure OCI credentials
  ./manage.py cloud deploy     Deploy database schema
  ./manage.py data download    Download ICIJ data
  ./manage.py data ingest      Load data into Oracle
  ./manage.py mcp setup        Configure MCP connections
  ./manage.py full clean       Complete cleanup
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Command category')

    # Cloud commands
    cloud_parser = subparsers.add_parser('cloud', help='Cloud infrastructure commands')
    cloud_sub = cloud_parser.add_subparsers(dest='subcommand')
    cloud_sub.add_parser('setup', help='Interactive OCI configuration')
    cloud_sub.add_parser('deploy', help='Deploy schema via Liquibase')
    cloud_sub.add_parser('clean', help='Clean cloud artifacts')

    # Data commands
    data_parser = subparsers.add_parser('data', help='Data management commands')
    data_sub = data_parser.add_subparsers(dest='subcommand')
    data_sub.add_parser('download', help='Download ICIJ CSV files')
    data_sub.add_parser('ingest', help='Load data into Oracle')
    data_sub.add_parser('embeddings', help='Generate vector embeddings')

    # MCP commands
    mcp_parser = subparsers.add_parser('mcp', help='MCP configuration commands')
    mcp_sub = mcp_parser.add_subparsers(dest='subcommand')
    mcp_sub.add_parser('setup', help='Configure SQLcl connections')
    mcp_sub.add_parser('test', help='Test MCP connection')

    # Full workflow commands
    full_parser = subparsers.add_parser('full', help='Full workflow commands')
    full_sub = full_parser.add_subparsers(dest='subcommand')
    full_sub.add_parser('setup', help='Complete setup workflow')
    full_sub.add_parser('clean', help='Complete cleanup')

    args = parser.parse_args()

    # Command dispatch
    commands = {
        ('cloud', 'setup'): cloud_setup,
        ('cloud', 'deploy'): cloud_deploy,
        ('cloud', 'clean'): cloud_clean,
        ('data', 'download'): data_download,
        ('data', 'ingest'): data_ingest,
        ('data', 'embeddings'): data_embeddings,
        ('mcp', 'setup'): mcp_setup,
        ('mcp', 'test'): mcp_test,
        ('full', 'setup'): full_setup,
        ('full', 'clean'): full_clean,
    }

    key = (args.command, args.subcommand)
    if key in commands:
        commands[key]()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
