from pathlib import Path
import yaml

def load_policy_from_skill(skill_path: str) -> dict:
    text = Path(skill_path).read_text(encoding="utf-8")
    # Extract first YAML fenced block ```yaml ... ```
    start = text.find("```yaml")
    if start == -1:
        raise ValueError("No ```yaml block found in policy skill.")
    end = text.find("```", start + 6)
    if end == -1:
        raise ValueError("YAML block not closed.")
    yaml_text = text[start+6:end]
    return yaml.safe_load(yaml_text)
