#!/usr/bin/env python3
"""Deterministic helper for the Claude Code AppSec scan skill.

Claude Code owns the workflow: deciding what to scan, explaining findings,
editing code, and repeating remediation. This helper only handles repeatable
mechanics: fetching Chronicle GitLab component templates, rendering scanner jobs
for local Docker execution, normalizing scanner reports, and applying a simple
evidence-based triage model.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

try:
    import yaml
except ImportError as exc:  # pragma: no cover - depends on host environment
    raise SystemExit("PyYAML is required: install pyyaml before running appsec-scan") from exc


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_REGISTRY = SKILL_DIR / "references" / "chronicle-components.yaml"
SEVERITY_ORDER = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
INPUT_EXPR_RE = re.compile(r"\$\[\[\s*inputs\.([A-Za-z0-9_-]+)\s*\]\]")
ENV_EXPR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}|\$([A-Za-z_][A-Za-z0-9_]*)")
ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
PINNED_REF_RE = re.compile(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}")
SECRET_NAME_RE = re.compile(r"(TOKEN|PASSWORD|SECRET|KEY|AUTH|CREDENTIAL)", re.IGNORECASE)
LOCAL_TEMPLATE_HOSTS = {"localhost", "127.0.0.1", "::1"}
PARSEABLE_SUFFIXES = {".json", ".xml", ".fvdl", ".fpr"}
HARNESS_JSON_FILES = {"resolved-jobs.json", "scan-coverage.json", "findings.normalized.json", "findings.triaged.json"}
DEFAULT_CONTAINER_ENV = {
    "CI_COMMIT_BRANCH",
    "CI_COMMIT_REF_NAME",
    "CI_COMMIT_SHORT_SHA",
    "CI_PROJECT_DIR",
    "CI_PROJECT_NAME",
    "CI_PROJECT_ROOT_NAMESPACE",
    "CI_PROJECT_URL",
    "CI_REGISTRY",
    "SOURCE_PATH",
    "BRANCH",
}


class HarnessError(RuntimeError):
    pass


class GitLabComponentLoader(yaml.SafeLoader):
    pass


def _construct_unknown_tag(loader: yaml.Loader, _tag_suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_scalar(node)


GitLabComponentLoader.add_multi_constructor("!", _construct_unknown_tag)


@dataclass
class Component:
    name: str
    data: dict[str, Any]

    @property
    def template_path(self) -> str:
        return str(self.data["template_path"])

    @property
    def scanner(self) -> str:
        return str(self.data.get("scanner", self.name))

    @property
    def kind(self) -> str:
        return str(self.data.get("kind", "scanner"))


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def read_json_loose(path: Path) -> Any:
    text = path.read_text(encoding="utf-8", errors="replace")
    text = "\n".join(line for line in text.splitlines() if not line.startswith("##tool"))
    return json.loads(text or "null")


def registry_components(registry_path: Path) -> tuple[dict[str, Any], list[Component]]:
    data = load_yaml(registry_path)
    defaults = data.get("defaults", {})
    components = [Component(name, cfg) for name, cfg in (data.get("components") or {}).items()]
    return defaults, components


def output_dir(defaults: dict[str, Any], project_dir: Path | None = None) -> Path:
    path = Path(env_expand(os.environ.get("APPSEC_OUTPUT_DIR", defaults.get("output_dir", ".appsec-results"))))
    if project_dir is not None and not path.is_absolute():
        return (project_dir / path).resolve()
    return path


def user_results_dir(value: str | None, defaults: dict[str, Any], project_dir: Path) -> Path:
    if not value:
        return output_dir(defaults, project_dir)
    path = Path(value)
    return path.resolve() if path.is_absolute() else (project_dir / path).resolve()


def default_reports_dir(defaults: dict[str, Any], project_dir: Path) -> Path:
    return output_dir(defaults, project_dir) / "reports"


def cache_dir(defaults: dict[str, Any], project_dir: Path, out_dir: Path) -> Path:
    path = Path(env_expand(os.environ.get("APPSEC_CACHE_DIR", defaults.get("cache_dir", out_dir / "component-cache"))))
    if not path.is_absolute():
        return (project_dir / path).resolve()
    return path


def env_expand(value: Any, extra: dict[str, str] | None = None) -> Any:
    if not isinstance(value, str):
        return value
    env = dict(os.environ)
    if extra:
        env.update(extra)

    def repl(match: re.Match[str]) -> str:
        braced, default, plain = match.groups()
        key = braced or plain
        if key in env and env[key] != "":
            return env[key]
        return default or ""

    expanded = value
    for _ in range(5):
        next_value = ENV_EXPR_RE.sub(repl, expanded)
        if next_value == expanded:
            return next_value
        expanded = next_value
    return expanded


def substitute_inputs(value: Any, inputs: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return INPUT_EXPR_RE.sub(lambda m: str(inputs.get(m.group(1), "")), value)
    if isinstance(value, list):
        return [substitute_inputs(v, inputs) for v in value if v != ""]
    if isinstance(value, dict):
        return {k: substitute_inputs(v, inputs) for k, v in value.items()}
    return value


def resolve_input_defaults(spec_doc: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    spec_inputs = (((spec_doc or {}).get("spec") or {}).get("inputs") or {})
    for key, meta in spec_inputs.items():
        if isinstance(meta, dict) and "default" in meta:
            result[key] = env_expand(meta["default"])
        else:
            result[key] = ""
    for key, value in overrides.items():
        result[key] = env_expand(value, result)
    return result


def component_enabled(component: Component) -> bool:
    enable_env = component.data.get("enable_env")
    if enable_env:
        return os.environ.get(str(enable_env), "").lower() in {"1", "true", "yes", "on"}
    return bool(component.data.get("default_enabled", True))


def any_path_exists(root: Path, paths: Iterable[str]) -> bool:
    return any((root / p).exists() for p in paths)


def all_paths_exist(root: Path, paths: Iterable[str]) -> bool:
    return all((root / p).exists() for p in paths)


def detector_matches(component: Component, project_dir: Path) -> bool:
    detect = component.data.get("detect") or {}
    if detect.get("any_exists") and not any_path_exists(project_dir, detect["any_exists"]):
        return False
    if detect.get("all_exists") and not all_paths_exist(project_dir, detect["all_exists"]):
        return False
    if detect.get("none_exists") and any_path_exists(project_dir, detect["none_exists"]):
        return False
    env_any = detect.get("env_any_set") or []
    if env_any and not any(os.environ.get(name) for name in env_any):
        return False
    return True


def truthy_env(name: str) -> bool:
    return os.environ.get(name, "").lower() in {"1", "true", "yes", "on"}


def validate_remote_component_source(url: str, ref: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" and parsed.hostname not in LOCAL_TEMPLATE_HOSTS and not truthy_env("APPSEC_ALLOW_INSECURE_COMPONENT_URL"):
        raise HarnessError(
            f"Refusing insecure Chronicle component URL {url!r}. Use HTTPS, "
            "APPSEC_CHRONICLE_LOCAL_DIR, or APPSEC_ALLOW_INSECURE_COMPONENT_URL=true for local testing."
        )
    allowed_hosts = {host.strip().lower() for host in os.environ.get("APPSEC_ALLOWED_COMPONENT_HOSTS", "").split(",") if host.strip()}
    if allowed_hosts and (parsed.hostname or "").lower() not in allowed_hosts:
        raise HarnessError(f"Refusing Chronicle component host {(parsed.hostname or '')!r}; not in APPSEC_ALLOWED_COMPONENT_HOSTS")
    if not PINNED_REF_RE.fullmatch(ref) and not truthy_env("APPSEC_ALLOW_UNPINNED_COMPONENTS"):
        raise HarnessError(
            f"Refusing unpinned Chronicle component ref {ref!r}. Set APPSEC_COMPONENT_REF to a commit SHA, "
            "or use APPSEC_ALLOW_UNPINNED_COMPONENTS=true only for controlled development."
        )


def validate_raw_base(raw_base: str, ref: str) -> None:
    if "{ref}" not in raw_base:
        raise HarnessError("APPSEC_COMPONENT_RAW_BASE must contain {ref} so pinned APPSEC_COMPONENT_REF is used in the fetched URL")
    validate_remote_component_source(raw_base, ref)


def write_template_cache(cache_path: Path, text: str, metadata: dict[str, Any]) -> None:
    try:
        metadata = dict(metadata)
        metadata.setdefault("sha256", hashlib.sha256(text.encode("utf-8")).hexdigest())
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(text, encoding="utf-8")
        write_json(cache_path.with_suffix(cache_path.suffix + ".meta.json"), metadata)
    except OSError as exc:
        print(f"WARNING: unable to write Chronicle template cache at {cache_path}: {exc}", file=sys.stderr)


def fetch_template(component: Component, defaults: dict[str, Any], cache_dir: Path, allow_stale_cache: bool = False) -> tuple[str, str]:
    ref_env = str(defaults.get("ref_env", "APPSEC_COMPONENT_REF"))
    ref = os.environ.get(ref_env, str(defaults.get("ref", "main")))
    template_path = component.template_path
    cache_path = cache_dir / ref / template_path

    local_dir = os.environ.get("APPSEC_CHRONICLE_LOCAL_DIR")
    if local_dir:
        path = Path(local_dir) / template_path
        if path.exists():
            text = path.read_text(encoding="utf-8")
            write_template_cache(cache_path, text, {"source": str(path), "ref": ref, "fetched_at": int(time.time())})
            return text, f"local:{path}"

    raw_base = os.environ.get("APPSEC_COMPONENT_RAW_BASE")
    urls: list[str] = []
    if raw_base:
        validate_raw_base(raw_base, ref)
        base = raw_base.replace("{ref}", urllib.parse.quote(ref, safe=""))
        urls.append(f"{base.rstrip('/')}/{template_path.lstrip('/')}")

    gitlab_url = os.environ.get("APPSEC_GITLAB_URL")
    project = os.environ.get("APPSEC_GITLAB_PROJECT")
    if gitlab_url and project:
        validate_remote_component_source(gitlab_url, ref)
        encoded_project = urllib.parse.quote(project, safe="")
        encoded_path = urllib.parse.quote(template_path, safe="")
        urls.append(
            f"{gitlab_url.rstrip('/')}/api/v4/projects/{encoded_project}/"
            f"repository/files/{encoded_path}/raw?ref={urllib.parse.quote(ref, safe='')}"
        )

    token = os.environ.get("APPSEC_GITLAB_TOKEN")
    headers = {"PRIVATE-TOKEN": token} if token else {}
    errors: list[str] = []
    for url in urls:
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                text = response.read().decode("utf-8")
            source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            write_template_cache(cache_path, text, {"source": url, "ref": ref, "sha256": source_hash, "fetched_at": int(time.time())})
            return text, url
        except (urllib.error.URLError, TimeoutError) as exc:
            errors.append(f"{url}: {exc}")

    if cache_path.exists() and allow_stale_cache:
        text = read_valid_cached_template(cache_path, ref)
        print(f"WARNING: using cached Chronicle template for {component.name}: {cache_path}", file=sys.stderr)
        return text, f"cache:{cache_path}"
    if cache_path.exists():
        raise HarnessError(
            f"Live resolution failed for {component.name}, and stale cache fallback is disabled. "
            "Rerun with --allow-stale-cache only after confirming the cached template is trusted."
        )

    detail = "; ".join(errors) if errors else "no APPSEC_CHRONICLE_LOCAL_DIR, APPSEC_COMPONENT_RAW_BASE, or GitLab API config set"
    raise HarnessError(f"Unable to resolve {component.name} template ({template_path}): {detail}")


def read_valid_cached_template(cache_path: Path, ref: str) -> str:
    meta_path = cache_path.with_suffix(cache_path.suffix + ".meta.json")
    if not meta_path.exists():
        raise HarnessError(f"Cached template is missing metadata: {meta_path}")
    metadata = read_json_loose(meta_path)
    if metadata.get("ref") != ref:
        raise HarnessError(f"Cached template ref mismatch for {cache_path}: expected {ref}, got {metadata.get('ref')}")
    text = cache_path.read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if metadata.get("sha256") != digest:
        raise HarnessError(f"Cached template hash mismatch for {cache_path}; refusing to execute stale cache")
    return text


def load_component_docs(text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        docs = list(yaml.load_all(text, Loader=GitLabComponentLoader))
    except yaml.YAMLError as exc:
        raise HarnessError(f"Unable to parse Chronicle component YAML: {exc}") from exc
    if not docs:
        raise HarnessError("component template is empty")
    spec_doc = docs[0] or {}
    job_doc = docs[1] if len(docs) > 1 else {}
    return spec_doc or {}, job_doc or {}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def resolve_extends(name: str, rendered: dict[str, Any], stack: tuple[str, ...] = ()) -> dict[str, Any]:
    if name in stack:
        raise HarnessError(f"Cycle in GitLab job extends: {' -> '.join(stack + (name,))}")
    job = rendered.get(name)
    if not isinstance(job, dict):
        raise HarnessError(f"GitLab job {name!r} extends missing parent")
    parents = job.get("extends") or []
    if isinstance(parents, str):
        parents = [parents]
    merged: dict[str, Any] = {}
    for parent in parents:
        if parent not in rendered:
            raise HarnessError(f"GitLab job {name!r} extends unknown parent {parent!r}")
        merged = deep_merge(merged, resolve_extends(str(parent), rendered, stack + (name,)))
    child = {k: v for k, v in job.items() if k != "extends"}
    return deep_merge(merged, child)


def looks_like_gitlab_reference(value: Any) -> bool:
    return (
        isinstance(value, list)
        and 2 <= len(value) <= 3
        and all(isinstance(part, str) for part in value)
        and str(value[0]).startswith(".")
    )


def value_at_path(root: dict[str, Any], path: list[str]) -> Any:
    current: Any = root
    for part in path:
        if not isinstance(current, dict) or part not in current:
            raise HarnessError(f"Unable to resolve GitLab !reference path: {path}")
        current = current[part]
    return copy.deepcopy(current)


def resolve_gitlab_references(value: Any, root: dict[str, Any]) -> Any:
    if looks_like_gitlab_reference(value):
        return resolve_gitlab_references(value_at_path(root, [str(part) for part in value]), root)
    if isinstance(value, list):
        resolved: list[Any] = []
        for item in value:
            item = resolve_gitlab_references(item, root)
            if isinstance(item, list):
                resolved.extend(item)
            else:
                resolved.append(item)
        return resolved
    if isinstance(value, dict):
        return {key: resolve_gitlab_references(item, root) for key, item in value.items()}
    return value


def find_scanner_job(job_doc: dict[str, Any], component: Component, inputs: dict[str, Any]) -> dict[str, Any]:
    rendered = substitute_inputs(copy.deepcopy(job_doc), inputs)
    candidates: list[tuple[str, dict[str, Any]]] = []
    for key, value in rendered.items():
        if key in {"include", "stages", "variables", "default", "workflow"} or key.startswith(".") or not isinstance(value, dict):
            continue
        job = resolve_extends(key, rendered)
        if "script" not in job:
            continue
        lower_key = key.lower()
        if "upload" in lower_key or "srm" in lower_key:
            continue
        default = rendered.get("default") if isinstance(rendered.get("default"), dict) else {}
        if default.get("before_script") and "before_script" not in job:
            job["before_script"] = default["before_script"]
        job = resolve_gitlab_references(job, rendered)
        candidates.append((key, job))
    if not candidates:
        raise HarnessError(f"No executable scanner job found in {component.name}")
    job_name, job = candidates[0]
    job["name"] = job_name
    return job


def image_name(job: dict[str, Any], component: Component) -> str:
    override = os.environ.get(f"APPSEC_IMAGE_OVERRIDE_{component.name.upper().replace('-', '_')}")
    if override:
        return override
    image = job.get("image")
    if isinstance(image, dict):
        image = image.get("name")
    if not image:
        image = component.data.get("inputs", {}).get("image")
    if not image:
        raise HarnessError(f"No image resolved for {component.name}")
    return str(env_expand(image))


def validate_image_trust(image: str) -> None:
    registry = image.split("/", 1)[0] if "/" in image else "docker.io"
    allowed = {item.strip().lower() for item in os.environ.get("APPSEC_ALLOWED_IMAGE_REGISTRIES", "").split(",") if item.strip()}
    if allowed and registry.lower() not in allowed:
        raise HarnessError(f"Refusing scanner image {image!r}; registry {registry!r} is not in APPSEC_ALLOWED_IMAGE_REGISTRIES")
    if "@sha256:" not in image and not truthy_env("APPSEC_ALLOW_MUTABLE_IMAGES"):
        raise HarnessError(
            f"Refusing mutable scanner image {image!r}. Use an image digest or set "
            "APPSEC_ALLOW_MUTABLE_IMAGES=true only after accepting scanner image drift risk."
        )


def script_lines(job: dict[str, Any]) -> list[str]:
    script = job.get("script") or []
    return command_lines(script)


def command_lines(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(line) for line in value if str(line).strip()]
    return [str(value)]


def resolve_jobs(args: argparse.Namespace, defaults: dict[str, Any], components: list[Component]) -> list[dict[str, Any]]:
    project_dir = Path(args.project_dir).resolve()
    out_dir = output_dir(defaults, project_dir)
    c_dir = cache_dir(defaults, project_dir, out_dir)
    selected = set(args.component or [])
    jobs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    env_defaults = {
        "CI_PROJECT_DIR": "/workspace",
        "CI_PROJECT_NAME": project_dir.name,
        "CI_PROJECT_ROOT_NAMESPACE": project_dir.parent.name,
        "CI_COMMIT_REF_NAME": current_branch(project_dir),
        "CI_COMMIT_BRANCH": current_branch(project_dir),
        "CI_COMMIT_SHORT_SHA": short_sha(project_dir),
        "SOURCE_PATH": str(defaults.get("source_path", "src")),
        "BRANCH": current_branch(project_dir),
    }

    for key, value in env_defaults.items():
        os.environ.setdefault(key, value)

    for component in components:
        if selected and component.name not in selected:
            continue
        if not selected and not component_enabled(component):
            continue
        if not selected and not detector_matches(component, project_dir):
            continue

        missing_env = [name for name in component.data.get("required_env", []) if not os.environ.get(name)]
        if missing_env and not args.include_unconfigured:
            skipped.append({"component": component.name, "scanner": component.scanner, "kind": component.kind, "reason": "missing_env", "missing_env": missing_env})
            print(f"[{component.name}] skipped: missing env {', '.join(missing_env)}")
            continue

        text, source = fetch_template(component, defaults, c_dir, getattr(args, "allow_stale_cache", False))
        spec_doc, job_doc = load_component_docs(text)
        inputs = resolve_input_defaults(spec_doc, component.data.get("inputs") or {})
        job = find_scanner_job(job_doc, component, inputs)
        jobs.append(
            {
                "component": component.name,
                "scanner": component.scanner,
                "kind": component.kind,
                "template_source": source,
                "inputs": inputs,
                "image": image_name(job, component),
                "job_name": job["name"],
                "before_script": command_lines(job.get("before_script") or []),
                "script": script_lines(job),
                "after_script": command_lines(job.get("after_script") or []),
                "variables": substitute_inputs(job.get("variables") or {}, inputs),
                "artifacts": substitute_inputs(job.get("artifacts") or {}, inputs),
                "required_env": list(component.data.get("required_env", [])),
            }
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    args.appsec_skipped = skipped
    write_json(out_dir / "resolved-jobs.json", redact_job_values(jobs))
    write_json(out_dir / "scan-coverage.json", {"resolved": [job["component"] for job in jobs], "skipped": skipped})
    return jobs


def current_branch(project_dir: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_dir,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return "main"


def short_sha(project_dir: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project_dir,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return "local"


def render_runner(job: dict[str, Any], out_dir: Path) -> Path:
    path = out_dir / f"{job['component']}.sh"
    lines = ["#!/usr/bin/env bash", "set -euo pipefail", "cd /workspace"]
    for key, value in mapping_or_empty(job.get("variables")).items():
        if not ENV_NAME_RE.fullmatch(str(key)):
            raise HarnessError(f"Unsafe environment variable name from {job['component']}: {key!r}")
        lines.append(f"export {key}={shlex.quote(str(value))}")
    after_script = command_lines(job.get("after_script") or [])
    if after_script:
        lines.extend(["__appsec_after_script() {", "  set +e"])
        lines.extend(f"  {line}" for line in after_script)
        lines.extend(["}", "trap __appsec_after_script EXIT"])
    lines.extend(command_lines(job.get("before_script") or []))
    lines.extend(job["script"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path.resolve()


def is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def prepare_scan_workspace(project_dir: Path, out_dir: Path, component: str) -> Path:
    workspace_root = out_dir / "workspaces"
    workspace = workspace_root / component
    if workspace.exists():
        shutil.rmtree(workspace)
    out_dir_resolved = out_dir.resolve()

    def ignore(dir_name: str, names: list[str]) -> set[str]:
        ignored = {".git"}
        current = Path(dir_name).resolve()
        if current == project_dir.resolve() and is_relative_to(out_dir_resolved, project_dir):
            ignored.add(out_dir.name)
        return {name for name in names if name in ignored}

    workspace.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(project_dir, workspace, ignore=ignore)
    return workspace


def artifact_paths(job: dict[str, Any]) -> list[str]:
    artifacts = mapping_or_empty(job.get("artifacts"))
    paths = artifacts.get("paths") or []
    if isinstance(paths, str):
        paths = [paths]
    return [str(path) for path in paths if str(path).strip()]


def is_parseable_report_path(path: Path) -> bool:
    return path.suffix.lower() in PARSEABLE_SUFFIXES


def copy_artifacts(job: dict[str, Any], workspace: Path, reports_dir: Path) -> list[Path]:
    destination = reports_dir / job["component"]
    destination.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for pattern in artifact_paths(job):
        matches = list(workspace.glob(pattern))
        for src in matches:
            if not src.is_file() or not is_parseable_report_path(src):
                continue
            target = destination / src.name
            shutil.copy2(src, target)
            copied.append(target)
    return copied


def run_jobs(jobs: list[dict[str, Any]], project_dir: Path, out_dir: Path, dry_run: bool) -> int:
    if not jobs:
        print("No applicable AppSec scanners resolved.")
        return 0
    exit_code = 0
    reports_dir = out_dir / "reports"
    for job in jobs:
        if not dry_run:
            validate_image_trust(job["image"])
        workspace = project_dir if dry_run else prepare_scan_workspace(project_dir, out_dir, job["component"])
        runner = render_runner(job, out_dir)
        log_path = out_dir / f"{job['component']}.log"
        docker_env = os.environ.copy()
        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{workspace}:/workspace",
            "-v",
            f"{runner}:/appsec-runner.sh:ro",
            "-w",
            "/workspace",
        ]
        variables = mapping_or_empty(job.get("variables"))
        for key in container_env_names(job):
            if key in variables or key in os.environ:
                value = str(variables.get(key, os.environ.get(key, "")))
                docker_env[key] = value
                docker_cmd.extend(["--env", key])
        docker_cmd.extend(["--entrypoint", ""])
        docker_cmd.extend([job["image"], "bash", "/appsec-runner.sh"])
        print(f"[{job['component']}] image={job['image']}")
        if dry_run:
            print(" ".join(sh_quote(part) for part in redact_docker_command(docker_cmd)))
            continue
        with log_path.open("w", encoding="utf-8") as log:
            proc = subprocess.run(docker_cmd, cwd=workspace, env=docker_env, stdout=log, stderr=subprocess.STDOUT)
        copied = copy_artifacts(job, workspace, reports_dir)
        if proc.returncode:
            print(f"[{job['component']}] failed with exit {proc.returncode}; see {log_path}")
            exit_code = proc.returncode if exit_code == 0 else exit_code
        else:
            print(f"[{job['component']}] complete; collected {len(copied)} report artifact(s)")
    return exit_code


def sh_quote(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:=@+-]+", value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"


def mapping_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def container_env_names(job: dict[str, Any]) -> set[str]:
    names = set(DEFAULT_CONTAINER_ENV)
    names.update(mapping_or_empty(job.get("variables")).keys())
    names.update(str(name) for name in job.get("required_env", []))
    return names


def is_secret_name(name: str) -> bool:
    return bool(SECRET_NAME_RE.search(name))


def redact_value(key: str, value: Any) -> Any:
    return "<redacted>" if is_secret_name(key) and value not in (None, "") else value


def secret_values() -> list[str]:
    values = []
    for key, value in os.environ.items():
        if is_secret_name(key) and len(value) >= 4:
            values.append(value)
    return sorted(set(values), key=len, reverse=True)


def redact_job_values(value: Any) -> Any:
    secrets = secret_values()

    def redact(value: Any) -> Any:
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, dict):
            return {key: redact_value(str(key), redact(item)) for key, item in value.items()}
        if isinstance(value, str):
            redacted = value
            for secret in secrets:
                redacted = redacted.replace(secret, "<redacted>")
            return redacted
        return value

    return redact(value)

def redact_docker_command(cmd: list[str]) -> list[str]:
    redacted: list[str] = []
    redact_next_env = False
    for part in cmd:
        if redact_next_env:
            key, sep, value = part.partition("=")
            redacted.append(f"{key}=<redacted>" if sep and is_secret_name(key) and value else part)
            redact_next_env = False
            continue
        redacted.append(part)
        if part == "-e":
            redact_next_env = True
    return redacted


def coverage_findings(skipped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for item in skipped:
        component = item.get("component", "scanner")
        missing = ", ".join(item.get("missing_env") or [])
        findings.append(
            new_finding(
                "appsec-harness",
                f"Scanner skipped: {component}",
                "HIGH",
                {"file": "appsec scan configuration"},
                {"rule_id": "APPSEC-SCANNER-SKIPPED", "component": component, "missing_env": missing, "reason": item.get("reason")},
            )
        )
    return findings


def report_coverage_findings(jobs: list[dict[str, Any]], reports_dir: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for job in jobs:
        expected = [path for path in artifact_paths(job) if Path(path).suffix.lower() in PARSEABLE_SUFFIXES]
        component_reports_dir = reports_dir / job["component"]
        found = list(component_reports_dir.rglob("*")) if component_reports_dir.exists() else []
        found = [path for path in found if path.is_file() and is_parseable_report_path(path)]
        if not expected:
            findings.append(
                new_finding(
                    "appsec-harness",
                    f"No parseable report declared: {job['component']}",
                    "HIGH",
                    {"file": "appsec scan configuration"},
                    {"rule_id": "APPSEC-REPORT-NOT-DECLARED", "component": job["component"]},
                )
            )
        elif not found:
            findings.append(
                new_finding(
                    "appsec-harness",
                    f"Scanner report missing: {job['component']}",
                    "HIGH",
                    {"file": "appsec scan results"},
                    {"rule_id": "APPSEC-REPORT-MISSING", "component": job["component"], "expected": ", ".join(expected)},
                )
            )
    return findings


def fingerprint(parts: Iterable[Any]) -> str:
    raw = "|".join(str(p or "") for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def normalize_severity(value: Any) -> str:
    if value is None:
        return "UNKNOWN"
    text = str(value).strip().upper()
    aliases = {"ERROR": "HIGH", "FATAL": "CRITICAL", "WARN": "MEDIUM", "WARNING": "MEDIUM", "INFO": "INFO", "INFORMATIONAL": "INFO"}
    if text in aliases:
        return aliases[text]
    try:
        numeric = float(text)
    except ValueError:
        return text
    if numeric >= 4:
        return "CRITICAL"
    if numeric >= 3:
        return "HIGH"
    if numeric >= 2:
        return "MEDIUM"
    if numeric >= 1:
        return "LOW"
    return "INFO"


def new_finding(scanner: str, name: str, severity: str, location: dict[str, Any] | None, evidence: dict[str, Any]) -> dict[str, Any]:
    location = location or {}
    normalized = normalize_severity(severity)
    return {
        "id": fingerprint([scanner, name, normalized, location.get("file"), location.get("line"), evidence.get("rule_id"), evidence.get("package")]),
        "scanner": scanner,
        "name": name,
        "severity": normalized,
        "location": location,
        "evidence": evidence,
        "verification_status": "unverified",
        "remediation_status": "unassessed",
    }


def normalize_reports(results_dir: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in sorted(results_dir.rglob("*")):
        if not path.is_file():
            continue
        name = path.name.lower()
        if name in HARNESS_JSON_FILES:
            continue
        try:
            if name == "pylint-report.json":
                findings.extend(parse_pylint(path))
            elif name == "eslint.json" or name == "eslint-report.json":
                findings.extend(parse_eslint(path))
            elif name.endswith(".json"):
                data = read_json_loose(path)
                parsed = parse_generic_json(path, data)
                findings.extend(parsed)
                if not parsed and not is_supported_clean_json(data):
                    findings.append(unsupported_report_finding(path, "Unsupported JSON scanner report schema"))
            elif name.endswith(".xml") or name.endswith(".fvdl"):
                parsed = parse_generic_xml(path)
                findings.extend(parsed)
                if not parsed:
                    findings.append(unsupported_report_finding(path, "Unsupported XML scanner report schema"))
            elif name.endswith(".fpr"):
                parsed = parse_fpr(path)
                findings.extend(parsed)
                if not parsed:
                    findings.append(unsupported_report_finding(path, "No parseable findings found in FPR report"))
        except Exception as exc:  # Keep normalization robust across vendor formats.
            findings.append(
                new_finding(
                    "normalizer",
                    f"Failed to parse {path.name}",
                    "HIGH",
                    {"file": str(path)},
                    {"rule_id": "APPSEC-REPORT-PARSE-FAILED", "error": str(exc), "raw_report": str(path)},
                )
            )
    return findings


def unsupported_report_finding(path: Path, message: str) -> dict[str, Any]:
    return new_finding(
        "normalizer",
        message,
        "HIGH",
        {"file": str(path)},
        {"rule_id": "APPSEC-REPORT-UNSUPPORTED", "raw_report": str(path)},
    )


def is_supported_clean_json(data: Any) -> bool:
    if data in (None, [], {}):
        return True
    return isinstance(data, dict) and (
        isinstance(data.get("vulnerabilities"), list)
        or isinstance(data.get("Results"), list)
        or isinstance(data.get("results"), list)
    )


def parse_pylint(path: Path) -> list[dict[str, Any]]:
    data = read_json_loose(path)
    findings = []
    for item in data or []:
        msg_id = item.get("message-id") or item.get("symbol") or item.get("type")
        findings.append(
            new_finding(
                "pylint",
                item.get("message") or msg_id or "Pylint finding",
                item.get("type", "INFO"),
                {"file": item.get("path") or item.get("module"), "line": item.get("line")},
                {"rule_id": msg_id, "raw_report": str(path)},
            )
        )
    return findings


def parse_eslint(path: Path) -> list[dict[str, Any]]:
    data = read_json_loose(path)
    findings = []
    for result in data or []:
        file_path = result.get("filePath")
        for msg in result.get("messages", []):
            severity = "HIGH" if msg.get("severity") == 2 else "MEDIUM"
            findings.append(
                new_finding(
                    "eslint",
                    msg.get("message") or msg.get("ruleId") or "ESLint finding",
                    severity,
                    {"file": file_path, "line": msg.get("line"), "column": msg.get("column")},
                    {"rule_id": msg.get("ruleId"), "raw_report": str(path)},
                )
            )
    return findings


def parse_generic_json(path: Path, data: Any) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if isinstance(data, dict) and isinstance(data.get("vulnerabilities"), list):
        scanner = ((data.get("scan") or {}).get("scanner") or {}).get("id") or path.stem
        for vuln in data["vulnerabilities"]:
            loc = vuln.get("location") or {}
            location = {
                "file": loc.get("file") or loc.get("dependency", {}).get("package", {}).get("name") or loc.get("path"),
                "line": loc.get("start_line") or loc.get("line"),
                "url": loc.get("url"),
            }
            identifiers = vuln.get("identifiers") or []
            rule_id = identifiers[0].get("value") if identifiers and isinstance(identifiers[0], dict) else None
            findings.append(
                new_finding(
                    scanner,
                    vuln.get("name") or vuln.get("message") or "Security finding",
                    vuln.get("severity", "UNKNOWN"),
                    location,
                    {"rule_id": rule_id, "raw_report": str(path), "description": vuln.get("description"), "solution": vuln.get("solution")},
                )
            )
    if isinstance(data, dict) and isinstance(data.get("Results"), list):
        for result in data.get("Results", []):
            target = result.get("Target")
            for vuln in result.get("Vulnerabilities") or []:
                findings.append(
                    new_finding(
                        "trivy",
                        vuln.get("Title") or vuln.get("VulnerabilityID") or "Container vulnerability",
                        vuln.get("Severity", "UNKNOWN"),
                        {"file": target},
                        {
                            "rule_id": vuln.get("VulnerabilityID"),
                            "package": vuln.get("PkgName"),
                            "installed_version": vuln.get("InstalledVersion"),
                            "fixed_version": vuln.get("FixedVersion"),
                            "raw_report": str(path),
                        },
                    )
                )
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        for item in data.get("results", []):
            findings.append(
                new_finding(
                    "prisma-cloud",
                    item.get("title") or item.get("id") or "Prisma Cloud finding",
                    item.get("severity", "UNKNOWN"),
                    {"file": item.get("packageName") or item.get("resource")},
                    {"rule_id": item.get("id"), "raw_report": str(path), "package": item.get("packageName")},
                )
            )
    return findings


def parse_generic_xml(path: Path) -> list[dict[str, Any]]:
    root = ET.parse(path).getroot()
    tag = strip_ns(root.tag).lower()
    if tag == "fvdl":
        return parse_fvdl_root(root, path)
    findings: list[dict[str, Any]] = []
    for elem in root.iter():
        elem_tag = strip_ns(elem.tag).lower()
        if elem_tag in {"violation", "rule", "issue", "vulnerability"}:
            name = first_text(elem, ["Name", "RuleID", "rule", "message", "Category"]) or elem_tag
            severity = first_text(elem, ["Severity", "severity", "Priority", "priority"]) or elem.get("severity") or elem.get("id") or "UNKNOWN"
            file_name = first_text(elem, ["File", "FileName", "file", "Path"]) or elem.get("file")
            line = first_text(elem, ["Line", "LineStart", "line"]) or elem.get("line")
            findings.append(new_finding(path.stem, name, severity, {"file": file_name, "line": line}, {"raw_report": str(path)}))
    return findings


def parse_fpr(path: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            lower = name.lower()
            if lower.endswith(".fvdl"):
                with zf.open(name) as f:
                    root = ET.parse(f).getroot()
                findings.extend(parse_fvdl_root(root, path))
            elif lower.endswith(".xml") and "webinspect" in lower:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xml")
                try:
                    tmp.write(zf.read(name))
                    tmp.close()
                    findings.extend(parse_generic_xml(Path(tmp.name)))
                finally:
                    Path(tmp.name).unlink(missing_ok=True)
    return findings


def parse_fvdl_root(root: ET.Element, path: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for vuln in root.iter():
        if strip_ns(vuln.tag) != "Vulnerability":
            continue
        class_info = child_by_name(vuln, "ClassInfo")
        instance = child_by_name(vuln, "InstanceInfo")
        name = first_text(class_info, ["Type", "Subtype", "Kingdom"]) if class_info is not None else None
        severity = first_text(class_info, ["DefaultSeverity", "Friority", "Priority"]) if class_info is not None else None
        file_name = first_text(instance, ["FileName", "FunctionDeclarationSourceLocation/Path"]) if instance is not None else None
        line = first_text(instance, ["LineStart", "FunctionDeclarationSourceLocation/Line"]) if instance is not None else None
        findings.append(
            new_finding(
                "fortify",
                name or "Fortify vulnerability",
                severity or "HIGH",
                {"file": file_name, "line": line},
                {"rule_id": first_text(class_info, ["ClassID"]) if class_info is not None else None, "raw_report": str(path)},
            )
        )
    return findings


def strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child_by_name(elem: ET.Element, name: str) -> ET.Element | None:
    for child in elem:
        if strip_ns(child.tag) == name:
            return child
    return None


def first_text(elem: ET.Element | None, names: list[str]) -> str | None:
    if elem is None:
        return None
    for name in names:
        node = elem.find(name)
        if node is None:
            for candidate in elem.iter():
                if strip_ns(candidate.tag) == name:
                    node = candidate
                    break
        if node is not None and node.text:
            return node.text.strip()
    return None


def triage_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for finding in findings:
        location = finding.get("location") or {}
        evidence = finding.get("evidence") or {}
        path = str(location.get("file") or "").replace("\\", "/").lower()
        path_parts = [part for part in path.split("/") if part]
        severity = normalize_severity(finding.get("severity"))
        if finding.get("scanner") == "appsec-harness" and evidence.get("rule_id") == "APPSEC-SCANNER-SKIPPED":
            finding["verification_status"] = "needs_human_review"
            finding["remediation_status"] = "configuration_required"
            finding["triage_reason"] = "A matching scanner could not run because required environment variables are missing."
        elif evidence.get("rule_id") in {"APPSEC-REPORT-PARSE-FAILED", "APPSEC-REPORT-UNSUPPORTED", "APPSEC-REPORT-NOT-DECLARED", "APPSEC-REPORT-MISSING"}:
            finding["verification_status"] = "needs_human_review"
            finding["remediation_status"] = "parser_or_report_fix_required"
            finding["triage_reason"] = "Scanner output could not be collected or parsed; treat coverage as incomplete."
        elif evidence.get("fixed_version") == "":
            finding["verification_status"] = "not_fixable_locally"
            finding["remediation_status"] = "blocked_external_dependency"
            finding["triage_reason"] = "No fixed version is reported by the scanner."
        elif finding.get("scanner") in {"pylint", "eslint"} and any(part in path_parts for part in ["test", "tests", "__tests__", "fixtures", "vendor", "node_modules", "dist", "build"]):
            finding["verification_status"] = "likely_false_positive"
            finding["remediation_status"] = "needs_user_decision"
            finding["triage_reason"] = "Finding is in generated, dependency, fixture, or test-only code."
        elif severity in {"CRITICAL", "HIGH"} and (location.get("file") or location.get("url") or evidence.get("package")):
            finding["verification_status"] = "confirmed_true_positive"
            finding["remediation_status"] = "fixable_candidate"
            finding["triage_reason"] = "High-impact finding includes concrete location or package evidence."
        elif finding.get("scanner") in {"pylint", "eslint"}:
            finding["verification_status"] = "confirmed_true_positive"
            finding["remediation_status"] = "fixable_candidate"
            finding["triage_reason"] = "Static lint finding maps to a concrete rule and file location."
        else:
            finding["verification_status"] = "needs_human_review"
            finding["remediation_status"] = "unassessed"
            finding["triage_reason"] = "Evidence is insufficient for automatic classification."
    return findings


def gate_failed(findings: list[dict[str, Any]], defaults: dict[str, Any]) -> bool:
    gate = defaults.get("ci_gate") or {}
    severities = {normalize_severity(s) for s in gate.get("severities", ["CRITICAL", "HIGH"])}
    for finding in findings:
        if normalize_severity(finding.get("severity")) in severities:
            return True
    return False


def print_summary(findings: list[dict[str, Any]]) -> None:
    counts: dict[tuple[str, str], int] = {}
    for finding in findings:
        key = (normalize_severity(finding.get("severity")), str(finding.get("verification_status", "unverified")))
        counts[key] = counts.get(key, 0) + 1
    print("AppSec finding summary:")
    if not counts:
        print("  No findings parsed.")
        return
    for (severity, status), count in sorted(counts.items(), key=lambda item: (-SEVERITY_ORDER.get(item[0][0], -1), item[0][1])):
        print(f"  {severity:9s} {status:24s} {count}")


def ensure_remediation_branch(project_dir: Path) -> str:
    branch = current_branch(project_dir)
    if branch.startswith("appsec/remediate/"):
        return branch
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-") or "work"
    new_branch = f"appsec/remediate/{base}-{time.strftime('%Y%m%d%H%M%S')}"
    subprocess.check_call(["git", "checkout", "-b", new_branch], cwd=project_dir)
    return new_branch


def cmd_resolve(args: argparse.Namespace) -> int:
    defaults, components = registry_components(Path(args.registry))
    jobs = resolve_jobs(args, defaults, components)
    print(f"Resolved {len(jobs)} scanner job(s).")
    for job in jobs:
        print(f"  - {job['component']}: {job['image']} ({job['template_source']})")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    defaults, components = registry_components(Path(args.registry))
    jobs = resolve_jobs(args, defaults, components)
    project_dir = Path(args.project_dir).resolve()
    out_dir = output_dir(defaults, project_dir)
    scan_exit = run_jobs(jobs, project_dir, out_dir, args.dry_run)
    if args.dry_run:
        return scan_exit
    reports_dir = out_dir / "reports"
    findings = triage_findings(
        coverage_findings(getattr(args, "appsec_skipped", []))
        + report_coverage_findings(jobs, reports_dir)
        + normalize_reports(reports_dir)
    )
    write_json(out_dir / "findings.normalized.json", findings)
    write_json(out_dir / "findings.triaged.json", findings)
    print_summary(findings)
    if args.gate == "ci" and gate_failed(findings, defaults):
        return scan_exit or 2
    return scan_exit


def cmd_normalize(args: argparse.Namespace) -> int:
    defaults, _ = registry_components(Path(args.registry))
    project_dir = Path(args.project_dir).resolve()
    scan_out = output_dir(defaults, project_dir)
    reports_dir = user_results_dir(args.results_dir, defaults, project_dir) if args.results_dir else default_reports_dir(defaults, project_dir)
    write_dir = reports_dir if args.results_dir else scan_out
    findings = normalize_reports(reports_dir)
    write_json(write_dir / "findings.normalized.json", findings)
    print_summary(findings)
    return 0


def cmd_triage(args: argparse.Namespace) -> int:
    defaults, _ = registry_components(Path(args.registry))
    project_dir = Path(args.project_dir).resolve()
    scan_out = output_dir(defaults, project_dir)
    reports_dir = user_results_dir(args.results_dir, defaults, project_dir) if args.results_dir else default_reports_dir(defaults, project_dir)
    write_dir = reports_dir if args.results_dir else scan_out
    input_path = write_dir / "findings.normalized.json"
    findings = read_json_loose(input_path) if input_path.exists() else normalize_reports(reports_dir)
    triaged = triage_findings(findings)
    write_json(write_dir / "findings.triaged.json", triaged)
    print_summary(triaged)
    return 2 if args.gate == "ci" and gate_failed(triaged, defaults) else 0


def cmd_prepare_branch(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    if not shutil.which("git"):
        raise HarnessError("git is required for remediation branch creation")
    if not args.allow_dirty and not is_clean_worktree(project_dir):
        raise HarnessError("Refusing to create remediation branch with uncommitted changes. Commit/stash first, or rerun with --allow-dirty.")
    branch = ensure_remediation_branch(project_dir)
    print(f"Remediation branch: {branch}")
    print("Claude Code should make fixes in this branch, then repeat the scan with: appsec_harness.py run --gate ci")
    return 0


def is_clean_worktree(project_dir: Path) -> bool:
    try:
        status = subprocess.check_output(["git", "status", "--porcelain"], cwd=project_dir, text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        raise HarnessError(f"{project_dir} is not a git repository")
    return status.strip() == ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run local Chronicle AppSec scanner harness")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY), help="Component registry YAML")
    parser.add_argument("--project-dir", default=".", help="Project directory to scan")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_resolve_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument("--component", action="append", help="Run only this component; may be repeated")
        p.add_argument("--include-unconfigured", action="store_true", help="Resolve components even when required env is missing")
        p.add_argument("--allow-stale-cache", action="store_true", help="Use a cached Chronicle template when live resolution fails")

    p_resolve = sub.add_parser("resolve", help="Resolve current Chronicle scanner jobs")
    add_resolve_flags(p_resolve)
    p_resolve.set_defaults(func=cmd_resolve)

    p_run = sub.add_parser("run", help="Resolve and run applicable scanners")
    add_resolve_flags(p_run)
    p_run.add_argument("--dry-run", action="store_true", help="Print Docker commands without running scanners")
    p_run.add_argument("--gate", choices=["none", "ci"], default="ci", help="Exit non-zero when CI-equivalent gate fails")
    p_run.set_defaults(func=cmd_run)

    p_norm = sub.add_parser("normalize", help="Normalize existing scanner reports")
    p_norm.add_argument("--results-dir")
    p_norm.set_defaults(func=cmd_normalize)

    p_triage = sub.add_parser("triage", help="Triage normalized findings")
    p_triage.add_argument("--results-dir")
    p_triage.add_argument("--gate", choices=["none", "ci"], default="none")
    p_triage.set_defaults(func=cmd_triage)

    p_branch = sub.add_parser("prepare-branch", help="Create or reuse a local AppSec remediation branch")
    p_branch.add_argument("--allow-dirty", action="store_true", help="Create the branch even when the worktree has uncommitted changes")
    p_branch.set_defaults(func=cmd_prepare_branch)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except HarnessError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
