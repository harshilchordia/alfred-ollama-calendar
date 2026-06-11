#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import json
import socket
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from typing import Optional, List, Dict


OLLAMA_URL = "http://localhost:11434/api/chat"
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


def load_config() -> Dict:
    """Load calendar configuration"""
    config_file = os.path.join(get_workflow_data_dir(), 'calendar_config.json')
    try:
        with open(config_file, 'r') as f:
            return json.load(f)
    except Exception:
        return {"default_calendar": "Calendar", "ollama_model": DEFAULT_MODEL}


def query_ollama(prompt: str, model: str = None) -> str:
    """Send a prompt to Ollama and return the response text"""
    if not model:
        config = load_config()
        model = config.get('ollama_model', DEFAULT_MODEL)

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 512
        }
    }).encode('utf-8')

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode('utf-8'))
        return result.get("message", {}).get("content", "")


def build_preview_prompt(user_input: str, default_calendar: str) -> str:
    """Build a concise prompt for quick event preview"""
    now = datetime.now()
    return f"""Parse this calendar event input into JSON. Current date: {now.strftime("%Y-%m-%d %A")} Time: {now.strftime("%H:%M")}
Default calendar: {default_calendar}

Rules:
- If no event title is given, set title to "New Event"
- If no calendar specified with # prefix, use the default calendar above
- date_display should be human-friendly (e.g. "Jun 12, 2026 at 5:00 PM")

Return ONLY a JSON object with these keys: "title" (string), "calendar" (string), "date_display" (string), "location" (string or null).

Input: {user_input}"""


def format_preview(event: Dict) -> List[Dict]:
    """Format parsed event into Alfred script filter items"""
    title = event.get("title") or "New Event"
    calendar = event.get("calendar") or "Calendar"
    date_display = event.get("date_display", "")
    location = event.get("location")

    subtitle_parts = [f"📅 {calendar}"]
    if date_display:
        subtitle_parts.append(date_display)
    if location:
        subtitle_parts.append(f"📍 {location}")

    subtitle = " • ".join(subtitle_parts)

    return [{
        "title": title or "Type event details...",
        "subtitle": subtitle,
        "arg": " ".join(sys.argv[1:]),
        "valid": bool(title),
        "icon": {"path": "icon.png"}
    }]


def main():
    if len(sys.argv) < 2:
        print(json.dumps({
            "items": [{
                "title": "Type event details...",
                "subtitle": "Use natural language to describe your event (powered by Ollama)",
                "valid": False,
                "icon": {"path": "icon.png"}
            }]
        }))
        return

    query = " ".join(sys.argv[1:])

    # Don't call Ollama for very short input
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

    try:
        config = load_config()
        default_calendar = config.get('default_calendar', 'Calendar')
        prompt = build_preview_prompt(query, default_calendar)
        response = query_ollama(prompt)

        # Parse the response - extract JSON even if wrapped in markdown
        text = response.strip()
        if "```" in text:
            import re
            match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
            if match:
                text = match.group(0)
        elif not text.startswith("{"):
            # Try to find JSON object in the response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                text = text[start:end]

        event = json.loads(text)
        items = format_preview(event)
        print(json.dumps({"items": items}))

    except socket.timeout:
        # Model is processing - takes time for larger models
        print(json.dumps({
            "items": [{
                "title": query,
                "subtitle": "⏳ Ollama is thinking... (press Enter to create anyway)",
                "arg": query,
                "valid": True,
                "icon": {"path": "icon.png"}
            }]
        }))
    except (urllib.error.URLError, ConnectionRefusedError, OSError):
        # Ollama not running - show helpful message
        print(json.dumps({
            "items": [{
                "title": query,
                "subtitle": "⚠️ Ollama not running. Start Ollama to enable AI parsing.",
                "valid": False,
                "icon": {"path": "icon.png"}
            }]
        }))
    except (json.JSONDecodeError, KeyError, ValueError):
        # Parsing failed - show raw input as fallback
        print(json.dumps({
            "items": [{
                "title": query,
                "subtitle": "⏳ Processing with Ollama...",
                "arg": query,
                "valid": True,
                "icon": {"path": "icon.png"}
            }]
        }))
    except Exception:
        print(json.dumps({
            "items": [{
                "title": query,
                "subtitle": "Press Enter to create event",
                "arg": query,
                "valid": True,
                "icon": {"path": "icon.png"}
            }]
        }))


if __name__ == "__main__":
    main()
