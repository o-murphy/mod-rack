import json

# Path to your file
INPUT_JSON = "plugins.json"
OUTPUT_TOML = "plugins_output.toml"


def generate_toml():
    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        plugins_data = json.load(f)

    # Use set for uniqueness by URI
    seen_uris = set()
    output = []

    output.append(
        "# ============================================================================="
    )
    output.append("# Plugins (Generated from plugins.json)")
    output.append(
        "# =============================================================================\n"
    )

    # Dict for grouping by categories for nice output
    categories = {}

    for plugin in plugins_data:
        uri = plugin.get("uri")
        if not uri or uri in seen_uris:
            continue

        seen_uris.add(uri)

        name = plugin.get("name", "Unknown")
        # Take first category from list or set 'utility'
        cat_list = plugin.get("category", [])
        category = cat_list[0].lower() if cat_list else "utility"

        if category not in categories:
            categories[category] = []

        categories[category].append({"name": name, "uri": uri, "category": category})

    # Sort categories for order
    sorted_cats = sorted(categories.keys())

    for cat in sorted_cats:
        output.append(f"# --- {cat.capitalize()} ---")
        for p in categories[cat]:
            output.append("[[plugins]]")
            output.append(f'name = "{p["name"]}"')
            output.append(f'uri = "{p["uri"]}"')
            output.append(f'category = "{p["category"]}"')
            output.append("")  # empty line between plugins

    with open(OUTPUT_TOML, "w", encoding="utf-8") as f:
        f.write("\n".join(output))

    print(f"Done! Generated {len(seen_uris)} plugins in file {OUTPUT_TOML}")


if __name__ == "__main__":
    generate_toml()
