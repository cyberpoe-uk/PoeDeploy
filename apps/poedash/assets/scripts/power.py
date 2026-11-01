#!/usr/bin/env python3
"""Report system-battery information and valid OS remaining estimates."""
import json
from battery import reading

if __name__ == '__main__':
    print(json.dumps(reading()))
