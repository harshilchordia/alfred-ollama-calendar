#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Alfred Script Filter with async Ollama preview.
Uses Alfred's 'rerun' to poll for results without blocking.
1st call: spawns Ollama in background, shows "Thinking..."
2nd+ call: checks cache, shows parsed result when ready.
"""

import sys
import os
import re
import json
import hashlib
import subprocess
import time
from typing import Dict


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


def load_config() -> Dict:
    config_file = os.path.join(get_workflow_data_dir(), 'calendar_config.json')
    try:
        with open(config_file, 'r') as f:
            return json.load(f)
    except Exception:
        return {"default_calendar": "Calendar", "ollama_model": DEFAULT_MODEL}


def get_cache_dir():
    cache_dir = os.path.join(get_workflow_data_dir(), 'preview_cache')
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def cache_key(query: str) -> str:
    return hashlib.md5(query.encode()).hexdigest()


def get_cached_result(query: str) -> Dict:
    """Check if we have a cached Ollama result for this query"""
    path = os.path.join(get_cache_dir(), cache_key(query) + '.json')
    if os.path.exists(path):
        # Only use cache if fresh (< 30 seconds old)
        if time.time() - os.path.getmtime(path) < 30:
            try:
                with open(path, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
    return None


def is_worker_running(query: str) -> bool:
    """Check if a background worker is already processing this query"""
    lock_path = os.path.join(get_cache_dir(), cache_key(query) + '.lock')
    if os.path.exists(lock_path):
        # Consider stale if older than 60s
        if time.time() - os.path.getmtime(lock_path) < 60:
            return True
        else:
            os.unlink(lock_path)
    return False


def spawn_preview_worker(query: str, default_calendar: str):
    """Spawn background process to call Ollama and write result to cache"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    worker = os.path.join(script_dir, 'preview_worker.py')

    subprocess.Popen(
        [sys.executable, worker, query, default_calendar],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        cwd=script_dir
    )


def cleanup_old_cache():
    """Remove cache files older than 60 seconds"""
    cache_dir = get_cache_dir()
    now = time.time()
    try:
        for f in os.listdir(cache_dir):
            path = os.path.join(cache_dir, f)
            if now - os.path.getmtime(path) > 60:
                os.unlink(path)
    except OSError:
        pass


def main():
    if len(sys.argv) < 2:
        print(json.dumps({
            "items": [{
                "title": "Type event details...",
                "subtitle": "Natural language → calendar event (powered by Ollama)",
                "valid": False,
                "icon": {"path": "icon.png"}
            }]
        }))
        return

    query = " ".join(sys.argv[1:])

    if len(query.strip()) < 3:
        print(json.dumps({
            "items": [{
                "title": query,
                "subtitle": "Keep typing...",
                "valid": False,
                "icon": {"path": "icon.png"}
            }]
        }))
        return

    config = load_config()
    default_calendar = config.get('default_calendar', 'Calendar')

    # Check if we already have a result
    cached = get_cached_result(query)
    if cached:
        title = cached.get("title") or "New Event"
        calendar = cached.get("calendar") or default_calendar
        date_display = cached.get("date_display", "")
        location = cached.get("location")

        subtitle_parts = [f"📅 {calendar}"]
        if date_display:
            subtitle_parts.append(date_display)
        if location:
            subtitle_parts.append(f"📍 {location}")
        subtitle = " • ".join(subtitle_parts)

        print(json.dumps({
            "items": [{
                "title": title,
                "subtitle": subtitle,
                "arg": query,
                "valid": True,
                "icon": {"path": "icon.png"}
            }]
        }))
        return

    # No cached result yet — spawn worker if not already running
    if not is_worker_running(query):
        spawn_preview_worker(query, default_calendar)
        cleanup_old_cache()

    # Return "thinking" result with rerun to auto-refresh
    print(json.dumps({
        "rerun": 0.5,
        "items": [{
            "title": query,
            "subtitle": "🧠 Ollama is parsing... (press ↵ to create now)",
            "arg": query,
            "valid": True,
            "icon": {"path": "icon.png"}
        }]
    }))


if __name__ == "__main__":
    main()
