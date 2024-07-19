#!/bin/python3

import argparse
import logging
import platform
import os
import yaml
import sys
import distro
import getpass
import fnmatch
import subprocess
from pydantic import BaseModel
from pydantic_core import to_jsonable_python
from pathlib import Path
from typing import Optional


import colorlog
import inotify.adapters
import inotify.constants

CONFIG_PATH = Path(
    os.getenv("2WSYNC_CONFIG_PATH", os.getenv("HOME") + "/.config/2wsync/config.yml")
)
LOG_PATH = Path(
    os.getenv(
        "2WSYNC_LOG_PATH", os.getenv("HOME") + "/.local/share/2wsync/log/2wsync.log"
    )
)


class ItemConfig(BaseModel):
    src: Path
    dest: Optional[Path] = None
    enabled: bool = True


class Config(BaseModel):
    default_src: Optional[Path] = Path(os.getenv("HOME")) / "workspace"
    default_dest: Optional[Path] = Path(
        f"/mnt/c/Users/{getpass.getuser()}/OneDrive/workspace"
    )
    items: list[ItemConfig] = []
    exclude: list[str] = ["node_modules"]


config: Optional[Config] = None

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False):
    # 设置日志记录级别
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    SUCCESS = 25
    logging.addLevelName(SUCCESS, "SUCCESS")

    def success(self, message, *args, **kws):
        if self.isEnabledFor(SUCCESS):
            self._log(SUCCESS, message, args, **kws)

    logging.Logger.success = success

    console_handler = colorlog.StreamHandler()
    console_formatter = colorlog.ColoredFormatter(
        fmt="[\033[01m%(log_color)s%(levelname)s\033[00m] \033[100m%(asctime)s\033[00m: %(message)s",
        log_colors={
            "SUCCESS": "green",
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold_red",
        },
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)


def setup_file_logging():
    file_handler = logging.FileHandler(LOG_PATH)
    file_formatter = logging.Formatter("[%(levelname)s] %(asctime)s: %(message)s")
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)


def install_requirements():
    logger.info("Installing required packages...")

    if platform.system() != "Linux":
        logger.error("Unsupported system: %s", platform.system())
        return

    dist = distro.name()
    logger.debug("Detected distribution: %s", dist)

    if "ubuntu" in dist.lower() or "debian" in dist.lower():
        os.system("sudo apt install -y inotify-tools unison")

    elif "arch" in dist.lower():
        os.system("sudo pacman -S --noconfirm inotify-tools unison ")

    elif "fedora" in dist.lower():
        os.system("sudo dnf install -y inotify-tools unison")

    elif "centos" in dist.lower() or "redhat" in dist.lower():
        os.system("sudo yum install -y inotify-tools unison")

    else:
        logger.error("Unsupported distribution: %s", dist)
        return

    logger.success("Packages installed successfully")


def check_requirements():
    try:
        # inotifywait can't be checked like unison
        # subprocess.run(
        #     ["inotifywait"],
        #     stdout=subprocess.PIPE,
        #     stderr=subprocess.PIPE,
        #     check=True,
        # )

        subprocess.run(
            ["unison", "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        logger.info("Required packages are installed.")
        return True
    except subprocess.CalledProcessError:
        return False
    except FileNotFoundError:
        return False


def getConfig():
    global config
    if config is None:
        if not CONFIG_PATH.exists():
            logger.error(
                f"Config file not found. Run '{sys.argv[0]} init' to create one."
            )
            return

        with open(CONFIG_PATH, "r") as f:
            data = yaml.safe_load(f)
            config = Config.model_validate(data)
    return config


def init(**kwargs):
    # check if required packages are installed
    logger.info("Checking required packages...")
    if not check_requirements():
        install_requirements()

    # create config file
    config = Config()
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r") as f:
            data = yaml.safe_load(f)
            if data:
                logger.warning("Config file already exists, importing it...")
                config = Config.model_validate(data)

    default_src = input(
        f"[\033[01m\033[34m+\033[00m] Enter the source directory [{config.default_src}]: "
    )
    if default_src:
        config.default_src = Path(default_src)
    default_dest = input(
        f"[\033[01m\033[34m+\033[00m] Enter the destination directory [{config.default_dest}]: "
    )
    if default_dest:
        config.default_dest = Path(default_dest)

    with open(CONFIG_PATH, "w") as f:
        yaml.dump(to_jsonable_python(config.model_dump()), f)


def status(**kwargs):
    if not CONFIG_PATH.exists():
        logger.error(f"Config file not found. Run '{sys.argv[0]} init' to create one.")
        return

    with open(CONFIG_PATH, "r") as f:
        data = yaml.safe_load(f)
        config = Config.model_validate(data)

    print(
        "\033[01m\033[100mDefault Synchronizer\033[00m \033[01m\033[35m%s\033[00m -> \033[01m\033[34m%s\033[00m"
        % (config.default_src.absolute(), config.default_dest.absolute())
    )
    print()

    for item in config.items:
        print(
            "\033[01m\033[35m%s\033[00m"
            % (item.src if item.src.is_absolute() else config.default_src / item.src)
        )
        if not item.dest:
            dest = config.default_dest / item.src
        else:
            dest = (
                item.dest
                if item.dest.is_absolute()
                else config.default_dest / item.dest
            )
        print("\t\033[01mDestination\033[00m \033[01m\033[34m%s\033[00m" % dest)
        print(
            "\t\033[01mStatus\033[00m %s"
            % (
                "\033[32mEnabled\033[00m"
                if item.enabled
                else "\033[31mDisabled\033[00m"
            )
        )

    real_sync_list, exclude_files = get_sync_list()
    print()
    print("\033[01m\033[100mSync List\033[00m")
    for src, dest in real_sync_list.items():
        print("\033[01m\033[35m%s\033[00m -> \033[01m\033[34m%s\033[00m" % (src, dest))
    print()
    print("\033[01m\033[100mExcluded Files\033[00m")
    for file in exclude_files:
        print("\033[01m\033[31m%s\033[00m" % file)


def get_sync_list() -> tuple[dict[Path, Path], set[Path]]:
    if not CONFIG_PATH.exists():
        logger.error(f"Config file not found. Run '{sys.argv[0]} init' to create one.")
        return []

    config = getConfig()

    sync_list = map(
        lambda x: (x, config.default_dest / x.relative_to(config.default_src)),
        config.default_src.iterdir(),
    )
    sync_list = dict(sync_list)
    # sync_list[config.default_src] = config.default_dest

    exclude_files = set()
    for item in config.items:
        if not item.enabled:
            exclude_files.add(
                item.src if item.src.is_absolute() else config.default_src / item.src
            )
        if not item.src.is_absolute():
            src = config.default_src / item.src
            if item.enabled:
                if item.dest:
                    sync_list[src] = item.dest
                else:
                    p = src
                    t = ""
                    while p not in sync_list and p != Path("/"):
                        t = p.name + "/" + t
                        p = p.parent

                    if p == Path("/"):
                        sync_list[src] = config.default_dest / item.src
                    else:
                        sync_list[src] = sync_list[p] / t
            else:
                sync_list.pop(src, None)

        elif item.enabled:
            sync_list[item.src] = item.dest
    sync_list = sync_list.items()
    for pattern in config.exclude:
        sync_list = filter(lambda x: not fnmatch.fnmatch(x[0].name, pattern), sync_list)
    return dict(sync_list), exclude_files


def add_watch(
    i: inotify.adapters.Inotify,
    src: Path,
    sync_list: dict[Path, Path],
    exclude_files: list[Path],
    exclude_pattern: list[str],
) -> bool:
    if str(src) in i._Inotify__watches:
        return False
    if not src.exists():
        logger.warning(
            "Source directory \033[01m\033[35m%s\033[00m does not exist", src
        )
        return False
    if not src.is_dir():
        return False
    if src in exclude_files:
        logger.debug("Excluding \033[01m\033[31m%s\033[00m", src)
        return False
    for pattern in exclude_pattern:
        if fnmatch.fnmatch(str(src.name), pattern):
            logger.debug("Excluding \033[01m\033[31m%s\033[00m", src)
            return False

    logger.debug("Adding watch for \033[01m\033[35m%s\033[00m", src)
    i.add_watch(
        str(src),
        mask=inotify.constants.IN_CREATE
        | inotify.constants.IN_DELETE
        | inotify.constants.IN_MODIFY
        | inotify.constants.IN_ATTRIB,
    )
    for f in src.glob("*"):
        add_watch(i, f, sync_list, exclude_files, exclude_pattern)
    return True


def call_unison(
    src: Path,
    sync_list: dict[Path, Path],
    dry_run: bool = False,
    ignore: list[str] = [],
    ignorenot: list[str] = [],
    exclude_pattern: list[str] = [],
):
    p = src
    t = ""
    while p not in sync_list and p != Path("/"):
        t = p.name + "/" + t
        p = p.parent
        print(t, p)
    if p == Path("/"):
        logger.error("Source directory not found in sync list.")
        return

    dest = sync_list[p] / t
    ignores = []
    ignorenots = []
    for x in ignore + exclude_pattern:
        ignores.extend(["-ignore", f"Path {x}"])

    for x in ignorenot:
        ignorenots.extend(["-ignorenot", f"Path {x}"])

    if not dest.exists():
        dest.mkdir(parents=True, exist_ok=True)

    cmd = [
        "unison",
        "-auto",
        "-batch",
        "-silent",
        "-confirmbigdel=false",
        *ignorenots,
        *ignores,
        str(src),
        str(dest),
    ]

    if dry_run:
        logger.info("Running \033[01m\033[34m%s\033[00m", " ".join(cmd))
    else:
        logger.debug("Running \033[01m\033[34m%s\033[00m", " ".join(cmd))
        try:
            subprocess.run(cmd, check=True)
            logger.success("Synchronization successful")
        except subprocess.CalledProcessError as e:
            logger.error("Synchronization failed")
            logger.debug(e)


def start(dry_run: bool = False, **kwargs):
    if not CONFIG_PATH.exists():
        logger.error(f"Config file not found. Run '{sys.argv[0]} init' to create one.")
        return

    sync_list, exclude_files = get_sync_list()
    config = getConfig()
    exclude_pattern = config.exclude + [".unison*"]
    default_src = config.default_src

    if not sync_list:
        logger.error("No directories to sync.")
        return

    logger.info("Starting synchronization...")
    logger.debug("Sync list: %s", sync_list)

    i = inotify.adapters.Inotify()
    for f in sync_list.keys():
        add_watch(i, f, sync_list, exclude_files, exclude_pattern)

    try:
        for event in i.event_gen(yield_nones=False):
            logger.debug(event)
            (_, types, path, filename) = event
            path = Path(path)
            final_path = path / filename

            if "IN_CREATE" in types and "IN_ISDIR" in types:
                add_watch(i, final_path, sync_list, exclude_files, exclude_pattern)
            if "IN_DELETE" in types and "IN_ISDIR" in types:
                if str(final_path) in sync_list:
                    i.remove_watch(str(final_path))

            if final_path in exclude_files or any(
                filter(
                    lambda x: fnmatch.fnmatch(str(final_path.name), x), exclude_pattern
                )
            ):
                if final_path not in sync_list:
                    logger.debug(
                        "Ignoring change in \033[01m\033[31m%s\033[00m", final_path
                    )
                    continue

            if path == default_src:
                continue
            logger.debug("Detected change in \033[01m\033[35m%s\033[00m", final_path)

            ignore = map(
                lambda x: x.relative_to(path),
                filter(lambda x: x.is_relative_to(path), exclude_files),
            )
            ignorenot = map(
                lambda x: x.relative_to(path),
                filter(
                    lambda x: x.is_relative_to(path) and x != path, sync_list.keys()
                ),
            )

            call_unison(
                path,
                sync_list,
                dry_run,
                list(ignore),
                list(ignorenot),
                exclude_pattern,
            )

    except KeyboardInterrupt:
        logger.info("Stopping synchronization...")


def main():
    global LOG_PATH
    if not CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not LOG_PATH.exists():
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    parser = argparse.ArgumentParser(
        description="two-way sync tool between wsl2 and OneDrive"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Increase output verbosity to DEBUG level.",
    )
    parser.add_argument(
        "-l",
        "--log",
        action="store",
        help="Log output to file.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True, metavar="command")

    parser_start = subparsers.add_parser(
        "start", help="Start the synchronization process"
    )
    parser_start.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        help="Print the unison command instead of running",
    )
    parser_start.set_defaults(func=start)

    parser_status = subparsers.add_parser(
        "status", help="Check the synchronization status"
    )
    parser_status.set_defaults(func=status)

    parser_status = subparsers.add_parser(
        "init", help="Install required packages and initialize the configuration file"
    )
    parser_status.set_defaults(func=init)

    args = parser.parse_args()

    setup_logging(args.verbose)
    if platform.system() != "Linux":
        logger.error("Unsupported system: %s", platform.system())
        return
    if args.log:
        LOG_PATH = Path(args.log)
        setup_file_logging()
    args.func(**vars(args))


if __name__ == "__main__":
    main()
