"""InControl 2 connectivity / auth diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field

from peplink_core.config import IC2Config

from peplink_ic2.client import IC2Client
from peplink_ic2.endpoints.inventory import _records
from peplink_ic2.exceptions import IC2ConfigError, IC2Error


@dataclass
class IC2CheckResult:
    check: str
    ok: bool
    message: str


@dataclass
class IC2DoctorReport:
    base_url: str
    checks: list[IC2CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)


def run_ic2_doctor(ic2: IC2Config, *, client: IC2Client | None = None) -> IC2DoctorReport:
    """Probe IC2: token grant, org list, and (if set) the default org's groups.

    Uses the read credential. When a distinct admin (write) credential is configured,
    its token grant is checked too.
    """
    read_creds = ic2.read_credentials()
    if read_creds is None:
        raise IC2ConfigError("incontrol2 has no credentials configured")

    client = client or IC2Client(
        read_creds, base_url=ic2.base_url, verify_tls=ic2.verify_tls
    )
    report = IC2DoctorReport(base_url=ic2.base_url)

    # 1) token grant
    try:
        client.ensure_authenticated()
        report.checks.append(IC2CheckResult("token_grant", True, "OAuth2 token granted"))
    except IC2Error as exc:
        report.checks.append(IC2CheckResult("token_grant", False, str(exc)))
        return report

    # 2) org list
    try:
        orgs = _records(client.request("GET", "/rest/o"))
        report.checks.append(
            IC2CheckResult("list_orgs", True, f"GET /rest/o ok ({len(orgs)} org(s))")
        )
    except IC2Error as exc:
        report.checks.append(IC2CheckResult("list_orgs", False, str(exc)))
        return report

    # 3) optional default-org groups
    if ic2.default_org_id:
        try:
            groups = _records(client.request("GET", f"/rest/o/{ic2.default_org_id}/g"))
            report.checks.append(
                IC2CheckResult(
                    "list_groups",
                    True,
                    f"GET /rest/o/{ic2.default_org_id}/g ok ({len(groups)} group(s))",
                )
            )
        except IC2Error as exc:
            report.checks.append(IC2CheckResult("list_groups", False, str(exc)))

    # If a distinct admin (write) credential is configured, verify its token grant too.
    write_creds = ic2.write_credentials()
    if write_creds is not None and write_creds is not read_creds:
        try:
            IC2Client(
                write_creds, base_url=ic2.base_url, verify_tls=ic2.verify_tls
            ).ensure_authenticated()
            report.checks.append(
                IC2CheckResult("admin_token_grant", True, "admin (write) token granted")
            )
        except IC2Error as exc:
            report.checks.append(IC2CheckResult("admin_token_grant", False, str(exc)))

    return report
