"""The service's settings, all from the environment (service/README.md lists them)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _list(name: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, "").replace("\n", ",").split(",") if x.strip()]


def _int(name: str, default: int) -> int:
    v = os.environ.get(name, "").strip()
    return int(v) if v else default


@dataclass
class Config:
    secret: str                              # signs session tokens and OAuth state (SCALE_WEB_SECRET)
    github_client_id: str = ""
    github_client_secret: str = ""
    allowlist: list[str] = field(default_factory=list)      # GitHub logins, lower case
    site_origins: list[str] = field(default_factory=list)   # the pages allowed to call the service and to sign in
    public_url: str = ""                     # the service's own URL, for the OAuth callback
    model: str = "claude-opus-5-5"
    contact_email: str = ""                  # for Unpaywall; without it no open-access PDF is looked up
    jobs_per_user_per_day: int = 5
    questions_per_user_per_day: int = 50
    tokens_per_day: int = 4_000_000          # input + output tokens over every job and question, a day (UTC)
    tokens_per_job: int = 600_000
    max_turns: int = 60
    concurrent_jobs: int = 2
    max_upload_mb: int = 40
    job_ttl_s: int = 3600
    session_ttl_s: int = 8 * 3600
    workdir: str = ""                        # where job folders live while they run (a temporary directory)
    github_token: str = ""                   # the bot's token that opens contribution pull requests
    repo: str = "hlxin/scale"
    commons: str = "graphs/catal-commons"
    reviewers: list[str] = field(default_factory=list)      # asked to review each contribution
    contributions_per_user_per_day: int = 5
    archive: str = ""                        # where kept papers live (scaleweb/archive.py); empty: none kept
    usage: str = ""                          # the use counts of the leaderboard (scaleweb/usage.py); empty: in memory
    inbox: str = ""                          # the inbox (scaleweb/inbox.py): Claude Code curates there; empty: the model here
    inbox_login: str = ""                    # who a PDF dropped into the inbox by hand is credited to
    claude: str = "claude"                   # the Claude Code command the inbox runner starts
    inbox_turns: int = 200                   # Claude Code's turns for one publication
    inbox_minutes: int = 90                  # and its time

    @classmethod
    def from_env(cls) -> Config:
        secret = os.environ.get("SCALE_WEB_SECRET", "")
        if len(secret) < 32:
            raise SystemExit("SCALE_WEB_SECRET must be set to a random string of at least 32 characters")
        return cls(
            secret=secret,
            github_client_id=os.environ.get("GITHUB_CLIENT_ID", ""),
            github_client_secret=os.environ.get("GITHUB_CLIENT_SECRET", ""),
            allowlist=[x.lower() for x in _list("SCALE_WEB_ALLOWLIST")],
            site_origins=[x.rstrip("/") for x in _list("SCALE_WEB_SITE_ORIGINS")],
            public_url=os.environ.get("SCALE_WEB_PUBLIC_URL", "").rstrip("/"),
            model=os.environ.get("SCALE_WEB_MODEL", "claude-opus-5-5"),
            contact_email=os.environ.get("SCALE_CONTACT_EMAIL", ""),
            jobs_per_user_per_day=_int("SCALE_WEB_JOBS_PER_USER", 5),
            questions_per_user_per_day=_int("SCALE_WEB_QUESTIONS_PER_USER", 50),
            tokens_per_day=_int("SCALE_WEB_TOKENS_PER_DAY", 4_000_000),
            tokens_per_job=_int("SCALE_WEB_TOKENS_PER_JOB", 600_000),
            max_turns=_int("SCALE_WEB_MAX_TURNS", 60),
            concurrent_jobs=_int("SCALE_WEB_CONCURRENT_JOBS", 2),
            max_upload_mb=_int("SCALE_WEB_MAX_UPLOAD_MB", 40),
            workdir=os.environ.get("SCALE_WEB_WORKDIR", ""),
            github_token=os.environ.get("SCALE_WEB_GITHUB_TOKEN", ""),
            repo=os.environ.get("SCALE_WEB_REPO", "hlxin/scale"),
            commons=os.environ.get("SCALE_WEB_COMMONS", "graphs/catal-commons"),
            reviewers=_list("SCALE_WEB_REVIEWERS"),
            contributions_per_user_per_day=_int("SCALE_WEB_CONTRIBUTIONS_PER_USER", 5),
            archive=os.environ.get("SCALE_WEB_ARCHIVE", ""),
            usage=os.environ.get("SCALE_WEB_USAGE", ""),
            inbox=os.environ.get("SCALE_WEB_INBOX", ""),
            inbox_login=os.environ.get("SCALE_WEB_INBOX_LOGIN", "").lower(),
            claude=os.environ.get("SCALE_WEB_CLAUDE", "claude"),
            inbox_turns=_int("SCALE_WEB_INBOX_TURNS", 200),
            inbox_minutes=_int("SCALE_WEB_INBOX_MINUTES", 90),
        )
