#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import json
import socket
import base64
import subprocess
import tempfile
import urllib.request
import urllib.error
from datetime import datetime
from typing import Dict, Optional


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


def get_clipboard_image() -> Optional[str]:
    """Get image from macOS clipboard as base64 string. Returns None if no image."""
    tmp_path = os.path.join(tempfile.gettempdir(), 'alfred_cal_clipboard.png')

    # Use AppleScript to save clipboard image to a temp file
    script = f'''
    try
        set imgData to the clipboard as «class PNGf»
        set filePath to POSIX file "{tmp_path}"
        set fileRef to open for access filePath with write permission
        set eof of fileRef to 0
        write imgData to fileRef
        close access fileRef
        return "ok"
    on error
        try
            close access filePath
        end try
        return "no_image"
    end try
    '''

    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True, text=True, timeout=5
        )
        if result.stdout.strip() != "ok":
            return None

        with open(tmp_path, 'rb') as f:
            img_data = f.read()

        if len(img_data) < 100:  # Too small to be a real image
            return None

        return base64.b64encode(img_data).decode('utf-8')
    except (subprocess.TimeoutExpired, FileNotFoundError, IOError):
        return None
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def query_ollama_vision(image_b64: str, prompt: str) -> str:
    """Send an image + prompt to Ollama and return the response"""
    config = load_config()
    model = config.get('ollama_model', DEFAULT_MODEL)

    payload = json.dumps({
        "model": model,
        "messages": [{
            "role": "user",
            "content": prompt,
            "images": [image_b64]
        }],
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 1024
        }
    }).encode('utf-8')

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"}
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode('utf-8'))
        return result.get("message", {}).get("content", "")


def build_vision_prompt(default_calendar: str) -> str:
    """Build prompt for extracting calendar event from an image"""
    now = datetime.now()
    return f"""Look at this image and extract calendar event information from it.
Current date: {now.strftime("%Y-%m-%d %A")} Current time: {now.strftime("%H:%M")}
Default calendar: {default_calendar}

The image might be a screenshot of an email, a flyer, an invitation, a poster, a text message, or any visual with event details.

Extract and return ONLY a JSON object with these fields:
- "title": event name/title (string, required)
- "calendar": which calendar to add it to (string, use default calendar above)
- "date_display": human-friendly date/time (e.g. "Jun 12, 2026 at 5:00 PM")
- "start_date": ISO format date if found (e.g. "2026-06-12")
- "start_time": 24h time if found (e.g. "17:00")
- "end_time": 24h end time if found (e.g. "18:00"), or null
- "location": venue/address if mentioned, or null
- "notes": any extra details worth noting, or null
- "url": any URL/link found, or null

If you cannot identify any event in the image, return: {{"title": null, "error": "No event found in image"}}

Return ONLY the JSON object, no markdown formatting."""


def extract_json(text: str) -> Dict:
    """Extract JSON object from model response"""
    import re
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    if "```" in text:
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

    # Try finding JSON object in text
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError("Could not extract JSON from response")


def format_alfred_items(event: Dict) -> Dict:
    """Format extracted event into Alfred script filter output"""
    if event.get("title") is None:
        return {
            "items": [{
                "title": "No event found in image",
                "subtitle": "⚠️ Could not identify calendar event details in the clipboard image",
                "valid": False,
                "icon": {"path": "icon.png"}
            }]
        }

    title = event.get("title", "New Event")
    calendar = event.get("calendar") or "Calendar"
    date_display = event.get("date_display", "")
    location = event.get("location")
    notes = event.get("notes")
    url = event.get("url")

    subtitle_parts = [f"📅 {calendar}"]
    if date_display:
        subtitle_parts.append(date_display)
    if location:
        subtitle_parts.append(f"📍 {location}")
    subtitle = " • ".join(subtitle_parts)

    # Build the arg string for calendar_nlp.py to process
    arg_parts = [title]
    if event.get("start_date"):
        arg_parts.append(event["start_date"])
    if event.get("start_time"):
        arg_parts.append(event["start_time"])
    if event.get("end_time"):
        arg_parts.append(f"to {event['end_time']}")
    if location:
        arg_parts.append(f"at {location}")
    if notes:
        arg_parts.append(f"notes: {notes}")
    if url:
        arg_parts.append(f"url: {url}")
    arg = " ".join(arg_parts)

    items = [{
        "title": title,
        "subtitle": subtitle,
        "arg": arg,
        "valid": True,
        "icon": {"path": "icon.png"}
    }]

    # Add a second item showing extra details if available
    detail_parts = []
    if notes:
        detail_parts.append(f"📝 {notes}")
    if url:
        detail_parts.append(f"🔗 {url}")
    if detail_parts:
        items.append({
            "title": " | ".join(detail_parts),
            "subtitle": "Additional details extracted from image",
            "valid": False,
            "icon": {"path": "icon.png"}
        })

    return {"items": items}


def main():
    # Check clipboard for image
    image_b64 = get_clipboard_image()

    if not image_b64:
        print(json.dumps({
            "items": [{
                "title": "No image on clipboard",
                "subtitle": "📷 Copy or screenshot an event image first (Cmd+Shift+4), then trigger this command",
                "valid": False,
                "icon": {"path": "icon.png"}
            }]
        }))
        return

    try:
        config = load_config()
        default_calendar = config.get('default_calendar', 'Calendar')
        prompt = build_vision_prompt(default_calendar)

        response = query_ollama_vision(image_b64, prompt)
        event = extract_json(response)
        output = format_alfred_items(event)
        print(json.dumps(output))

    except socket.timeout:
        print(json.dumps({
            "items": [{
                "title": "⏳ Still processing image...",
                "subtitle": "Ollama is analyzing the image. This may take a moment for large images.",
                "valid": False,
                "icon": {"path": "icon.png"}
            }]
        }))
    except (urllib.error.URLError, ConnectionRefusedError, OSError) as e:
        if "Connection refused" in str(e) or "URLError" in type(e).__name__:
            print(json.dumps({
                "items": [{
                    "title": "⚠️ Ollama not running",
                    "subtitle": "Start Ollama to enable image recognition. https://ollama.ai",
                    "valid": False,
                    "icon": {"path": "icon.png"}
                }]
            }))
        else:
            raise
    except Exception as e:
        print(json.dumps({
            "items": [{
                "title": "Error processing image",
                "subtitle": f"⚠️ {str(e)[:80]}",
                "valid": False,
                "icon": {"path": "icon.png"}
            }]
        }))


if __name__ == "__main__":
    main()
