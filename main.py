# --- PART 1 of 4 -------------------------------------------------------
"""InstaLockpick - single-file Kivy Android app."""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

os.environ.setdefault("KIVY_NO_ARGS", "1")

try:
    import certifi

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except Exception:
    pass

import instaloader
import requests
from bs4 import BeautifulSoup

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.properties import BooleanProperty, ListProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.progressbar import ProgressBar  # noqa: F401
from kivy.uix.screenmanager import FadeTransition, Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

APP_NAME = "InstaLockpick"
VERSION = "0.1.0"

SHARED_EXPORT = Path("/storage/emulated/0/Download/InstaLockpick")


def _root() -> Path:
    app = App.get_running_app()
    base = Path(app.user_data_dir) if app else Path.cwd() / ".lockpick"
    base.mkdir(parents=True, exist_ok=True)
    return base


def session_dir() -> Path:
    d = _root() / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def download_dir() -> Path:
    d = _root() / "downloads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_file() -> Path:
    return _root() / "watch-state.json"


def watchlist_file() -> Path:
    return _root() / "watchlist.json"


class NotLoggedIn(RuntimeError):
    pass


class NeedsTwoFactor(RuntimeError):
    pass


class Locked(RuntimeError):
    pass


class Missing(LookupError):
    pass


class Cancelled(RuntimeError):
    pass


_pending: dict = {}


def _base_loader(quiet: bool = True) -> instaloader.Instaloader:
    return instaloader.Instaloader(
        quiet=quiet,
        download_pictures=True,
        download_videos=True,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=True,
        compress_json=False,
        post_metadata_txt_pattern="{caption}",
        max_connection_attempts=3,
    )


def _session_file(username: str) -> Path:
    return session_dir() / f"session-{username}"


def login(username: str, password: str) -> str:
    inst = _base_loader(quiet=False)
    try:
        inst.login(username, password)
    except instaloader.exceptions.TwoFactorAuthRequiredException:
        _pending["loader"] = inst
        _pending["username"] = username
        return "2fa"
    except instaloader.exceptions.BadCredentialsException as exc:
        raise RuntimeError("Wrong username or password.") from exc

    inst.save_session_to_file(str(_session_file(username)))
    return "ok"


def login_two_factor(code: str) -> str:
    if "loader" not in _pending:
        raise NeedsTwoFactor("Start the login again.")
    inst = _pending.pop("loader")
    username = _pending.pop("username")
    inst.two_factor_login(code)
    inst.save_session_to_file(str(_session_file(username)))
    return "ok"


def saved_accounts() -> list[str]:
    return sorted(
        p.stem.removeprefix("session-") for p in session_dir().glob("session-*")
    )


def logged_in_as() -> str | None:
    accounts = saved_accounts()
    if not accounts:
        return None
    try:
        inst = _base_loader()
        inst.load_session_from_file(accounts[0], str(_session_file(accounts[0])))
        return inst.test_login() or None
    except Exception:
        return None


def loader(username: str | None = None, quiet: bool = True) -> instaloader.Instaloader:
    username = username or logged_in_as()
    if not username:
        raise NotLoggedIn("Not logged in. Open Settings and log in first.")
    path = _session_file(username)
    if not path.exists():
        raise NotLoggedIn(f"No saved session for @{username}.")
    inst = _base_loader(quiet=quiet)
    inst.load_session_from_file(username, str(path))
    return inst


def logout() -> None:
    account = logged_in_as()
    if not account:
        return
    path = _session_file(account)
    if path.exists():
        path.unlink()


class Access(str, Enum):
    PUBLIC = "public"
    APPROVED = "approved"
    LOCKED = "locked"
    MISSING = "missing"
    UNKNOWN = "unknown"


@dataclass
class Probe:
    username: str
    access: str
    is_private: bool | None = None
    followed_by_viewer: bool | None = None
    follow_request_pending: bool | None = None
    user_id: int | None = None
    full_name: str | None = None
    biography: str | None = None
    followers: int | None = None
    following: int | None = None
    posts: int | None = None
    verified: bool | None = None
    external_url: str | None = None

    @property
    def readable(self) -> bool:
        return self.access in (Access.PUBLIC.value, Access.APPROVED.value)

    def to_dict(self) -> dict:
        return asdict(self)


NEXT_MOVE = {
    Access.PUBLIC.value: "Not private. Open Instagram, nothing is hidden.",
    Access.APPROVED.value: "You are on the list. Download everything.",
    Access.LOCKED.value: "Locked. Send a follow request, then wait.",
    Access.MISSING.value: "No such account. Check the spelling.",
    Access.UNKNOWN.value: "API hiccup. Try again.",
}


def probe(inst: instaloader.Instaloader, username: str) -> Probe:
    username = username.lstrip("@").strip().lower()
    try:
        profile = instaloader.Profile.from_username(inst.context, username)
    except instaloader.exceptions.ProfileNotExistsException:
        return Probe(username=username, access=Access.MISSING.value)
    except (
        instaloader.exceptions.LoginRequiredException,
        instaloader.exceptions.ConnectionException,
    ):
        return Probe(username=username, access=Access.UNKNOWN.value)

    is_private = bool(getattr(profile, "is_private", False))
    followed = bool(getattr(profile, "followed_by_viewer", False))
    pending = bool(
        getattr(
            profile,
            "requested_by_viewer",
            getattr(profile, "has_requested_viewer", False),
        )
    )

    if not is_private:
        access = Access.PUBLIC
    elif followed:
        access = Access.APPROVED
    else:
        access = Access.LOCKED

    return Probe(
        username=username,
        access=access.value,
        is_private=is_private,
        followed_by_viewer=followed,
        follow_request_pending=pending,
        user_id=getattr(profile, "userid", None),
        full_name=getattr(profile, "full_name", None),
        biography=getattr(profile, "biography", None),
        followers=getattr(profile, "followers", None),
        following=getattr(profile, "followees", None),
        posts=getattr(profile, "mediacount", None),
        verified=getattr(profile, "is_verified", None),
        external_url=getattr(profile, "external_url", None),
    )
