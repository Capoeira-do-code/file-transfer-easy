#!/usr/bin/env python3
"""Prepare, explicitly submit, inspect and download an isolated macOS CI build.

`prepare` is entirely local. `submit` creates a private build repository or a
new public branch only when explicitly selected. It never creates a tag, PR
or release and never deletes a remote repository or branch.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(directory, plan):
    (directory / "CI-PLAN.json").write_text(json.dumps(plan, indent=2) + "\n")


def verified(directory):
    plan = json.loads((directory / "CI-PLAN.json").read_text())
    manifest = json.loads((directory / "BUILD-SNAPSHOT.json").read_text())
    for name, expected in manifest["files"].items():
        path = directory / name
        if not path.resolve().is_relative_to(directory.resolve()) or digest(path.read_bytes()) != expected:
            raise ValueError("Source snapshot changed: " + name)
    if digest((directory / "BUILD-SNAPSHOT.json").read_bytes()) != plan["manifest_sha256"]:
        raise ValueError("Source manifest changed after preparation")
    return plan, manifest


def prepare(source, directory):
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Use a new or empty staging directory")
    directory.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as archive:
        for entry in archive.infolist():
            name = PurePosixPath(entry.filename)
            if name.is_absolute() or ".." in name.parts:
                raise ValueError("Unsafe source archive path")
            path = directory.joinpath(*name.parts)
            if entry.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(entry))
    manifest_path = directory / "BUILD-SNAPSHOT.json"
    manifest = json.loads(manifest_path.read_text())
    for name, expected in manifest["files"].items():
        if digest((directory / name).read_bytes()) != expected:
            raise ValueError("Source archive hash mismatch: " + name)
    workflow = Path(__file__).with_name("macos-artifacts.yml").read_bytes()
    workflow_name = ".github/workflows/build.yml"
    (directory / workflow_name).write_bytes(workflow)
    # Git text normalization must not invalidate hashes on the Unix runner.
    # The reviewed source archive remains unchanged; only staging is normalized.
    for name in manifest["files"]:
        path = directory / name
        data = path.read_bytes()
        try:
            data.decode("utf-8")
            if b"\0" not in data:
                data = data.replace(b"\r\n", b"\n")
                path.write_bytes(data)
        except UnicodeDecodeError:
            pass
        manifest["files"][name] = digest(data)
    manifest["ci_workflow"] = "macOS-only artifact build, Ubuntu vet/race, no release job"
    manifest["source_archive_sha256"] = digest(source.read_bytes())
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    plan = {"version": manifest["version"], "source_sha256": manifest["source_archive_sha256"],
            "manifest_sha256": digest(manifest_path.read_bytes()), "file_count": len(manifest["files"]),
            "workflow": workflow_name, "artifact": "macos-dmg", "remote_mutated": False}
    save(directory, plan)
    print(json.dumps({"directory": str(directory), **plan}, indent=2))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self):
        env = dict(os.environ, GCM_INTERACTIVE="Never", GIT_TERMINAL_PROMPT="0")
        result = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                                capture_output=True, text=True, env=env, check=True, timeout=20)
        credentials = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        self.token = credentials.get("password")
        if not self.token:
            raise RuntimeError("Git Credential Manager has no GitHub credential")
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, path, data=None, method=None):
        headers = {"Accept": "application/vnd.github+json", "Authorization": "Bearer " + self.token,
                   "User-Agent": "FileTransferEasy-Build", "X-GitHub-Api-Version": "2022-11-28"}
        payload = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request("https://api.github.com" + path, data=payload, headers=headers, method=method)
        with self.opener.open(req, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else None

    def artifact(self, path):
        # The artifact endpoint redirects to signed storage. Do not forward the
        # GitHub bearer credential across that authentication boundary.
        try:
            self.request(path)
        except urllib.error.HTTPError as error:
            if error.code != 302:
                raise
            location = error.headers["Location"]
            if urllib.parse.urlparse(location).scheme != "https":
                raise ValueError("Artifact download did not use HTTPS")
            with urllib.request.urlopen(location, timeout=120) as response:
                return response.read()
        raise RuntimeError("Artifact endpoint did not return its signed download")


def submit(directory, repository, branch, mode):
    plan, manifest = verified(directory)
    if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Repository must use owner/name")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]*", branch) or ".." in branch:
        raise ValueError("Invalid branch name")
    if mode == "public-branch" and branch in ("main", "master"):
        raise ValueError("A public build requires a new branch, never main/master")
    api = GitHub()
    owner, name = repository.split("/")
    user = api.request("/user")
    if owner.lower() != user["login"].lower():
        raise ValueError("Build repository must belong to the authenticated account")
    try:
        repo = api.request("/repos/" + repository)
        if mode == "private" and not plan.get("created_repository"):
            raise ValueError("Private build repository already exists; choose a new name")
    except urllib.error.HTTPError as error:
        if error.code != 404 or mode != "private":
            raise
        repo = api.request("/user/repos", {"name": name, "private": True, "auto_init": False,
                           "has_issues": False, "has_projects": False, "has_wiki": False})
        plan["created_repository"] = repo["full_name"]
        plan["remote_mutated"] = True
        save(directory, plan)
    if bool(repo["private"]) != (mode == "private"):
        raise ValueError("Repository visibility differs from the selected mode")
    if plan.get("repository") not in (None, repository) or plan.get("branch") not in (None, branch):
        raise ValueError("Staging directory is already associated with another remote target")
    plan.update(repository=repository, branch=branch, mode=mode)
    save(directory, plan)
    env = dict(os.environ, GCM_INTERACTIVE="Never", GIT_TERMINAL_PROMPT="0")
    def git(*arguments, capture=False):
        return subprocess.run(["git", "-C", str(directory), *arguments], check=True,
                              text=True, capture_output=capture, env=env)
    if not (directory / ".git").exists():
        git("init", "-b", branch, capture=True)
        git("config", "core.autocrlf", "false")
        git("config", "user.name", "File Transfer Easy build")
        git("config", "user.email", "noreply@filetransfereasy.local")
        git("remote", "add", "origin", "https://github.com/" + repository + ".git")
        if mode == "public-branch":
            # Preserve normal ancestry without checking out over the reviewed
            # staging files. read-tree seeds only the index from origin's base.
            git("fetch", "--depth=1", "origin", repo["default_branch"])
            git("reset", "--soft", "FETCH_HEAD")
            git("read-tree", "HEAD")
            previous = git("ls-tree", "-r", "--name-only", "HEAD", "--", "go-app", capture=True).stdout.splitlines()
            removed = [name for name in previous if name not in manifest["files"]]
            if removed:
                git("rm", "--cached", "--ignore-unmatch", "--", *removed, capture=True)
        git("add", "--", *manifest["files"], "BUILD-SNAPSHOT.json")
        git("commit", "-m", "Build macOS artifact " + plan["version"], capture=True)
    commit = git("rev-parse", "HEAD", capture=True).stdout.strip()
    try:
        existing = api.request("/repos/" + repository + "/git/ref/heads/" + urllib.parse.quote(branch, safe=""))
        if existing["object"]["sha"] != commit:
            raise ValueError("Remote branch already exists with different content; no overwrite performed")
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        git("push", "origin", "HEAD:refs/heads/" + branch)
    plan.update(commit=commit, remote_mutated=True)
    save(directory, plan)
    if plan.get("run_id") or plan.get("dispatched"):
        print(json.dumps(plan, indent=2)); return
    # A new private repository needs a moment to register its first workflow.
    deadline = time.monotonic() + 25
    while True:
        try:
            api.request("/repos/" + repository + "/actions/workflows/build.yml")
            break
        except urllib.error.HTTPError as error:
            if error.code != 404 or time.monotonic() >= deadline:
                raise
            time.sleep(1)
    api.request("/repos/" + repository + "/actions/workflows/build.yml/dispatches",
                {"ref": branch, "inputs": {"version": plan["version"]}})
    plan["dispatched"] = True
    save(directory, plan)
    print(json.dumps(plan, indent=2))


def status(directory):
    plan, _ = verified(directory)
    api = GitHub()
    repository = plan["repository"]
    if not plan.get("run_id"):
        query = urllib.parse.urlencode({"branch": plan["branch"], "event": "workflow_dispatch", "per_page": 20})
        runs = api.request("/repos/" + repository + "/actions/runs?" + query)["workflow_runs"]
        run = next((run for run in runs if run["head_sha"] == plan["commit"]), None)
        if not run:
            print(json.dumps({"status": "awaiting workflow registration/run", "repository": repository})); return
        plan["run_id"] = run["id"]
        save(directory, plan)
    run = api.request(f"/repos/{repository}/actions/runs/{plan['run_id']}")
    jobs = api.request(f"/repos/{repository}/actions/runs/{plan['run_id']}/jobs?per_page=100")["jobs"]
    print(json.dumps({"run_id": run["id"], "url": run["html_url"], "status": run["status"],
                      "conclusion": run["conclusion"], "jobs": [{"name": job["name"], "status": job["status"],
                      "conclusion": job["conclusion"], "id": job["id"]} for job in jobs]}, indent=2))


def download(directory, output):
    import io
    plan, _ = verified(directory)
    api = GitHub()
    repository, run_id = plan["repository"], plan["run_id"]
    run = api.request(f"/repos/{repository}/actions/runs/{run_id}")
    if run["conclusion"] != "success":
        raise ValueError("Wait for a successful workflow run before downloading")
    artifacts = api.request(f"/repos/{repository}/actions/runs/{run_id}/artifacts")["artifacts"]
    artifact = next(artifact for artifact in artifacts if artifact["name"] == "macos-dmg" and not artifact["expired"])
    data = api.artifact(f"/repos/{repository}/actions/artifacts/{artifact['id']}/zip")
    output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        expected = f"FileTransferEasy-{plan['version']}.dmg"
        names = {PurePosixPath(name).name: name for name in archive.namelist() if not name.endswith("/")}
        dmg = archive.read(names[expected])
        checksum = archive.read(names[expected + ".sha256"])
        parts = checksum.decode().split()
        if digest(dmg) != parts[0] or parts[1].lstrip("*") != expected:
            raise ValueError("Downloaded DMG checksum mismatch")
        if dmg[-512:-508] != b"koly":
            raise ValueError("Downloaded file is not a UDIF disk image")
        for name, content in ((expected, dmg), (expected + ".sha256", checksum)):
            destination = output / name
            if destination.exists() and destination.read_bytes() != content:
                raise ValueError("Refusing to overwrite a different existing artifact: " + str(destination))
            destination.write_bytes(content)
    plan["downloaded_dmg"] = {"path": str(output / expected), "sha256": digest(dmg), "bytes": len(dmg),
                               "run_url": run["html_url"]}
    save(directory, plan)
    print(json.dumps(plan["downloaded_dmg"], indent=2))


parser = argparse.ArgumentParser(description=__doc__)
commands = parser.add_subparsers(dest="command", required=True)
command = commands.add_parser("prepare", help="Local staging only; never accesses GitHub")
command.add_argument("--source", type=Path, required=True)
command.add_argument("--directory", type=Path, required=True)
command = commands.add_parser("submit", help="Explicitly upload reviewed staging and start its macOS build")
command.add_argument("--directory", type=Path, required=True)
command.add_argument("--repository", required=True)
command.add_argument("--branch", required=True)
command.add_argument("--mode", choices=("private", "public-branch"), required=True)
command = commands.add_parser("status", help="Read-only workflow status")
command.add_argument("--directory", type=Path, required=True)
command = commands.add_parser("download", help="Download and verify the completed DMG artifact")
command.add_argument("--directory", type=Path, required=True)
command.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
if args.command == "prepare":
    prepare(args.source.resolve(), args.directory.resolve())
elif args.command == "submit":
    submit(args.directory.resolve(), args.repository, args.branch, args.mode)
elif args.command == "status":
    status(args.directory.resolve())
else:
    download(args.directory.resolve(), args.output.resolve())
