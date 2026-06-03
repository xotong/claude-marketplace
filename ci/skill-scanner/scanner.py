#!/usr/bin/env python3
"""
Skill Safety Scanner
Scans all instruction files in a directory tree and evaluates each for security
risks using an OpenAI-compatible LLM endpoint.

Configuration (highest precedence first):
  1. Environment variables          (SCANNER_THRESHOLD, SCANNER_MODEL, ...)
  2. scanner-config.yaml in the skills directory  (tenant overrides)
  3. /scanner/config.yaml           (defaults baked into the image)

Required env vars:
  SCANNER_ENDPOINT   OpenAI-compatible base URL, e.g. https://litellm.company.com/v1
  SCANNER_API_KEY    API key for the endpoint

Optional env vars:
  SCANNER_SKILLS_DIR    Directory to scan recursively (default: .)
  SCANNER_OUTPUT_DIR    Where to write scan-report.json and scan-results.xml
                        (default: <skills_dir>/.skill-scanner-output)
  SCANNER_THRESHOLD     Float 0-1, override config threshold (default: 0.85)
  SCANNER_MODEL         Model name as registered in LiteLLM (override config)
  SCANNER_FAIL_ON_REVIEW  Treat REVIEW_NEEDED verdict as failure (default: false)
  SCANNER_CONFIG_FILE   Explicit path to a config YAML (overrides discovery)
  SCANNER_MAX_RETRIES   API call retries on transient error (default: 3)
  SCANNER_WORKERS       Parallel LLM workers (default: 10)
  SCANNER_FILES         Comma-separated list of instruction file paths to scan instead of
                        the full directory tree. Paths may be absolute or relative
                        to SCANNER_SKILLS_DIR. When set, only the listed files are
                        scanned — use this in CI to scan only changed files.
                        Accepted: SKILL.md files, agents/*.md, commands/**/*.md.
"""

import json
import os
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import yaml
from openai import OpenAI, APIConnectionError, APIStatusError, RateLimitError
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()
console_lock = threading.Lock()

BUILTIN_CONFIG = Path(__file__).parent / "config.yaml"


# ── Config loading ────────────────────────────────────────────────────────────

def load_config(skills_dir: Path) -> dict:
    """Merge config from builtin → local file → env vars."""
    with open(BUILTIN_CONFIG) as f:
        config = yaml.safe_load(f)

    explicit = os.environ.get("SCANNER_CONFIG_FILE")
    if explicit:
        p = Path(explicit)
        if not p.exists():
            console.print(f"[red]SCANNER_CONFIG_FILE not found: {p}[/red]")
            sys.exit(2)
        with open(p) as f:
            config.update({k: v for k, v in (yaml.safe_load(f) or {}).items() if v is not None})
        console.print(f"[dim]Config loaded from {p}[/dim]")
    else:
        local = skills_dir / "scanner-config.yaml"
        if local.exists():
            with open(local) as f:
                config.update({k: v for k, v in (yaml.safe_load(f) or {}).items() if v is not None})
            console.print(f"[dim]Local config merged from {local}[/dim]")

    if os.environ.get("SCANNER_THRESHOLD"):
        config["threshold"] = float(os.environ["SCANNER_THRESHOLD"])
    if os.environ.get("SCANNER_MODEL"):
        config["model"] = os.environ["SCANNER_MODEL"]

    return config


# ── LLM call ─────────────────────────────────────────────────────────────────

def scan_skill(client: OpenAI, config: dict, skill_path: Path, max_retries: int) -> dict:
    """Call the LLM and return the parsed safety assessment."""
    skill_content = skill_path.read_text(encoding="utf-8")
    # Use str.replace() not str.format() — skill files routinely contain { } braces
    # in JSON examples, shell variables, and template syntax. .format() would attempt
    # to substitute those as Python format fields and raise KeyError/IndexError.
    user_prompt = config["user_prompt"].replace("{skill_content}", skill_content)

    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=config["model"],
                messages=[
                    {"role": "system", "content": config["system_prompt"]},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
                response_format={"type": "json_object"},
                timeout=30,
            )
            raw = response.choices[0].message.content
            result = json.loads(raw)
            result.setdefault("confidence_safe", 0.0)
            result.setdefault("risks", [])
            result.setdefault("reasoning", "")
            result.setdefault("verdict", "UNKNOWN")
            return result

        except (APIConnectionError, RateLimitError) as e:
            if attempt == max_retries:
                raise
            wait = 2 ** attempt
            with console_lock:
                console.print(f"[yellow]  Attempt {attempt} failed ({e}), retrying in {wait}s…[/yellow]")
            time.sleep(wait)

        except APIStatusError as e:
            if e.status_code >= 500 and attempt < max_retries:
                wait = 2 ** attempt
                with console_lock:
                    console.print(f"[yellow]  Attempt {attempt} failed (HTTP {e.status_code}), retrying in {wait}s…[/yellow]")
                time.sleep(wait)
            else:
                raise RuntimeError(f"API error {e.status_code}: {e.message}") from e

        except json.JSONDecodeError as e:
            raise RuntimeError(f"LLM returned non-JSON: {raw[:200]}") from e


# ── File discovery ────────────────────────────────────────────────────────────

def find_instruction_files(root: Path) -> list[Path]:
    """Find all instruction files that need safety scanning:
    - SKILL.md everywhere in the tree (standard skill convention)
    - Any *.md file under skills/ with a YAML frontmatter name: field
      (catches non-standard skill naming like dual-mode/*.md)
    - All *.md files under agents/ (sub-agent definitions)
    - All *.md files recursively under commands/ (slash command definitions)
    Hidden directories (.git, etc.) are excluded throughout.
    """
    def not_hidden(p: Path) -> bool:
        return not any(part.startswith(".") for part in p.relative_to(root).parts[:-1])

    def has_skill_frontmatter(p: Path) -> bool:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
            if not text.startswith("---"):
                return False
            end = text.find("---", 3)
            return end > 0 and "name:" in text[3:end]
        except OSError:
            return False

    found: set[Path] = set()

    found.update(p for p in root.rglob("SKILL.md") if not_hidden(p))

    skills_dir = root / "skills"
    if skills_dir.is_dir():
        for p in skills_dir.rglob("*.md"):
            if p.name != "SKILL.md" and not_hidden(p) and has_skill_frontmatter(p):
                found.add(p)

    agents_dir = root / "agents"
    if agents_dir.is_dir():
        found.update(p for p in agents_dir.rglob("*.md") if not_hidden(p))

    commands_dir = root / "commands"
    if commands_dir.is_dir():
        found.update(p for p in commands_dir.rglob("*.md") if not_hidden(p))

    return sorted(found)


# ── Output writers ────────────────────────────────────────────────────────────

def write_json_report(results: list[dict], threshold: float, output_path: Path) -> None:
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "threshold": threshold,
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r["passed"]),
            "failed": sum(1 for r in results if not r["passed"]),
        },
        "results": results,
    }
    output_path.write_text(json.dumps(report, indent=2))


def write_junit_report(results: list[dict], threshold: float, output_path: Path) -> None:
    """Write JUnit XML — GitLab renders this as named test cases in the MR UI."""
    failures = sum(1 for r in results if not r["passed"])
    suite = ET.Element(
        "testsuite",
        name="skill-safety-scan",
        tests=str(len(results)),
        failures=str(failures),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    for r in results:
        tc = ET.SubElement(suite, "testcase", name=r["path"], classname="SkillSafety")
        if not r["passed"]:
            score = r.get("confidence_safe", 0)
            risks = ", ".join(r.get("risks", [])) or "none detected"
            msg = r.get("error") or f"Score {score:.2f} below threshold {threshold} | risks: {risks}"
            failure = ET.SubElement(tc, "failure", message=msg, type="SkillSafetyFailure")
            failure.text = r.get("reasoning") or r.get("error", "")
    tree = ET.ElementTree(ET.Element("testsuites"))
    tree.getroot().append(suite)
    ET.indent(tree, space="  ")
    output_path.write_bytes(ET.tostring(tree.getroot(), encoding="utf-8", xml_declaration=True))


def print_summary_table(results: list[dict], threshold: float) -> None:
    table = Table(title="\nScan Results", box=box.ROUNDED, show_lines=True)
    table.add_column("Skill", style="cyan", no_wrap=True)
    table.add_column("Score", justify="center", width=7)
    table.add_column("Verdict", width=15)
    table.add_column("Risks")

    for r in results:
        score = r.get("confidence_safe", 0)
        verdict = r.get("verdict", "ERROR")
        risks = ", ".join(r.get("risks", [])) or "—"
        color = "green" if r["passed"] else "red"
        table.add_row(r["path"], f"[{color}]{score:.2f}[/{color}]", f"[{color}]{verdict}[/{color}]", risks)

    console.print(table)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    endpoint = os.environ.get("SCANNER_ENDPOINT", "").strip()
    api_key = os.environ.get("SCANNER_API_KEY", "").strip()
    if not endpoint or not api_key:
        console.print("[red bold]ERROR:[/red bold] SCANNER_ENDPOINT and SCANNER_API_KEY must be set.")
        sys.exit(2)

    skills_dir = Path(os.environ.get("SCANNER_SKILLS_DIR", ".")).resolve()
    if not skills_dir.is_dir():
        console.print(f"[red bold]ERROR:[/red bold] SCANNER_SKILLS_DIR not found: {skills_dir}")
        sys.exit(2)

    output_dir = Path(
        os.environ.get("SCANNER_OUTPUT_DIR", str(skills_dir / ".skill-scanner-output"))
    ).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    fail_on_review = os.environ.get("SCANNER_FAIL_ON_REVIEW", "false").lower() in ("1", "true", "yes")
    max_retries = int(os.environ.get("SCANNER_MAX_RETRIES", "3"))
    max_workers = int(os.environ.get("SCANNER_WORKERS", "10"))

    config = load_config(skills_dir)
    threshold: float = config["threshold"]

    scanner_files_env = os.environ.get("SCANNER_FILES", "").strip()
    if scanner_files_env:
        explicit_paths = [p.strip() for p in scanner_files_env.split(",") if p.strip()]
        skills = []
        for raw in explicit_paths:
            p = Path(raw)
            if not p.is_absolute():
                p = skills_dir / p
            p = p.resolve()
            if not p.exists():
                console.print(f"[yellow]  Warning: SCANNER_FILES entry not found, skipping: {p}[/yellow]")
                continue
            if p.suffix != ".md":
                console.print(f"[yellow]  Warning: SCANNER_FILES entry is not a .md file, skipping: {p}[/yellow]")
                continue
            skills.append(p)
        mode_str = f"targeted ({len(skills)} file(s) from SCANNER_FILES)"
    else:
        skills = find_instruction_files(skills_dir)
        mode_str = "full scan"

    console.rule("[bold]Skill Safety Scanner[/bold]")
    console.print(f"  Directory : {skills_dir}")
    console.print(f"  Output    : {output_dir}")
    console.print(f"  Endpoint  : {endpoint}")
    console.print(f"  Model     : {config['model']}")
    console.print(f"  Threshold : {threshold}")
    console.print(f"  Workers   : {max_workers}")
    console.print(f"  Fail on REVIEW_NEEDED: {fail_on_review}")
    console.print(f"  Mode      : {mode_str}")
    console.rule()

    if not skills:
        console.print("[yellow]No instruction files found to scan. Nothing to do.[/yellow]")
        sys.exit(0)

    console.print(f"\nFound [bold]{len(skills)}[/bold] file(s) to scan.\n")

    client = OpenAI(base_url=endpoint, api_key=api_key)
    results: list[dict] = []

    # NDJSON sidecar: one JSON line per completed file, appended as each worker
    # finishes. If the CI job is killed mid-scan the partial results are readable.
    # The canonical scan-report.json is written once at the end, sorted by path.
    ndjson_partial = output_dir / "scan-report-partial.ndjson"
    ndjson_partial.unlink(missing_ok=True)

    def scan_one(skill_path: Path) -> dict:
        rel = str(skill_path.relative_to(skills_dir))
        try:
            assessment = scan_skill(client, config, skill_path, max_retries)
            score = assessment["confidence_safe"]
            verdict = assessment["verdict"]
            passed = score >= threshold and not (fail_on_review and verdict == "REVIEW_NEEDED")
            color = "green" if passed else "red"
            with console_lock:
                console.print(f"  [cyan]{rel}[/cyan] [{color}]{score:.2f}[/{color}] — [{color}]{verdict}[/{color}]")
            return {"path": rel, "passed": passed, **assessment}
        except Exception as e:
            with console_lock:
                console.print(f"  [cyan]{rel}[/cyan] [red]ERROR — {e}[/red]")
            return {
                "path": rel, "passed": False, "error": str(e),
                "confidence_safe": 0.0, "verdict": "ERROR", "risks": [], "reasoning": "",
            }

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(scan_one, p): p for p in skills}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            with ndjson_partial.open("a") as f:
                f.write(json.dumps(result) + "\n")

    results.sort(key=lambda r: r["path"])
    print_summary_table(results, threshold)

    json_report = output_dir / "scan-report.json"
    junit_report = output_dir / "scan-results.xml"
    write_json_report(results, threshold, json_report)
    write_junit_report(results, threshold, junit_report)
    console.print(f"\n  JSON report  : {json_report}")
    console.print(f"  Partial NDJSON: {ndjson_partial}")
    console.print(f"  JUnit XML    : {junit_report}")

    failures = [r for r in results if not r["passed"]]
    console.rule()
    if failures:
        console.print(f"\n[red bold]FAILED[/red bold] — {len(failures)}/{len(results)} file(s) did not pass.\n")
        for r in failures:
            detail = r.get("reasoning") or r.get("error") or "no detail"
            console.print(f"  [red]✗[/red] {r['path']}")
            console.print(f"    {detail}\n")
        sys.exit(1)
    else:
        console.print(f"\n[green bold]PASSED[/green bold] — all {len(results)} file(s) cleared threshold {threshold}.\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
