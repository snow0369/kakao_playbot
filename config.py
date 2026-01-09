# config.py
import yaml
from pathlib import Path

CONFIG_FILE = Path("config.local.yaml")


def load_config(interactive=True) -> dict:
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        if "USER_NAME" not in cfg:
            raise KeyError("USER_NAME")

        return cfg

    except (FileNotFoundError, KeyError):
        if not interactive:
            raise

        user_name = input("Enter your username: ").strip()
        cfg = {"USER_NAME": user_name}

        with CONFIG_FILE.open("w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, sort_keys=False)

        return cfg
