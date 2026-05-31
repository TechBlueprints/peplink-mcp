"""IC2 doctor tests."""

from __future__ import annotations

import httpx
from peplink_core.config import IC2ClientCredentials, IC2Config
from peplink_ic2.client import IC2Client
from peplink_ic2.doctor import run_ic2_doctor


def _ic2(default_org=None) -> IC2Config:
    return IC2Config(
        enabled=True,
        default_org_id=default_org,
        auth=IC2ClientCredentials(client_id="cid", client_secret="sec"),
    )


def _bound_client(handler) -> IC2Client:
    c = IC2Client(_ic2().auth)
    transport = httpx.MockTransport(handler)
    c._client = lambda: httpx.Client(transport=transport, verify=False)  # noqa: SLF001
    return c


def _token(_req):
    return httpx.Response(200, json={"access_token": "t", "expires_in": 9999})


def test_doctor_all_ok():
    def handler(request):
        path = request.url.path
        if path == "/api/oauth2/token":
            return _token(request)
        if path == "/rest/o":
            return httpx.Response(200, json={"resp_code": "SUCCESS", "data": [{"id": "1"}]})
        if path == "/rest/o/1/g":
            return httpx.Response(200, json={"resp_code": "SUCCESS", "data": [{"id": "g"}]})
        return httpx.Response(404)

    report = run_ic2_doctor(_ic2(default_org="1"), client=_bound_client(handler))
    assert report.ok
    assert [c.check for c in report.checks] == ["token_grant", "list_orgs", "list_groups"]


def test_doctor_token_failure_stops_early():
    def handler(request):
        return httpx.Response(401, json={"error": "invalid_client"})

    report = run_ic2_doctor(_ic2(), client=_bound_client(handler))
    assert not report.ok
    assert len(report.checks) == 1
    assert report.checks[0].check == "token_grant"
