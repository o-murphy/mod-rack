from mod_rack.schema.config import Config


if __name__ == "__main__":
    c = Config.load("src/mod_rack/config_example.toml")
    print(c)