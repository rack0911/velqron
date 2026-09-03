import os
import re
import sys


def update_noise_floor(new_val):
    config_path = "src/core/config.py"
    if not os.path.exists(config_path):
        print(f"Error: {config_path} not found.")
        return False

    with open(config_path, "r") as f:
        content = f.read()

    # Regex to find NOISE_FLOOR line
    pattern = r'("NOISE_FLOOR":\s*)[\d\.]+'
    if not re.search(pattern, content):
        print("Error: NOISE_FLOOR key not found in config.py")
        return False

    new_content = re.sub(pattern, rf"\1{new_val:.3f}", content)

    with open(config_path, "w") as f:
        f.write(new_content)

    print(f"Successfully updated NOISE_FLOOR to {new_val:.3f} in config.py")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/update_config_baseline.py <value>")
        sys.exit(1)

    try:
        val = float(sys.argv[1])
        update_noise_floor(val)
    except ValueError:
        print("Invalid number provided.")
