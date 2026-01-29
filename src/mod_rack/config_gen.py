import argparse
from pathlib import Path
from mod_rack.client import Client

try:
    import tomllib
except ImportError:
    import tomli as tomllib

base_path = Path(__file__).parent


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
name = "{name}"
brand = "{brand}"
uri = "{uri}"
category = {category}
disable_ports = {disable_ports}
join_audio_inputs = {join_audio_inputs}
join_audio_outputs = {join_audio_outputs}

"""


class Args(argparse.Namespace):
    server: str
    output: Path
    no_fix: bool
    allow_all: bool


class _KnownPlugins:
    PATH = base_path / "plugins.toml"

    def __init__(self):
        with open(self.PATH, "rb") as fp:
            data = tomllib.load(fp)
            self.known: dict[str, dict] = {
                item["uri"]: item for item in data["plugins"]
            }

    def is_supported(self, plugin_info: dict):
        if plugin_info["uri"] in self.known:
            return True
        return False

    def apply_fix(self, plugin_info: dict):
        if plugin_info["uri"] in self.known:
            plugin_info.update(self.known[plugin_info["uri"]])
            plugin_info["join_audio_inputs"] = str(plugin_info["join_audio_inputs"]).lower() 
            plugin_info["join_audio_outputs"] = str(plugin_info["join_audio_outputs"]).lower() 
        return plugin_info


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
        known = _KnownPlugins()

        ns: Args = parser.parse_args()
        client = Client(ns.server)

        plugins_list = client.effect_list()

        print("Fetched:", len(plugins_list))

        parts = []
        parts.append(header_fmt.format(url=client.base_url))

        plugins = []

        for plugin in plugins_list:
            info_dict = {
                "uri": plugin["uri"],
                "name": plugin["name"],
                "brand": plugin["brand"],
                "category": plugin["category"],
                "disable_ports": [],
                "join_audio_inputs": "false",
                "join_audio_outputs": "false",
            }

            if not ns.allow_all and not known.is_supported(info_dict):
                continue

            if not ns.no_fix:
                info_dict = known.apply_fix(info_dict)
            print(info_dict)
            info = plugin_fmt.format(**info_dict).replace("'", '"')
            plugins.append(info)

        if ns.output.exists():
            if ns.output.is_dir():
                out = ns.output / "config.toml"
            else:
                out = ns.output
        else:
            out = ns.output

        parts.extend(plugins)

        print("Parsed:", len(plugins))
        out = out.with_suffix(".toml")
        with open(out, "w") as fp:
            fp.writelines(parts)

        parser.exit(0, f"Config saved to '{out}'\n")

    except Exception as err:
        # parser.error(str(err))
        raise

    parser.exit(0)


if __name__ == "__main__":
    main()
