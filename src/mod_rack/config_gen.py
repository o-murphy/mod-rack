import argparse
from pathlib import Path
from pprint import pprint
from mod_rack.client import Client

try:
    import tomllib
except ImportError:
    import tomli as tomllib

header_fmt = """###########################
# --- MOD RACK CONFIG --- #
###########################

[server]
url = "{url}"

[hardware]
# disable_ports = ["capture_1"] #, "capture_2"]
# All-to-all routing: connect all hardware inputs to all first plugin inputs
# join_audio_inputs = true
# All-to-all routing: connect all last plugin outputs to all hardware outputs
# join_audio_outputs = true

[rack]
routing_mode = "hard_bypass"  # one of [hard_bypass, linear, dual_track], default=hard_bypass


###############################
# --- MOD Desktop Plugins --- #
###############################

"""

plugin_fmt = """[[plugins]]
name="{name}"
brand="{brand}"
uri="{uri}"
category="{category}"
# disable_ports = []
# join_audio_inputs = false
# join_audio_outputs = false

"""


class Args(argparse.Namespace):
    server: str
    output: Path
    no_fix: bool
    allow_all: bool


def _is_supported(plugin_data):
    # TODO
    return True


def _apply_fix(plugin_data):
    # TODO
    return plugin_data


def main():
    parser = argparse.ArgumentParser("mod-rack config")
    parser.add_argument(
        "-s", "--server", metavar="URL", type=str, help="Server url", action="store"
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="PATH",
        type=Path,
        help="Output path",
        action="store",
        default="config.toml",
    )
    parser.add_argument(
        "--no-fix",
        help="Do not apply known fixes",
        action="store_true",
    )
    parser.add_argument(
        "--allow-all",
        help="Allow untested or unsupported plugins",
        action="store_true",
    )

    try:
        ns: Args = parser.parse_args()
        client = Client(ns.server)

        plugins_list = client.effect_list()

        pprint(len(plugins_list))

        plugins = []

        plugins.append(header_fmt.format(url=client.base_url))

        for plugin in plugins_list:
            if not ns.allow_all and not _is_supported(plugin):
                continue

            if not ns.no_fix:
                plugin = _apply_fix(plugin)

            info = plugin_fmt.format(
                uri=plugin["uri"],
                name=plugin["name"],
                brand=plugin["brand"],
                category=plugin["category"],
            )

            plugins.append(info)

        if ns.output.exists():
            if ns.output.is_dir():
                out = ns.output / "config.toml"
            else:
                out = ns.output
        else:
            out = ns.output

        out = out.with_suffix(".toml")
        with open(out, "w") as fp:
            fp.writelines(plugins)

        parser.exit(0, f"Config saved to '{out}'\n")

    except Exception as err:
        parser.error(str(err))

    parser.exit(0)


if __name__ == "__main__":
    main()
