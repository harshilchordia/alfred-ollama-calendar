#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Background worker for calendar event creation.
Spawned by calendar_dispatch.py. Calls Ollama, creates the event,
and sends a macOS notification with the result.
"""

import sys
import os
import subprocess
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from typing import Dict, List


OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "gemma4"


def notify(title: str, message: str, sound: str = "Blow"):
    """Send a macOS notification"""
    script = f'''
    display notification "{message}" with title "{title}" sound name "{sound}"
    '''
    subprocess.run(['osascript', '-e', script], capture_output=True)


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


def get_available_calendars() -> List[str]:
    script = '''
    tell application "Calendar"
        set calList to {}
        repeat with calItem in calendars
            try
                if writable of calItem then
                    copy (name of calItem as string) to the end of calList
                end if
            end try
        end repeat
        return calList
    end tell
    '''
    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True, text=True, check=True
        )
        calendars = [cal.strip() for cal in result.stdout.strip().split(',')]
        return calendars if calendars and calendars[0] else ["Calendar"]
    except subprocess.CalledProcessError:
        return ["Calendar"]


def query_ollama(prompt: str, model: str = None) -> str:
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


def build_parse_prompt(user_input: str, calendars: List[str], default_calendar: str) -> str:
    now = datetime.now()
    current_date = now.strftime("%A, %B %d, %Y")
    current_time = now.strftime("%H:%M")

    return f"""You are a calendar event parser. Extract structured event details from natural language input.

Current date and time: {current_date} {current_time}

Available calendars: {', '.join(calendars)}
Default calendar: {default_calendar}

Parse the following input into a JSON object with these fields:
- "title": The event title/name (required)
- "calendar": Which calendar to use (use default if not specified; user specifies with # prefix like #Work)
- "start_date": Start date in YYYY-MM-DD format (required)
- "start_time": Start time in HH:MM:SS 24-hour format (required)
- "end_date": End date in YYYY-MM-DD format (required)
- "end_time": End time in HH:MM:SS 24-hour format (required)
- "location": Location if mentioned (optional, omit if not present)
- "url": URL if mentioned (optional, omit if not present)
- "notes": Notes/description if mentioned (optional, omit if not present)
- "alerts": Array of alert times in minutes before event (default [15] if not specified)
- "recurrence": iCal RRULE string if recurring (optional, omit if not recurring)

Rules:
- If no date is specified, use today's date
- If no time is specified, use the next full hour from now
- If no duration is specified, default to 60 minutes
- "tomorrow" means {(now + timedelta(days=1)).strftime("%Y-%m-%d")}
- "next week" means {(now + timedelta(days=7)).strftime("%Y-%m-%d")}
- Interpret shorthands: tmrw=tomorrow, mtg=meeting, apt=appointment, wfh=work from home
- For "every Monday" type events, set the start date to the next occurrence of that day

Respond with ONLY the JSON object, no explanation or markdown formatting.

Input: {user_input}"""


def parse_ollama_response(response: str) -> Dict:
    import re
    text = response.strip()

    # Strip markdown code fences
    if "```" in text:
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            text = match.group(1).strip()
    elif not text.startswith("{"):
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            text = match.group(0)

    event = json.loads(text)

    required = ['title', 'start_date', 'start_time', 'end_date', 'end_time']
    for field in required:
        if field not in event:
            raise ValueError(f"Missing required field: {field}")

    if 'alerts' not in event or not isinstance(event['alerts'], list):
        event['alerts'] = [15]
    else:
        event['alerts'] = [int(a) for a in event['alerts']]

    if 'calendar' not in event:
        event['calendar'] = "Calendar"

    return event


def create_calendar_event(event_details: Dict) -> str:
    start_date = datetime.strptime(
        f"{event_details['start_date']} {event_details['start_time']}",
        "%Y-%m-%d %H:%M:%S"
    )
    end_date = datetime.strptime(
        f"{event_details['end_date']} {event_details['end_time']}",
        "%Y-%m-%d %H:%M:%S"
    )

    calendar_name = event_details["calendar"].replace('"', '\\"')
    title = event_details["title"].replace('"', '\\"')

    script = f'''
        tell application "Calendar"
            tell calendar "{calendar_name}"
                set eventStartDate to current date
                set year of eventStartDate to {start_date.year}
                set month of eventStartDate to {start_date.month}
                set day of eventStartDate to {start_date.day}
                set hours of eventStartDate to {start_date.hour}
                set minutes of eventStartDate to {start_date.minute}
                set seconds of eventStartDate to 0

                set eventEndDate to current date
                set year of eventEndDate to {end_date.year}
                set month of eventEndDate to {end_date.month}
                set day of eventEndDate to {end_date.day}
                set hours of eventEndDate to {end_date.hour}
                set minutes of eventEndDate to {end_date.minute}
                set seconds of eventEndDate to 0

                make new event with properties {{summary:"{title}", start date:eventStartDate, end date:eventEndDate}}
                set newEvent to result
    '''

    if event_details.get('location'):
        location = event_details['location'].replace('"', '\\"')
        script += f'\n                set location of newEvent to "{location}"'

    if event_details.get('url'):
        url = event_details['url'].replace('"', '\\"')
        script += f'\n                set url of newEvent to "{url}"'

    if event_details.get('notes'):
        notes = event_details['notes'].replace('"', '\\"')
        script += f'\n                set description of newEvent to "{notes}"'

    if event_details.get('recurrence'):
        recurrence = event_details['recurrence'].replace('"', '\\"')
        script += f'\n                set recurrence of newEvent to "{recurrence}"'

    for minutes in event_details.get('alerts', [15]):
        alert_time = start_date - timedelta(minutes=int(minutes))
        script += f'''
                set alertDate to current date
                set year of alertDate to {alert_time.year}
                set month of alertDate to {alert_time.month}
                set day of alertDate to {alert_time.day}
                set hours of alertDate to {alert_time.hour}
                set minutes of alertDate to {alert_time.minute}
                set seconds of alertDate to 0
                make new display alarm at newEvent with properties {{trigger date:alertDate}}
        '''

    script += '''
                return newEvent
            end tell
        end tell
    '''

    result = subprocess.run(
        ['osascript', '-e', script],
        capture_output=True, text=True, check=True
    )

    if result.stderr:
        raise Exception(result.stderr)

    return title


def main():
    if len(sys.argv) < 2:
        return

    user_input = " ".join(sys.argv[1:])

    try:
        config = load_config()
        calendars = get_available_calendars()
        default_calendar = config.get('default_calendar', 'Calendar')

        # Parse with Ollama
        prompt = build_parse_prompt(user_input, calendars, default_calendar)
        response = query_ollama(prompt)
        event_details = parse_ollama_response(response)

        # Validate calendar
        if event_details['calendar'] not in calendars:
            matched = [c for c in calendars if c.lower() == event_details['calendar'].lower()]
            event_details['calendar'] = matched[0] if matched else default_calendar

        # Create the event
        title = create_calendar_event(event_details)

        # Format notification
        start_date = datetime.strptime(
            f"{event_details['start_date']} {event_details['start_time']}",
            "%Y-%m-%d %H:%M:%S"
        )
        end_date = datetime.strptime(
            f"{event_details['end_date']} {event_details['end_time']}",
            "%Y-%m-%d %H:%M:%S"
        )
        time_str = f"{start_date.strftime('%-I:%M %p')} – {end_date.strftime('%-I:%M %p')}"
        today = datetime.now()
        tomorrow = today + timedelta(days=1)

        if start_date.date() == today.date():
            date_str = f"Today at {time_str}"
        elif start_date.date() == tomorrow.date():
            date_str = f"Tomorrow at {time_str}"
        else:
            date_str = start_date.strftime("%A, %B %-d at ") + time_str

        msg = f"{event_details['calendar']} • {date_str}"
        if event_details.get('location'):
            msg += f" • {event_details['location']}"

        notify(f"✅ {title}", msg)

    except (urllib.error.URLError, ConnectionRefusedError, OSError):
        notify("❌ Calendar Error", "Ollama is not running. Start Ollama and try again.", "Basso")
    except Exception as e:
        error_msg = str(e)[:80].replace('"', "'")
        notify("❌ Calendar Error", error_msg, "Basso")


if __name__ == "__main__":
    main()
