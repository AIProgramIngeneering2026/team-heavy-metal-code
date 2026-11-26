import base64

import httpx
import pytest

from service.github import GitHub, GitHubError


URL = "https://github.com/example/coursework"
REPO = "/repos/example/coursework"
COMMIT, TREE, BLOB = (letter * 40 for letter in "abc")


def test_snapshot_uses_tree_and_readme_from_resolved_commit():
    readme = "# Описание проекта\n"
    responses = iter([
        (REPO, {"private": False, "default_branch": "release/current"}),
        (f"{REPO}/commits", [{"sha": COMMIT, "commit": {"tree": {"sha": TREE}}}]),
        (f"{REPO}/git/trees/{TREE}", {"truncated": False, "tree": [
            {"path": "README.md", "type": "blob", "mode": "100644", "sha": BLOB},
            {"path": "CONTRIBUTING.md", "type": "blob"},
        ]}),
        (f"{REPO}/git/blobs/{BLOB}", {
            "encoding": "base64", "content": base64.b64encode(readme.encode()).decode(),
        }),
    ])

    def github(request):
        path, body = next(responses)
        assert request.url.host == "api.github.com"
        assert request.url.path == path
        if path.endswith("/commits"):
            assert request.url.params["sha"] == "release/current"
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(github)) as client:
        adapter = GitHub(client)
        snapshot = adapter.snapshot(URL, *adapter.resolve(URL))
    assert snapshot.commit_sha == COMMIT
    assert snapshot.repository_url == URL
    assert set(snapshot.paths) == {"README.md", "CONTRIBUTING.md"}
    assert snapshot.text_files == {"README.md": readme}


@pytest.mark.parametrize(("status", "headers", "code"), [
    (404, {}, "repository_not_found"),
    (403, {}, "github_access_denied"),
    (403, {"X-RateLimit-Remaining": "0"}, "github_rate_limited"),
    (429, {}, "github_rate_limited"),
    (503, {}, "github_unavailable"),
    (None, {}, "github_unavailable"),
])
def test_github_refusal_has_a_stable_code(status, headers, code):
    def github(request):
        if status is None:
            raise httpx.ReadTimeout("upstream timeout", request=request)
        return httpx.Response(status, headers=headers)

    with httpx.Client(transport=httpx.MockTransport(github)) as client:
        with pytest.raises(GitHubError) as raised:
            GitHub(client).resolve(URL)
    assert raised.value.code == code
