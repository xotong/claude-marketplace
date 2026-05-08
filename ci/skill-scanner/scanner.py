#!/usr/bin/env python3
"""
Skill Safety Scanner
Scans all SKILL.md files in a directory tree and evaluates each for security
risks using an OpenAI-compatible LLM endpoint.

Configuration (highest precedence first):
  1. Environment variables          (SCANNER_THRESHOLD, SCANNER_MODEL, ...)
  2. scanner-config.yaml in the skills directory  (tenant overrides)
  3. /scanner/config.yaml           (defaults baked into the image)

Required env vars:
  SCANNER_ENDPOINT   OpenAI-compatible base URL, e.g. https://litellm.company.com/v1
  SCANNER_API_KEY    API key for the endpoint

Optional env vars:
  SCANNER_SKILLS_DIR          Directory to scan recursively (default: .)
  SCANNER_THRESHOLD           Float 0-1, override config threshold (default: 0.85)
  SCANNER_MODEL               Model name as registered in LiteLLM (override config)
  SCANNER_FAIL_ON_REVIEW      Treat REVIEW_NEEDED verdict as failure (default: false)
  SCANNER_CONFIG_FILE         Explicit path to a config YAML (overrides discovery)
  SCANNER_MAX_RETRIES         API call retries on transient error (default: 3)
"""

import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import yaml
from openai import OpenAI, APIConnectionError, APIStatusError, RateLimitError
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()

# ── Config loading ────────────────────────────────────────────────────────────

BUILTIN_CONFIG = Path(__file__).parent / "config.yaml"


def load_config(skills_dir: Path) -> dict:
    """Merge config from builtin → local file → env vars."""
    with open(BUILTIN_CONFIG) as f:
        config = yaml.safe_load(f)

    # Explicit config file path from env
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
        # Auto-discover scanner-config.yaml in skills dir
        local = skills_dir / "scanner-config.yaml"
        if local.exists():
            with open(local) as f:
                config.update({k: v for k, v in (yaml.safe_load(f) or {}).items() if v is not None})
            console.print(f"[dim]Local config merged from {local}[/dim]")

    # Env var overrides — individual knobs without a full config rewrite
    if os.environ.get("SCANNER_THRESHOLD"):
        config["threshold"] = float(os.environ["SCANNER_THRESHOLD"])
    if os.environ.get("SCANNER_MODEL"):
        config["model"] = os.environ["SCANNER_MODEL"]

    return config


# ── LLM call ─────────────────────────────────────────────────────────────────

def scan_skill(client: OpenAI, config: dict, skill_path: Path, max_retries: int) -> dict:
    """Call the LLM and return the parsed safety assessment."""
    skill_content = skill_path.read_text(encoding="utf-8")
    user_prompt = config["user_prompt"].format(skill_content=skill_content)

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
            )
            raw = response.choices[0].message.content
            result = json.loads(raw)
            # Normalise: ensure required fields exist
            result.setdefault("confidence_safe", 0.0)
            result.setdefault("risks", [])
            result.setdefault("reasoning", "")
            result.setdefault("verdict", "UNKNOWN")
            return result

        except (APIConnectionError, RateLimitError) as e:
            if attempt == max_retries:
                raise
            wait = 2 ** attempt
            console.print(f"[yellow]  Attempt {attempt} failed ({e}), retrying in {wait}s…[/yellow]")
            time.sleep(wait)

        except APIStatusError as e:
            raise RuntimeError(f"API error {e.status_code}: {e.message}") from e

        except json.JSONDecodeError as e:
            raise RuntimeError(f"LLM returned non-JSON: {raw[:200]}") from e


# ── File discovery ────────────────────────────────────────────────────────────

def find_skills(root: Path) -> list[Path]:
    return sorted(root.rglob("SKILL.md"))


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

        if r["passed"]:
            score_str = f"[green]{score:.2f}[/green]"
            verdict_str = f"[green]{verdict}[/green]"
        else:
            score_str = f"[red]{score:.2f}[/red]"
            verdict_str = f"[red]{verdict}[/red]"

        table.add_row(r["path"], score_str, verdict_str, risks)

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

    fail_on_review = os.environ.get("SCANNER_FAIL_ON_REVIEW", "false").lower() in ("1", "true", "yes")
    max_retries = int(os.environ.get("SCANNER_MAX_RETRIES", "3"))

    config = load_config(skills_dir)
    threshold: float = config["threshold"]

    console.rule("[bold]Skill Safety Scanner[/bold]")
    console.print(f"  Directory : {skills_dir}")
    console.print(f"  Endpoint  : {endpoint}")
    console.print(f"  Model     : {config['model']}")
    console.print(f"  Threshold : {threshold}")
    console.print(f"  Fail on REVIEW_NEEDED: {fail_on_review}")
    console.rule()

    skills = find_skills(skills_dir)
    if not skills:
        console.print(f"[yellow]No SKILL.md files found under {skills_dir}. Nothing to scan.[/yellow]")
        sys.exit(0)

    console.print(f"\nFound [bold]{len(skills)}[/bold] skill(s) to scan.\n")

    client = OpenAI(base_url=endpoint, api_key=api_key)
    results: list[dict] = []

    for skill_path in skills:
        rel = str(skill_path.relative_to(skills_dir))
        console.print(f"  Scanning [cyan]{rel}[/cyan] …", end=" ")
        try:
            assessment = scan_skill(client, config, skill_path, max_retries)
            score = assessment["confidence_safe"]
            verdict = assessment["verdict"]

            is_failure = score < threshold or (fail_on_review and verdict == "REVIEW_NEEDED")
            passed = not is_failure and assessment.get("error") is None

            color = "green" if passed else "red"
            console.print(f"[{color}]{score:.2f}[/{color}] — [{color}]{verdict}[/{color}]")

            results.append({
                "path": rel,
                "passed": passed,
                "error": None,
                **assessment,
            })
        except Exception as e:
            console.print(f"[red]ERROR — {e}[/red]")
            results.append({
                "path": rel,
                "passed": False,
                "error": str(e),
                "confidence_safe": 0.0,
                "verdict": "ERROR",
                "risks": [],
                "reasoning": "",
            })

    print_summary_table(results, threshold)

    # Write reports into the skills dir so GitLab CI can pick them up as artifacts
    json_report = skills_dir / "scan-report.json"
    junit_report = skills_dir / "scan-results.xml"
    write_json_report(results, threshold, json_report)
    write_junit_report(results, threshold, junit_report)
    console.print(f"\n  JSON report : {json_report}")
    console.print(f"  JUnit XML   : {junit_report}")

    failures = [r for r in results if not r["passed"]]
    console.rule()
    if failures:
        console.print(f"\n[red bold]FAILED[/red bold] — {len(failures)}/{len(results)} skill(s) did not pass.\n")
        for r in failures:
            detail = r.get("reasoning") or r.get("error") or "no detail"
            console.print(f"  [red]✗[/red] {r['path']}")
            console.print(f"    {detail}\n")
        sys.exit(1)
    else:
        console.print(f"\n[green bold]PASSED[/green bold] — all {len(results)} skill(s) cleared threshold {threshold}.\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
