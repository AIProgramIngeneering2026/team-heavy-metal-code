import base64
import binascii
import re

import httpx

from core.tool_contract import RepositorySnapshot


REPOSITORY_URL = re.compile(r"https://github.com/([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+)/?")
SHA = re.compile(r"[0-9a-f]{40}")
MESSAGES = {
    "repository_not_found": "Repository or commit was not found on GitHub.",
    "github_access_denied": "GitHub API denied access.",
    "github_rate_limited": "GitHub API rate limit exceeded.",
    "github_unavailable": "GitHub API could not provide the repository snapshot.",
}


def repository_match(url: str):
    match = REPOSITORY_URL.fullmatch(url)
    return match if match and match[2] not in {".", ".."} else None


class GitHubError(Exception):
    def __init__(self, code: str):
        super().__init__(MESSAGES[code])
        self.code = code


class GitHub:
    def __init__(self, client: httpx.Client):
        self.client = client

    def _get(self, path: str, **params):
        try:
            response = self.client.get(f"https://api.github.com/{path}", params=params)
        except httpx.RequestError as exc:
            raise GitHubError("github_unavailable") from exc

        status = response.status_code
        if status == 404:
            raise GitHubError("repository_not_found")
        if status == 429 or (
            status == 403 and (
                response.headers.get("x-ratelimit-remaining") == "0"
                or "retry-after" in response.headers
                or "rate limit" in response.text.lower()
            )
        ):
            raise GitHubError("github_rate_limited")
        if status in {401, 403, 451}:
            raise GitHubError("github_access_denied")
        if status != 200:
            raise GitHubError("github_unavailable")
        try:
            return response.json()
        except ValueError as exc:
            raise GitHubError("github_unavailable") from exc

    def resolve(self, url: str) -> tuple[str, str, str]:
        match = repository_match(url)
        if match is None:
            raise ValueError("Invalid GitHub repository URL")
        repo = f"repos/{match[1]}/{match[2]}"
        try:
            metadata = self._get(repo)
            if metadata["private"]:
                raise GitHubError("github_access_denied")
            commits = self._get(f"{repo}/commits", sha=metadata["default_branch"], per_page=1)
            sha = commits[0]["sha"]
            tree_sha = commits[0]["commit"]["tree"]["sha"]
            if not SHA.fullmatch(sha) or not SHA.fullmatch(tree_sha):
                raise ValueError("Invalid SHA")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise GitHubError("github_unavailable") from exc
        return repo, sha, tree_sha

    def snapshot(self, url: str, repo: str, sha: str, tree_sha: str) -> RepositorySnapshot:
        try:
            # The built-in profile uses only root files. The tree and blob
            # are content-addressed by the commit resolved above.
            tree = self._get(f"{repo}/git/trees/{tree_sha}")
            if tree["truncated"]:
                raise ValueError("Incomplete tree")
            files = {entry["path"]: entry for entry in tree["tree"] if entry["type"] == "blob"}
            texts = {}
            readme = files.get("README.md")
            if readme and readme["mode"] in {"100644", "100755"}:
                blob_sha = readme["sha"]
                if not SHA.fullmatch(blob_sha):
                    raise ValueError("Invalid blob SHA")
                blob = self._get(f"{repo}/git/blobs/{blob_sha}")
                if blob["encoding"] != "base64":
                    raise ValueError("Unsupported blob encoding")
                content = "".join(blob["content"].split())
                texts["README.md"] = base64.b64decode(content, validate=True).decode("utf-8-sig")
            return RepositorySnapshot(url, sha, tuple(files), texts)
        except (AttributeError, KeyError, TypeError, ValueError, binascii.Error) as exc:
            raise GitHubError("github_unavailable") from exc
