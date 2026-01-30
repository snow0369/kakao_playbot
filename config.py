# config.py
import yaml
from pathlib import Path
from urllib.parse import urlparse, parse_qs

CONFIG_FILE = Path("config.local.yaml")


def _loader(key: str, input_message: str, interactive: bool = True) -> str:
    save_flag = False
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        save_flag = True
        cfg = {}

    if key not in cfg:
        if not interactive:
            raise KeyError(key)
        user_name = input(input_message).strip()
        if not user_name:
            raise ValueError("USER_NAME cannot be empty")
        cfg[key] = user_name
        save_flag = True

    if save_flag:
        with CONFIG_FILE.open("w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)

    return cfg[key]


def load_username(interactive: bool = True) -> str:
    return _loader("USER_NAME", "Enter your username: ", interactive)


def _parse_playbot_url(url: str) -> dict[str, str]:
    """
    Parse Playbot collection URL and extract required keys.
    """
    parsed = urlparse(url.strip())

    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Invalid URL scheme")

    if parsed.netloc != "collection.playbot.co.kr":
        raise ValueError("Invalid Playbot collection URL")

    qs = parse_qs(parsed.query)

    try:
        bot_group_key = qs["botGroupKey"][0]
        bot_user_key = qs["botUserKey"][0]
    except (KeyError, IndexError):
        raise ValueError("URL must contain botGroupKey and botUserKey")

    return {
        "BOT_GROUP_KEY": bot_group_key,
        "BOT_USER_KEY": bot_user_key,
    }


def _load_playbot_keys(interactive: bool = True) -> tuple[str, str]:
    save_flag = False
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        cfg = {}
        save_flag = True

    missing = [k for k in ("BOT_GROUP_KEY", "BOT_USER_KEY") if k not in cfg]

    if missing:
        if not interactive:
            raise KeyError(f"Missing keys: {missing}")

        url = input(
            "Enter Playbot collection URL (copy from browser): "
        ).strip()

        parsed = _parse_playbot_url(url)
        cfg.update(parsed)
        save_flag = True

    if save_flag:
        with CONFIG_FILE.open("w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)

    return cfg["BOT_GROUP_KEY"], cfg["BOT_USER_KEY"]


def load_botgroupkey(interactive: bool = True) -> str:
    group_key, _ = _load_playbot_keys(interactive)
    return group_key


def load_botuserkey(interactive: bool = True) -> str:
    _, user_key = _load_playbot_keys(interactive)
    return user_key
