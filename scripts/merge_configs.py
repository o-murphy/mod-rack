# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "tomlkit",
# ]
# ///

import json
import os
from tomlkit import parse, table, aot


def merge_json_to_toml(json_path, toml_path):
    try:
        if not os.path.exists(toml_path):
            print(f"Error: {toml_path} not found!")
            return

        # 1. Read existing config
        with open(toml_path, "r", encoding="utf-8") as f:
            content = f.read()
            config = parse(content)

        # 2. Read JSON
        with open(json_path, "r", encoding="utf-8") as f:
            json_plugins = json.load(f)

        # Check for or create [[plugins]] section
        if "plugins" not in config:
            # Create Array of Tables
            config.add("plugins", aot())

        # Get existing URIs to check for duplicates
        # tomlkit objects behave like dicts/lists
        existing_uris = set()
        for p in config.get("plugins", []):
            if "uri" in p:
                existing_uris.add(p["uri"])

        new_plugins_count = 0

        # 3. Add new plugins
        plugins_aot = config["plugins"]

        for jp in json_plugins:
            uri = jp.get("uri")
            if uri and uri not in existing_uris:
                cat_list = jp.get("category", [])

                # Create new table for plugin
                new_entry = table()
                new_entry.add("name", jp.get("name", "Unknown"))
                new_entry.add("uri", uri)
                new_entry.add(
                    "category", cat_list[0].lower() if cat_list else "utility"
                )

                # Add to array
                plugins_aot.append(new_entry)
                existing_uris.add(uri)
                new_plugins_count += 1

        # 4. Save (tomlkit preserves comments and header formatting)
        with open(toml_path, "w", encoding="utf-8") as f:
            f.write(config.as_string())

        print(f"Success! Added new plugins: {new_plugins_count}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    merge_json_to_toml("plugins.json", "config.toml")
