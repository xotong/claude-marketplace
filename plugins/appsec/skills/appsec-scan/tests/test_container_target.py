#!/usr/bin/env python3
"""Tests for container-target.sh: scan-target discovery and FROM-line inventory.

container-target.sh used to look for a Dockerfile only when CS_IMAGE was unset
— the CS_IMAGE branch returned before the discovery block ever ran. That meant
registry-mode runs never found a Dockerfile even when one sat right there, and
base-images.json (a later base-image-availability check depends on it) was
never written for that mode. These tests pin: discovery now runs in both
modes, the mode|value stdout contract is unchanged, and the FROM-line parsing
rules (stage aliases, scratch, --platform, digests, ports, ARG substitution)
hold.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "container-target.sh"


def run(
    cwd: Path,
    results_dir: Path,
    env_overrides: dict[str, str] | None = None,
    runtime: str = "docker",
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("CS_IMAGE", None)
    env.pop("DOCKERFILE", None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", str(SCRIPT), runtime, "app", str(results_dir)],
        cwd=str(cwd),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def base_images(results_dir: Path) -> list[dict]:
    path = results_dir / "base-images.json"
    return json.loads(path.read_text(encoding="utf-8"))


class ContainerTargetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="container-target-")
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.results = Path(self.tmp.name) / "results"
        self.repo.mkdir()
        self.results.mkdir()

    def write_dockerfile(self, content: str) -> None:
        (self.repo / "Dockerfile").write_text(content, encoding="utf-8")

    # -- stdout contract -----------------------------------------------------

    def test_no_cs_image_no_dockerfile_writes_empty_array(self) -> None:
        result = run(self.repo, self.results)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "none|\n")
        self.assertEqual(base_images(self.results), [])

    def test_registry_mode_still_finds_dockerfile(self) -> None:
        # The defect: CS_IMAGE's early return used to sit above discovery, so
        # this Dockerfile would never have been looked at.
        self.write_dockerfile("FROM python:3.11\n")

        result = run(self.repo, self.results, {"CS_IMAGE": "example.com/app:1.0"})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "registry|example.com/app:1.0\n")
        images = base_images(self.results)
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["image"], "python")
        self.assertEqual(images[0]["tag"], "3.11")

    def test_registry_mode_without_dockerfile_still_writes_empty_array(self) -> None:
        result = run(self.repo, self.results, {"CS_IMAGE": "example.com/app:1.0"})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "registry|example.com/app:1.0\n")
        self.assertEqual(base_images(self.results), [])

    def test_archive_mode_writes_base_images_before_build(self) -> None:
        self.write_dockerfile("FROM alpine:3.19\n")
        fake_runtime = Path(self.tmp.name) / "fake-docker"
        fake_runtime.write_text(
            "#!/bin/sh\ncase \"$1\" in build) exit 0 ;; save) exit 0 ;; esac\n",
            encoding="utf-8",
        )
        fake_runtime.chmod(0o755)

        result = run(self.repo, self.results, runtime=str(fake_runtime))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("archive|"), result.stdout)
        images = base_images(self.results)
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["image"], "alpine")
        self.assertEqual(images[0]["tag"], "3.19")

    # -- FROM parsing ---------------------------------------------------------

    def test_multistage_alias_and_scratch_are_excluded(self) -> None:
        self.write_dockerfile(
            "FROM node:18 AS build\n"
            "FROM build AS release\n"
            "FROM scratch AS empty\n"
        )

        run(self.repo, self.results, {"CS_IMAGE": "x"})
        images = base_images(self.results)

        # Only the real external image survives; the alias reference to
        # "build" and the "scratch" stage are both internal, not images to
        # mirror.
        self.assertEqual(len(images), 1)
        self.assertEqual(
            images[0],
            {"raw": "node:18", "image": "node", "tag": "18", "line": 1, "alias": "build"},
        )

    def test_platform_flag_is_stripped(self) -> None:
        self.write_dockerfile("FROM --platform=linux/amd64 golang:1.22\n")

        run(self.repo, self.results, {"CS_IMAGE": "x"})
        images = base_images(self.results)

        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["raw"], "golang:1.22")
        self.assertEqual(images[0]["image"], "golang")
        self.assertEqual(images[0]["tag"], "1.22")

    def test_digest_ref_records_digest_as_tag(self) -> None:
        digest = "sha256:" + "ab" * 32
        self.write_dockerfile(f"FROM eclipse-temurin@{digest}\n")

        run(self.repo, self.results, {"CS_IMAGE": "x"})
        images = base_images(self.results)

        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["image"], "eclipse-temurin")
        self.assertEqual(images[0]["tag"], digest)

    def test_registry_with_port_disambiguates_port_from_tag(self) -> None:
        self.write_dockerfile("FROM registry.internal:5000/team/api:1.4\n")

        run(self.repo, self.results, {"CS_IMAGE": "x"})
        images = base_images(self.results)

        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["image"], "api")
        self.assertEqual(images[0]["tag"], "1.4")

    def test_arg_default_is_substituted(self) -> None:
        self.write_dockerfile(
            "ARG BASE_IMAGE=python\n"
            "ARG BASE_TAG=3.11\n"
            "FROM ${BASE_IMAGE}:${BASE_TAG}\n"
        )

        run(self.repo, self.results, {"CS_IMAGE": "x"})
        images = base_images(self.results)

        self.assertEqual(len(images), 1)
        # raw keeps the literal, unsubstituted text; image/tag hold the
        # resolved values.
        self.assertEqual(images[0]["raw"], "${BASE_IMAGE}:${BASE_TAG}")
        self.assertEqual(images[0]["image"], "python")
        self.assertEqual(images[0]["tag"], "3.11")

    def test_unresolvable_arg_is_excluded_not_guessed(self) -> None:
        self.write_dockerfile("FROM $UNDECLARED_BASE\n")

        run(self.repo, self.results, {"CS_IMAGE": "x"})

        # No ARG default for UNDECLARED_BASE anywhere in the file — inventing
        # an image name here would later produce a bogus "mirror this"
        # request, so the entry is dropped rather than guessed.
        self.assertEqual(base_images(self.results), [])

    def test_bare_image_defaults_to_latest_tag(self) -> None:
        self.write_dockerfile("FROM debian\n")

        run(self.repo, self.results, {"CS_IMAGE": "x"})
        images = base_images(self.results)

        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["image"], "debian")
        self.assertEqual(images[0]["tag"], "latest")

    def test_from_and_as_are_case_insensitive(self) -> None:
        self.write_dockerfile("from Node:18 as Build\n")

        run(self.repo, self.results, {"CS_IMAGE": "x"})
        images = base_images(self.results)

        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["alias"], "Build")


if __name__ == "__main__":
    unittest.main()
