import argparse
from pathlib import Path
from pprint import pprint
from mod_rack.client import Client

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
allow_all_plugins = true

###############################
# --- MOD Desktop Plugins --- #
###############################

"""

plugin_fmt = """[[plugin]]
name="{name}"
brand="{brand}"
uri="{uri}"
category="{category}"
# disable_ports = []
# join_audio_inputs = true
# join_audio_outputs = false

"""


class Args(argparse.Namespace):
    server: str
    output: Path


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

    try:
        ns: Args = parser.parse_args()
        client = Client(ns.server)

        data = client.effect_list()

        pprint(len(data))

        plugins = []

        plugins.append(header_fmt.format(url=client.base_url))

        for item in data:
            info = plugin_fmt.format(
                uri=item["uri"],
                name=item["name"],
                brand=item["brand"],
                category=item["category"],
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
