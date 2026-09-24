#!/usr/bin/env python3
"""Hermetic tests for scripts/remote-match.sh (GitLab-native remote dependency
scanning via the appsec-sbom-matcher helper project). curl is stubbed with a
tiny Python script driven by a per-test JSON scenario file; git is real
(git init in a temp dir is enough for `git ls-files --others` to work)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "remote-match.sh"

INSTANCE = "https://gitlab.example.com"
MATCHER_PROJECT = "44"
TOKEN = "dummy-test-token"

CURL_STUB = '''#!/usr/bin/env python3
import json, os, re, sys

args = sys.argv[1:]
method = "GET"
opts = {}
i = 0
positional = []
while i < len(args):
    a = args[i]
    if a == "-X":
        method = args[i + 1]; i += 2; continue
    if a == "-o":
        opts["o"] = args[i + 1]; i += 2; continue
    if a in ("-w", "--max-time", "--retry", "-H"):
        i += 2; continue
    if a == "--config":
        opts["config"] = args[i + 1]; i += 2; continue
    if a == "--upload-file":
        opts["upload_file"] = args[i + 1]; method = "PUT"; i += 2; continue
    if a == "--data-binary":
        opts["data_binary"] = args[i + 1]; method = "POST"; i += 2; continue
    if a in ("-sS", "-s", "-S"):
        i += 1; continue
    if a.startswith("-"):
        i += 1; continue
    positional.append(a); i += 1

url = positional[-1] if positional else ""

log_path = os.environ.get("FAKE_CURL_LOG")
if log_path:
    with open(log_path, "a") as fh:
        fh.write(json.dumps(args) + "\\n")

if method == "PUT" and "/packages/generic/appsec-bundles/" in url and url.endswith("/bundle.tar.gz"):
    kind = "put"
elif method == "POST" and url.endswith("/pipeline"):
    kind = "trigger"
elif re.search(r"/pipelines/[^/]+/jobs$", url):
    kind = "jobs"
elif re.search(r"/pipelines/[^/]+$", url):
    kind = "poll"
elif re.search(r"/jobs/[^/]+/artifacts/gl-dependency-scanning-report\\.json$", url):
    kind = "artifact"
elif re.search(r"/jobs/[^/]+/trace$", url):
    kind = "trace"
elif "/packages?package_name=" in url:
    kind = "packages_list"
elif method == "DELETE" and re.search(r"/packages/[^/]+$", url):
    kind = "delete"
else:
    kind = "unknown"

script = json.load(open(os.environ["FAKE_CURL_SCRIPT"]))
entry = script.get(kind, {"status": 404, "body": ""})
status = entry.get("status", 200)
body = entry.get("body", "")

outfile = opts.get("o")
if outfile:
    with open(outfile, "w") as fh:
        if isinstance(body, (dict, list)):
            json.dump(body, fh)
        else:
            fh.write(body if isinstance(body, str) else "")

sys.stdout.write(str(status))
sys.exit(0)
'''


def scenario(**overrides):
    base = {
        "put": {"status": 201, "body": ""},
        "trigger": {
            "status": 201,
            "body": {"id": 123, "web_url": f"{INSTANCE}/platform-engineering/skillshub/appsec-sbom-matcher/-/pipelines/123"},
        },
        "poll": {"status": 200, "body": {"status": "success"}},
        "jobs": {"status": 200, "body": [{"name": "dependency-scanning", "id": 555, "status": "success"}]},
        "artifact": {"status": 200, "body": {"vulnerabilities": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}},
        "packages_list": {"status": 200, "body": [{"id": 999}]},
        "delete": {"status": 202, "body": ""},
        "trace": {
            "status": 200,
            "body": "Running job\nresolution-job: image pull denied for registry/toolbox:1\nERROR: job failed\n",
        },
    }
    base.update(overrides)
    return base


class RemoteMatchTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="remote-match-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.repo = root / "repo"
        self.results = root / "results"
        self.bin_dir = root / "bin"
        self.repo.mkdir()
        self.results.mkdir()
        self.bin_dir.mkdir()

        curl_path = self.bin_dir / "curl"
        curl_path.write_text(CURL_STUB)
        curl_path.chmod(0o755)

        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)

        self.scenario_path = root / "scenario.json"
        self.log_path = root / "curl.log"

        self.env = os.environ.copy()
        self.env["PATH"] = f"{self.bin_dir}{os.pathsep}{self.env.get('PATH', '')}"
        self.env["APPSEC_RESOLVED_TOKEN"] = TOKEN
        self.env["FAKE_CURL_SCRIPT"] = str(self.scenario_path)
        self.env["FAKE_CURL_LOG"] = str(self.log_path)
        # Force a clean environment for the resolvers: no download URL, so
        # they only ever use jq/python3 already on PATH (never our fake curl).
        self.env["JQ_INSTALL_URL"] = ""
        self.env["PYTHON_INSTALL_URL"] = ""

    def write_files(self, files: dict[str, str]) -> None:
        for rel, content in files.items():
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)

    def write_scenario(self, data: dict) -> None:
        self.scenario_path.write_text(json.dumps(data))

    def run_script(self, *extra_args: str) -> subprocess.CompletedProcess[str]:
        cmd = [
            "bash", str(SCRIPT),
            "--project-dir", str(self.repo),
            "--results", str(self.results),
            "--instance", INSTANCE,
            "--matcher-project", MATCHER_PROJECT,
        ] + list(extra_args)
        return subprocess.run(cmd, env=self.env, text=True, capture_output=True, check=False)

    def result_json(self, lang: str) -> dict:
        return json.loads((self.results / "remote-ds" / lang / "result.json").read_text())

    def manifest_lines(self, lang: str) -> set[str]:
        text = (self.results / "remote-ds" / lang / "bundle-manifest.txt").read_text()
        return {line for line in text.splitlines() if line}

    def call_args(self) -> list[list[str]]:
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text().splitlines() if line]

    @staticmethod
    def method_url(args: list[str]) -> tuple[str, str]:
        m = args[args.index("-X") + 1] if "-X" in args else "GET"
        url = args[-1] if args else ""
        return m, url

    def has_call(self, calls: list[list[str]], method: str, url_suffix: str) -> bool:
        for args in calls:
            m, url = self.method_url(args)
            if m == method and url.endswith(url_suffix):
                return True
        return False


JAVASCRIPT_FILES = {
    "package.json": "{}",
    "package-lock.json": "{}",
    "src/index.js": "console.log('hi');\n",
    "node_modules/foo/package.json": "{}",
}


class BundleContentsTests(RemoteMatchTestCase):
    def test_bundle_contains_only_manifests_no_source_across_all_languages(self) -> None:
        self.write_files({
            **JAVASCRIPT_FILES,
            "requirements.txt": "flask==2.0\n",
            "pyproject.toml": "[project]\nname = 'x'\n",
            "app.py": "print('hi')\n",
            ".venv/lib/site.py": "print('nope')\n",
            "pom.xml": "<project/>",
            ".mvn/wrapper/maven-wrapper.properties": "distributionUrl=x\n",
            "src/main/java/App.java": "class App {}\n",
            "build.gradle": "// gradle\n",
            "settings.gradle": "// settings\n",
            "gradle.properties": "org.gradle.x=1\n",
            "gradle/wrapper/gradle-wrapper.properties": "x=1\n",
            "src/main/App.kt": "fun main() {}\n",
            "go.mod": "module example.com/x\n",
            "go.sum": "\n",
            "main.go": "package main\n",
        })
        self.write_scenario(scenario(put={"status": 401, "body": ""}))

        result = self.run_script()

        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertEqual(self.manifest_lines("javascript"), {"package.json", "package-lock.json"})
        self.assertEqual(self.manifest_lines("python"), {"requirements.txt", "pyproject.toml"})
        self.assertEqual(self.manifest_lines("maven"), {"pom.xml", ".mvn/wrapper/maven-wrapper.properties"})
        self.assertEqual(
            self.manifest_lines("gradle"),
            {"build.gradle", "settings.gradle", "gradle.properties", "gradle/wrapper/gradle-wrapper.properties"},
        )
        self.assertEqual(self.manifest_lines("go"), {"go.mod", "go.sum"})


class HappyPathTests(RemoteMatchTestCase):
    def test_upload_trigger_poll_report_happy_path(self) -> None:
        self.write_files(JAVASCRIPT_FILES)
        self.write_scenario(scenario())

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("REMOTE-MATCH: language=javascript status=ok findings=3 pipeline=", result.stdout)
        self.assertNotIn("REMOTE-MATCH-REASON", result.stdout)

        data = self.result_json("javascript")
        self.assertEqual(data["language"], "javascript")
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["pipeline_id"], "123")
        self.assertEqual(data["job_status"], "success")
        self.assertEqual(data["findings"], 3)
        self.assertEqual(data["reason"], "")
        self.assertTrue(data["bundle_id"].startswith("javascript-"))
        self.assertGreaterEqual(data["duration_s"], 0)

        report = self.results / "remote-ds" / "javascript" / "gl-dependency-scanning-report.json"
        self.assertEqual(json.loads(report.read_text()), {"vulnerabilities": [{"id": "a"}, {"id": "b"}, {"id": "c"}]})
        self.assertFalse((self.results / "remote-ds" / "javascript" / ".tmp").exists())


class JobFailureTests(RemoteMatchTestCase):
    def test_allow_failure_job_failed_while_pipeline_success(self) -> None:
        self.write_files(JAVASCRIPT_FILES)
        self.write_scenario(scenario(
            jobs={"status": 200, "body": [{"name": "dependency-scanning", "id": 555, "status": "failed"}]},
        ))

        result = self.run_script()

        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        self.assertIn("REMOTE-MATCH: language=javascript status=failed findings=0 pipeline=", result.stdout)
        self.assertIn("REMOTE-MATCH-REASON: language=javascript", result.stdout)
        self.assertIn("image pull denied", result.stdout)

        data = self.result_json("javascript")
        self.assertEqual(data["status"], "failed")
        self.assertEqual(data["job_status"], "failed")
        self.assertIn("image pull denied", data["reason"])

    def test_fetch_bundle_failure_marks_scan_job_skipped(self) -> None:
        self.write_files(JAVASCRIPT_FILES)
        self.write_scenario(scenario(
            jobs={
                "status": 200,
                "body": [
                    {"name": "dependency-scanning", "id": 555, "status": "skipped"},
                    {"name": "fetch-bundle", "id": 556, "status": "failed"},
                ],
            },
        ))

        result = self.run_script()

        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        data = self.result_json("javascript")
        self.assertEqual(data["status"], "failed")
        self.assertEqual(data["job_status"], "skipped")
        self.assertIn("fetch-bundle failed", data["reason"])
        self.assertIn("image pull denied", data["reason"])


class TimeoutTests(RemoteMatchTestCase):
    def test_pipeline_never_terminal_times_out(self) -> None:
        self.write_files(JAVASCRIPT_FILES)
        self.write_scenario(scenario(poll={"status": 200, "body": {"status": "running"}}))

        result = self.run_script("--timeout", "2", "--poll", "1")

        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        self.assertIn("REMOTE-MATCH: language=javascript status=timeout findings=0 pipeline=", result.stdout)
        data = self.result_json("javascript")
        self.assertEqual(data["status"], "timeout")
        self.assertIn("did not reach a terminal state within 2s", data["reason"])


class UploadFailureTests(RemoteMatchTestCase):
    def test_401_on_upload_exits_3_before_any_pipeline(self) -> None:
        self.write_files(JAVASCRIPT_FILES)
        self.write_scenario(scenario(put={"status": 401, "body": ""}))

        result = self.run_script()

        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("REMOTE-MATCH: language=javascript status=error findings=0 pipeline=", result.stdout)
        self.assertIn("401", result.stdout)
        data = self.result_json("javascript")
        self.assertEqual(data["status"], "error")
        self.assertIn("401", data["reason"])

        log_lines = self.log_path.read_text().splitlines()
        self.assertEqual(len(log_lines), 1, "only the failed upload should have been attempted")


class CleanupTests(RemoteMatchTestCase):
    def test_delete_403_is_advisory_not_fatal(self) -> None:
        self.write_files(JAVASCRIPT_FILES)
        self.write_scenario(scenario(delete={"status": 403, "body": ""}))

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ADVISORY: could not delete bundle", result.stdout)
        self.assertIn("needs Maintainer", result.stdout)
        data = self.result_json("javascript")
        self.assertEqual(data["status"], "ok")


class GradleLockfileScopeTests(RemoteMatchTestCase):
    def test_bundle_includes_only_gradle_dependency_lock_files(self) -> None:
        # A bare `*.lockfile` glob used to sweep up any file with that suffix
        # anywhere in the repo, not just gradle's own dependency-locks plugin
        # output -- e.g. another tool's *.lockfile sitting elsewhere.
        self.write_files({
            "build.gradle": "// gradle\n",
            "gradle.lockfile": "root lockfile\n",
            "gradle/dependency-locks/compileClasspath.lockfile": "locked\n",
            "some-other-tool/random.lockfile": "not ours\n",
        })
        self.write_scenario(scenario(put={"status": 401, "body": ""}))

        result = self.run_script()

        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertEqual(
            self.manifest_lines("gradle"),
            {
                "build.gradle",
                "gradle.lockfile",
                "gradle/dependency-locks/compileClasspath.lockfile",
            },
        )


class BundleSizeCapTests(RemoteMatchTestCase):
    def test_bundle_over_cap_is_an_error_and_nothing_is_uploaded(self) -> None:
        self.write_files(JAVASCRIPT_FILES)
        self.write_scenario(scenario())
        self.env["APPSEC_REMOTE_MATCH_MAX_BYTES"] = "1"

        result = self.run_script()

        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        data = self.result_json("javascript")
        self.assertEqual(data["status"], "error")
        self.assertIn("cap", data["reason"])
        self.assertFalse(self.log_path.exists(), "nothing should have been uploaded")


class InterruptCleanupTests(RemoteMatchTestCase):
    def test_sigterm_while_polling_deletes_bundle_and_cancels_pipeline(self) -> None:
        # A pipeline that never reaches a terminal state keeps poll_all_pending's
        # loop alive (--poll 1 keeps that loop fast) long enough to send it a
        # real SIGTERM mid-wait -- the trap installed in Main must still
        # delete the already-uploaded bundle and cancel the pipeline it
        # triggered, not just abandon both on the matcher project.
        self.write_files(JAVASCRIPT_FILES)
        self.write_scenario(scenario(poll={"status": 200, "body": {"status": "running"}}))

        cmd = [
            "bash", str(SCRIPT),
            "--project-dir", str(self.repo),
            "--results", str(self.results),
            "--instance", INSTANCE,
            "--matcher-project", MATCHER_PROJECT,
            "--poll", "1",
        ]
        proc = subprocess.Popen(
            cmd, env=self.env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            # Wait until upload + trigger + at least one poll have happened,
            # i.e. the script is now inside poll_all_pending's loop.
            deadline = time.time() + 10
            while time.time() < deadline and len(self.call_args()) < 3:
                time.sleep(0.05)
            self.assertGreaterEqual(
                len(self.call_args()), 3, "script never reached the poll loop"
            )

            proc.send_signal(signal.SIGTERM)
            stdout, stderr = proc.communicate(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()

        self.assertEqual(proc.returncode, 143, stdout + stderr)
        calls = self.call_args()
        self.assertTrue(
            self.has_call(calls, "DELETE", "/packages/999"),
            f"expected a DELETE cleaning up the in-flight bundle in {calls}",
        )
        self.assertTrue(
            any(a.endswith("/cancel") for args in calls for a in args),
            f"expected a POST .../cancel for the in-flight pipeline in {calls}",
        )


PYTHON_FILES = {"requirements.txt": "flask==2.0\n"}


class ConcurrentTriggerTests(RemoteMatchTestCase):
    def test_two_languages_upload_and_trigger_before_first_poll(self) -> None:
        # Phase 1 (build/upload/trigger) must run for every language before
        # phase 2 starts polling any of them -- that's what makes the
        # pipelines run concurrently on the matcher project instead of one
        # after another.
        self.write_files({**JAVASCRIPT_FILES, **PYTHON_FILES})
        self.write_scenario(scenario())

        result = self.run_script("--language", "javascript", "--language", "python")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        kinds = []
        for args in self.call_args():
            m, url = self.method_url(args)
            if m == "PUT" and "/packages/generic/appsec-bundles/" in url:
                kinds.append("upload")
            elif m == "POST" and url.endswith("/pipeline"):
                kinds.append("trigger")
            elif m == "GET" and "/pipelines/" in url and not url.endswith("/jobs"):
                kinds.append("poll")
        self.assertIn("poll", kinds, kinds)
        before_first_poll = kinds[: kinds.index("poll")]
        self.assertEqual(before_first_poll.count("upload"), 2, kinds)
        self.assertEqual(before_first_poll.count("trigger"), 2, kinds)

        # stdout still comes out in LANGS order (javascript, then python).
        self.assertIn("REMOTE-MATCH: language=javascript status=ok findings=3 pipeline=", result.stdout)
        self.assertIn("REMOTE-MATCH: language=python status=ok findings=3 pipeline=", result.stdout)
        self.assertLess(
            result.stdout.index("language=javascript"),
            result.stdout.index("language=python"),
            result.stdout,
        )


class MixedOutcomeTests(RemoteMatchTestCase):
    def test_one_language_fails_other_ok_exit_4(self) -> None:
        # go has no go.mod in this repo, so it fails in phase 1 (before any
        # HTTP call) while javascript runs the full upload/trigger/poll path.
        self.write_files(JAVASCRIPT_FILES)
        self.write_scenario(scenario())

        result = self.run_script("--language", "javascript", "--language", "go")

        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        self.assertIn("REMOTE-MATCH: language=javascript status=ok findings=3 pipeline=", result.stdout)
        self.assertIn("REMOTE-MATCH: language=go status=error findings=0 pipeline=", result.stdout)
        self.assertIn("REMOTE-MATCH-REASON: language=go", result.stdout)
        self.assertIn("no go manifest/lockfiles found", result.stdout)

        js = self.result_json("javascript")
        self.assertEqual(js["status"], "ok")
        self.assertEqual(js["findings"], 3)
        go = self.result_json("go")
        self.assertEqual(go["status"], "error")
        self.assertIn("no go manifest/lockfiles found", go["reason"])


class MultiLanguageInterruptTests(RemoteMatchTestCase):
    def test_sigterm_during_shared_poll_cleans_up_every_language(self) -> None:
        self.write_files({**JAVASCRIPT_FILES, **PYTHON_FILES})
        self.write_scenario(scenario(poll={"status": 200, "body": {"status": "running"}}))

        cmd = [
            "bash", str(SCRIPT),
            "--project-dir", str(self.repo),
            "--results", str(self.results),
            "--instance", INSTANCE,
            "--matcher-project", MATCHER_PROJECT,
            "--language", "javascript",
            "--language", "python",
            "--poll", "1",
        ]
        proc = subprocess.Popen(
            cmd, env=self.env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            # 2 uploads + 2 triggers + a poll per language before interrupting,
            # i.e. the script is inside the shared poll_all_pending loop.
            deadline = time.time() + 10
            while time.time() < deadline and len(self.call_args()) < 6:
                time.sleep(0.05)
            self.assertGreaterEqual(
                len(self.call_args()), 6, "script never reached the shared poll loop"
            )

            proc.send_signal(signal.SIGTERM)
            stdout, stderr = proc.communicate(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()

        self.assertEqual(proc.returncode, 143, stdout + stderr)
        calls = self.call_args()
        delete_calls = sum(
            1 for args in calls
            if self.method_url(args) == ("DELETE", f"{INSTANCE}/api/v4/projects/{MATCHER_PROJECT}/packages/999")
        )
        cancel_calls = sum(1 for args in calls for a in args if a.endswith("/cancel"))
        self.assertGreaterEqual(delete_calls, 2, f"expected 2 bundle deletes in {calls}")
        self.assertGreaterEqual(cancel_calls, 2, f"expected 2 pipeline cancels in {calls}")


class SharedTimeoutTests(RemoteMatchTestCase):
    def test_shared_timeout_reports_every_unfinished_language(self) -> None:
        self.write_files({**JAVASCRIPT_FILES, **PYTHON_FILES})
        self.write_scenario(scenario(poll={"status": 200, "body": {"status": "running"}}))

        result = self.run_script(
            "--language", "javascript", "--language", "python",
            "--timeout", "2", "--poll", "1",
        )

        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        self.assertIn("REMOTE-MATCH: language=javascript status=timeout findings=0 pipeline=", result.stdout)
        self.assertIn("REMOTE-MATCH: language=python status=timeout findings=0 pipeline=", result.stdout)

        for lang in ("javascript", "python"):
            data = self.result_json(lang)
            self.assertEqual(data["status"], "timeout")
            self.assertIn("did not reach a terminal state within 2s", data["reason"])


class TokenSafetyTests(RemoteMatchTestCase):
    def test_token_never_appears_in_argv_or_output(self) -> None:
        secret = "SUPER-SECRET-TOKEN-VALUE-0xDEADBEEF"
        self.env["APPSEC_RESOLVED_TOKEN"] = secret
        self.write_files(JAVASCRIPT_FILES)
        self.write_scenario(scenario())

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(secret, result.stdout)
        self.assertNotIn(secret, result.stderr)
        self.assertNotIn(secret, self.log_path.read_text())
        for path in self.results.rglob("*"):
            if path.is_file():
                try:
                    content = path.read_text(errors="ignore")
                except OSError:
                    continue
                self.assertNotIn(secret, content, f"token leaked into {path}")


class NoTokenTests(RemoteMatchTestCase):
    def test_missing_token_is_unusable_exit_3(self) -> None:
        del self.env["APPSEC_RESOLVED_TOKEN"]
        self.write_files(JAVASCRIPT_FILES)
        self.write_scenario(scenario())

        result = self.run_script()

        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("REMOTE-MATCH-REASON: language=javascript", result.stdout)
        self.assertIn("APPSEC_RESOLVED_TOKEN", result.stdout)
        self.assertFalse(self.log_path.exists(), "no HTTP call should have been made without a token")


class NoLanguagesTests(RemoteMatchTestCase):
    def test_no_detectable_languages_exits_0(self) -> None:
        self.write_files({"README.md": "# nothing to scan here\n"})
        self.write_scenario(scenario())

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "REMOTE-MATCH: none detected")
        self.assertFalse(self.log_path.exists())


if __name__ == "__main__":
    unittest.main()
