#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import urllib.request
import urllib.error


OLLAMA_URL = "http://localhost:11434/api/tags"
DEFAULT_MODEL = "gemma4"


def get_workflow_data_dir():
    """Get Alfred workflow data directory"""
    data_dir = os.getenv('alfred_workflow_data')
    if not data_dir:
        data_dir = os.path.expanduser(
            '~/Library/Application Support/Alfred/Workflow Data/com.ariestwn.calendar.nlp'
        )
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def check_ollama_running():
    """Check if Ollama is running and accessible"""
    try:
        req = urllib.request.Request(OLLAMA_URL)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            models = [m.get('name', '') for m in data.get('models', [])]
            return True, models
    except urllib.error.URLError:
        return False, []
    except Exception:
        return False, []


def ensure_config():
    """Ensure configuration file exists with defaults"""
    data_dir = get_workflow_data_dir()
    config_file = os.path.join(data_dir, 'calendar_config.json')

    if not os.path.exists(config_file):
        config = {
            "default_calendar": "Calendar",
            "ollama_model": DEFAULT_MODEL
        }
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
        return config
    else:
        with open(config_file, 'r') as f:
            config = json.load(f)
        # Ensure ollama_model key exists
        if 'ollama_model' not in config:
            config['ollama_model'] = DEFAULT_MODEL
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)
        return config


def setup_workflow():
    """Verify Ollama is set up and ready"""
    # Ensure config exists
    config = ensure_config()
    model = config.get('ollama_model', DEFAULT_MODEL)

    # Check Ollama is running
    running, available_models = check_ollama_running()

    if not running:
        print("ERROR: Ollama is not running.", file=sys.stderr)
        print("Please install and start Ollama: https://ollama.ai", file=sys.stderr)
        return False

    # Check if the configured model is available
    model_available = any(model in m for m in available_models)

    if not model_available:
        print(f"Model '{model}' not found. Pulling it now...", file=sys.stderr)
        # Try to pull the model via ollama CLI
        import subprocess
        try:
            subprocess.run(
                ['ollama', 'pull', model],
                check=True,
                stdout=sys.stderr,
                stderr=sys.stderr
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            print(f"Failed to pull model '{model}'. Please run: ollama pull {model}",
                  file=sys.stderr)
            return False

    return True


def main():
    success = setup_workflow()
    if success:
        print("Setup complete. Ollama is ready.", file=sys.stderr)
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
