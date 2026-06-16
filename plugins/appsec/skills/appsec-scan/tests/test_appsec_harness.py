import argparse
import json
import os
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT))

import appsec_harness as harness  # noqa: E402


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_resolve_jobs_from_local_chronicle_template(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    write(project / "requirements.txt", "flask\n")
    chronicle = tmp_path / "chronicle"
    write(
        chronicle / "pylint/templates/pylint.yml",
        """
spec:
  inputs:
    job-name:
      default: pylint
    source:
      default: $CI_PROJECT_DIR/.
    image:
      default: docker.io/touching/pylint:latest
---
"$[[ inputs.job-name ]]":
  image:
    name: $CI_REGISTRY/touching/pylint:latest
    entrypoint: [""]
  script:
    - echo $[[ inputs.source ]]
    - pylint $[[ inputs.source ]] --output-format=json:pylint-report.json
""",
    )
    registry = write(
        tmp_path / "registry.yaml",
        """
defaults:
  output_dir: ${APPSEC_TEST_OUTPUT_DIR}
  cache_dir: ${APPSEC_TEST_OUTPUT_DIR}/component-cache
components:
  pylint:
    template_path: pylint/templates/pylint.yml
    scanner: pylint
    default_enabled: true
    detect:
      any_exists: [requirements.txt]
    inputs:
      source: "${PYLINT_SOURCE:-$CI_PROJECT_DIR/.}"
""",
    )
    monkeypatch.setenv("APPSEC_CHRONICLE_LOCAL_DIR", str(chronicle))
    monkeypatch.setenv("APPSEC_TEST_OUTPUT_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("CI_REGISTRY", "registry.example.com")
    defaults, components = harness.registry_components(registry)
    args = argparse.Namespace(project_dir=str(project), component=None, include_unconfigured=False)

    jobs = harness.resolve_jobs(args, defaults, components)

    assert len(jobs) == 1
    assert jobs[0]["component"] == "pylint"
    assert jobs[0]["image"] == "registry.example.com/touching/pylint:latest"
    assert "pylint" in "\n".join(jobs[0]["script"])
    assert "/workspace/." in "\n".join(jobs[0]["script"])


def test_normalize_pylint_and_eslint_reports(tmp_path):
    results = tmp_path / "results"
    write(
        results / "pylint-report.json",
        '##tool = Pylint\n[{"type":"error","message":"bad call","path":"src/app.py","line":7,"message-id":"E1120"}]\n',
    )
    write(
        results / "eslint.json",
        json.dumps(
            [
                {
                    "filePath": "src/index.ts",
                    "messages": [{"severity": 2, "message": "eval is unsafe", "line": 3, "column": 9, "ruleId": "no-eval"}],
                }
            ]
        ),
    )

    findings = harness.normalize_reports(results)
    by_scanner = {finding["scanner"]: finding for finding in findings}

    assert by_scanner["pylint"]["severity"] == "HIGH"
    assert by_scanner["pylint"]["location"]["file"] == "src/app.py"
    assert by_scanner["eslint"]["severity"] == "HIGH"
    assert by_scanner["eslint"]["evidence"]["rule_id"] == "no-eval"


def test_triage_marks_test_paths_false_positive_and_gate_ignores_them():
    findings = [
        harness.new_finding("eslint", "unsafe", "HIGH", {"file": "tests/fixture.js"}, {"rule_id": "x"}),
        harness.new_finding("eslint", "unsafe", "HIGH", {"file": "src/app.js"}, {"rule_id": "x"}),
    ]

    triaged = harness.triage_findings(findings)

    assert triaged[0]["verification_status"] == "likely_false_positive"
    assert triaged[1]["verification_status"] == "confirmed_true_positive"
    assert harness.gate_failed(triaged, {"ci_gate": {"severities": ["CRITICAL", "HIGH"]}})


def test_gate_fails_when_high_is_likely_false_positive_until_user_accepts():
    findings = [
        harness.new_finding("eslint", "unsafe", "HIGH", {"file": "vendor/lib.js"}, {"rule_id": "x"}),
    ]
    triaged = harness.triage_findings(findings)

    assert triaged[0]["verification_status"] == "likely_false_positive"
    assert harness.gate_failed(triaged, {"ci_gate": {"severities": ["CRITICAL", "HIGH"]}})


def test_fetch_template_requires_explicit_stale_cache_flag(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cached = write(cache / "main/pylint/templates/pylint.yml", "spec: {}\n---\njob:\n  script: [echo ok]\n")
    harness.write_json(
        cached.with_suffix(cached.suffix + ".meta.json"),
        {"source": "test", "ref": "main", "sha256": "8ae6e0dac446703578d2641f251c6a7467ba6508b98d329e096d2838fdbec066"},
    )
    component = harness.Component("pylint", {"template_path": "pylint/templates/pylint.yml"})
    monkeypatch.delenv("APPSEC_CHRONICLE_LOCAL_DIR", raising=False)
    monkeypatch.delenv("APPSEC_COMPONENT_RAW_BASE", raising=False)
    monkeypatch.delenv("APPSEC_GITLAB_URL", raising=False)
    monkeypatch.delenv("APPSEC_GITLAB_PROJECT", raising=False)

    with pytest.raises(harness.HarnessError):
        harness.fetch_template(component, {"ref": "main"}, cache)

    text, source = harness.fetch_template(component, {"ref": "main"}, cache, allow_stale_cache=True)

    assert "echo ok" in text
    assert source.startswith("cache:")


def test_remote_template_ref_must_be_pinned_by_default(monkeypatch):
    monkeypatch.delenv("APPSEC_ALLOW_UNPINNED_COMPONENTS", raising=False)

    with pytest.raises(harness.HarnessError):
        harness.validate_remote_component_source("https://gitlab.example.com/group/chronicle/-/raw/{ref}", "main")

    harness.validate_remote_component_source("https://gitlab.example.com/group/chronicle/-/raw/{ref}", "a" * 40)


def test_raw_base_must_include_ref_placeholder():
    with pytest.raises(harness.HarnessError):
        harness.validate_raw_base("https://gitlab.example.com/group/chronicle/-/raw/main", "a" * 40)


def test_numeric_fortify_severity_gates():
    finding = harness.new_finding("fortify", "SQL Injection", "5.0", {"file": "src/app.py", "line": 12}, {"rule_id": "1"})

    assert finding["severity"] == "CRITICAL"
    assert harness.gate_failed([finding], {"ci_gate": {"severities": ["CRITICAL", "HIGH"]}})


def test_relative_output_dir_resolves_under_project(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(tmp_path)

    out_dir = harness.output_dir({"output_dir": ".appsec-results"}, project)

    assert out_dir == project / ".appsec-results"


def test_render_runner_shell_quotes_env_values(tmp_path):
    job = {
        "component": "eslint",
        "variables": {"SAFE_VALUE": 'hello "$(touch bad)"'},
        "script": ["echo ok"],
    }

    runner = harness.render_runner(job, tmp_path)
    text = runner.read_text(encoding="utf-8")

    assert "export SAFE_VALUE='hello \"$(touch bad)\"'" in text


def test_parse_failure_is_high_severity_gate_failure(tmp_path):
    write(tmp_path / "broken.json", "{")

    findings = harness.normalize_reports(tmp_path)

    assert findings[0]["scanner"] == "normalizer"
    assert findings[0]["severity"] == "HIGH"
    assert harness.gate_failed(findings, {"ci_gate": {"severities": ["CRITICAL", "HIGH"]}})


def test_report_coverage_fails_when_expected_report_missing(tmp_path):
    jobs = [{"component": "pylint", "artifacts": {"paths": ["pylint-report.json"]}}]

    findings = harness.report_coverage_findings(jobs, tmp_path / "reports")

    assert findings[0]["evidence"]["rule_id"] == "APPSEC-REPORT-MISSING"
    assert harness.gate_failed(findings, {"ci_gate": {"severities": ["CRITICAL", "HIGH"]}})


def test_mutable_images_require_explicit_acceptance(monkeypatch):
    monkeypatch.delenv("APPSEC_ALLOW_MUTABLE_IMAGES", raising=False)

    with pytest.raises(harness.HarnessError):
        harness.validate_image_trust("registry.example.com/scanner:latest")

    harness.validate_image_trust("registry.example.com/scanner@sha256:" + "a" * 64)
