#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Background preview worker. Spawned by preview.py.
Calls Ollama to parse the event and writes result to cache file.
preview.py polls for the cached result via Alfred's rerun.
"""

import sys
import os
import json
import hashlib
import urllib.request
import urllib.error
from datetime import datetime


OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "gemma4"


def get_workflow_data_dir():
    data_dir = os.getenv('alfred_workflow_data')
    if not data_dir:
        data_dir = os.path.expanduser(
            '~/Library/Application Support/Alfred/Workflow Data/com.ariestwn.calendar.nlp'
        )
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def get_cache_dir():
    cache_dir = os.path.join(get_workflow_data_dir(), 'preview_cache')
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def cache_key(query: str) -> str:
    return hashlib.md5(query.encode()).hexdigest()


def load_config():
    config_file = os.path.join(get_workflow_data_dir(), 'calendar_config.json')
    try:
        with open(config_file, 'r') as f:
            return json.load(f)
    except Exception:
        return {"default_calendar": "Calendar", "ollama_model": DEFAULT_MODEL}


def main():
    if len(sys.argv) < 3:
        return

    query = sys.argv[1]
    default_calendar = sys.argv[2]

    key = cache_key(query)
    cache_dir = get_cache_dir()
    lock_path = os.path.join(cache_dir, key + '.lock')
    result_path = os.path.join(cache_dir, key + '.json')

    # Write lock file
    with open(lock_path, 'w') as f:
        f.write(str(os.getpid()))

    try:
        config = load_config()
        model = config.get('ollama_model', DEFAULT_MODEL)

        now = datetime.now()
        prompt = f"""Parse this calendar event input into JSON. Current date: {now.strftime("%Y-%m-%d %A")} Time: {now.strftime("%H:%M")}
Default calendar: {default_calendar}

Rules:
- If no event title is given, set title to "New Event"
- If no calendar specified with # prefix, use the default calendar above
- date_display should be human-friendly (e.g. "Tomorrow at 5:00 PM – 6:00 PM")
- location: extract location if mentioned, else null

Return ONLY a JSON object with: "title" (string), "calendar" (string), "date_display" (string), "location" (string or null).

Input: {query}"""

        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 256
            }
        }).encode('utf-8')

        req = urllib.request.Request(
            OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"}
        )

        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            content = result.get("message", {}).get("content", "")

        # Extract JSON from response
        text = content.strip()
        if "```" in text:
            import re
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                text = match.group(0)
        elif not text.startswith("{"):
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                text = text[start:end]

        event = json.loads(text)

        # Write result to cache
        with open(result_path, 'w') as f:
            json.dump(event, f)

    except Exception:
        # On failure, write a minimal fallback so preview stops polling
        with open(result_path, 'w') as f:
            json.dump({
                "title": query,
                "calendar": default_calendar,
                "date_display": "",
                "location": None
            }, f)
    finally:
        # Remove lock
        try:
            os.unlink(lock_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
