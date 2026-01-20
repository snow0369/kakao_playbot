# config.py
import yaml
from pathlib import Path

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


def load_botuserkey(interactive: bool = True) -> str:
    return _loader("BOT_USER_KEY", "Enter the bot user key in the crawlbook crawlbook: ", interactive)


def load_botgroupkey(interactive: bool = True) -> str:
    return _loader("BOT_GROUP_KEY", "Enter the bot group key in the crawlbook crawlbook: ", interactive)
