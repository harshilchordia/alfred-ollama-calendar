#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import json
import subprocess
import os
import re
import logging

def get_workflow_data_dir():
    """Get Alfred workflow data directory, create if it doesn't exist"""
    data_dir = os.getenv('alfred_workflow_data')
    if not data_dir:
        data_dir = os.path.expanduser('~/Library/Application Support/Alfred/Workflow Data/com.ariestwn.calendar.nlp')
    
    # Create directory if it doesn't exist
    os.makedirs(data_dir, exist_ok=True)
    return data_dir

# Setup logging in Alfred's data directory
data_dir = get_workflow_data_dir()
log_file = os.path.join(data_dir, 'calendar_profile.log')
logging.basicConfig(
    filename=log_file,
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class CalendarProfileManager:
    def __init__(self):
        self.calendars = self.get_available_calendars()
        data_dir = get_workflow_data_dir()
        self.config_file = os.path.join(data_dir, 'calendar_config.json')
        self.config = {}  # Initialize config as empty dictionary
        self.load_config()  # Call load_config to fill self.config
        logging.debug(f"Calendars: {self.calendars}")
        logging.debug(f"Config: {self.config}")

    def sort_calendars(self, calendars):
        """Sort calendars with numbers and alphabetically"""
        def sort_key(name):
            parts = re.split(r'(\d+)', name)
            parts = [int(part) if part.isdigit() else part.lower() for part in parts]
            return parts
        
        return sorted(calendars, key=sort_key)

    def get_available_calendars(self):
        """Get list of available and writable calendars"""
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
            result = subprocess.run(['osascript', '-e', script],
                                  capture_output=True,
                                  text=True,
                                  check=True)
            calendars = [cal.strip() for cal in result.stdout.strip().split(',')]
            return self.sort_calendars(calendars)
        except subprocess.CalledProcessError as e:
            logging.error(f"Error running AppleScript: {e}")
            print(f"Error running AppleScript: {e}", file=sys.stderr)
            return ["Calendar"]
        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            print(f"Unexpected error: {e}", file=sys.stderr)
            return ["Calendar"]

    def load_config(self):
        """Load configuration from file"""
        logging.debug("Loading configuration")
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    self.config = json.load(f)
                    if self.config.get('default_calendar') not in self.calendars:
                        self.config['default_calendar'] = self.calendars[0] if self.calendars else 'Calendar'
                logging.debug(f"Configuration loaded: {self.config}")
            except json.JSONDecodeError:
                logging.error("Corrupted config file. Creating new configuration.")
                print("Error: Corrupted config file. Creating new configuration.")
                self.create_default_config()
            except Exception as e:
                logging.error(f"Failed to load configuration: {str(e)}")
                print(f"Error: Failed to load configuration: {str(e)}")
                self.create_default_config()
        else:
            logging.debug("Config file not found. Creating new configuration.")
            self.create_default_config()

    def create_default_config(self):
        """Create default configuration"""
        self.config = {
            "default_calendar": self.calendars[0] if self.calendars else 'Calendar',
            "ollama_model": "gemma4"
        }
        self.save_config(self.config['default_calendar'])

    def save_config(self, calendar_name):
        """Save configuration to file, preserving existing settings"""
        if calendar_name in self.calendars:
            try:
                # Preserve existing config keys (like ollama_model)
                self.config["default_calendar"] = calendar_name
                if "ollama_model" not in self.config:
                    self.config["ollama_model"] = "gemma4"

                with open(self.config_file, 'w') as f:
                    json.dump(self.config, f, indent=2)
                return True
            except Exception as e:
                print(f"Error: Failed to save configuration: {str(e)}")
        return False

    def generate_items(self, query=None):
        """Generate Alfred items"""
        items = []
        query_lower = query.lower() if query else ""
        default_cal = self.config.get('default_calendar', '')
        
        # Filter calendars
        matching_calendars = [
            cal for cal in self.calendars 
            if not query_lower or query_lower in cal.lower()
        ]
        
        # Move default to top
        if default_cal in matching_calendars:
            matching_calendars.remove(default_cal)
            items.append({
                "title": f"✓ {default_cal}",
                "subtitle": "Current default calendar",
                "valid": False,
                "icon": {
                    "path": "icon.png"
                }
            })
        
        # Add other calendars
        for cal in matching_calendars:
            items.append({
                "title": cal,
                "subtitle": "Press Enter to set as default calendar",
                "arg": f"--set:{cal}",
                "valid": True,
                "icon": {
                    "path": "icon.png"
                }
            })
        
        return items

def main():
    logging.debug("Starting program")
    manager = CalendarProfileManager()
    
    if len(sys.argv) > 1:
        arg = " ".join(sys.argv[1:])
        logging.debug(f"Received argument: {arg}")
        if arg.startswith("--set:"):
            # Remove all occurrences of "--set:" from argument
            calendar_name = arg.replace("--set:", "").strip()
            logging.debug(f"Attempting to set calendar: {calendar_name}")
            if calendar_name in manager.calendars:
                if manager.save_config(calendar_name):
                    output = json.dumps({
                        "alfredworkflow": {
                            "arg": f"📅 {calendar_name}",
                            "variables": {
                                "calendar": calendar_name,
                                "notificationTitle": "Default Calendar Set"
                            }
                        }
                    })
                    logging.debug(f"Output: {output}")
                    print(output)
                else:
                    output = json.dumps({
                        "alfredworkflow": {
                            "arg": f"Failed to set calendar '{calendar_name}'",
                            "variables": {
                                "error": "true",
                                "notificationTitle": "Error"
                            }
                        }
                    })
                    logging.error(f"Failed to set calendar: {calendar_name}")
                    print(output)
            else:
                output = json.dumps({
                    "alfredworkflow": {
                        "arg": f"Calendar '{calendar_name}' not found",
                        "variables": {
                            "error": "true",
                            "notificationTitle": "Error"
                        }
                    }
                })
                logging.error(f"Calendar not found: {calendar_name}")
                print(output)
        else:
            # Show filtered list
            items = manager.generate_items(arg)
            output = json.dumps({"items": items})
            logging.debug(f"Output: {output}")
            print(output)
    else:
        # Show all calendars
        items = manager.generate_items()
        output = json.dumps({"items": items})
        logging.debug(f"Output: {output}")
        print(output)

if __name__ == "__main__":
    main()