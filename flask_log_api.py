"""
Flask REST API for Log File Data Access and Analysis

Usage:
    1) Install requirements:
        pip install Flask python-dotenv

    2) Set environment variable LOG_DIR to the path containing log files, or edit default LOG_DIR below.
       Example log files should have lines formatted as:
         2025-05-07 10:00:00\tINFO\tUserAuth\tUser 'john.doe' logged in successfully.

    3) Run the app:
        python flask_log_api.py

    4) Endpoints:
        GET /logs
            Optional query params: level, component, start_time, end_time, page, per_page
            Time format for start_time & end_time: YYYY-MM-DD HH:MM:SS

        GET /logs/stats
            Returns total count and counts per level and per component.

        GET /logs/<log_id>
            Returns full log entry for given id (404 if not found).

Notes:
 - This implementation reads and parses all logs on startup into memory. For very large datasets consider
   streaming, a database, or an indexed format. Pagination is supported via page & per_page.
 - Unique IDs are generated deterministically as SHA1(file_path + ':' + line_no + ':' + timestamp + ':' + level + ':' + component).

"""

import os
import hashlib
from flask import Flask, jsonify, request, abort
from datetime import datetime
from collections import Counter, defaultdict
from typing import List, Dict, Any, Optional

# Configuration
LOG_DIR = os.environ.get('LOG_DIR', './logs')  # change as needed
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 500

app = Flask(__name__)


class LogEntry:
    def __init__(self, id_: str, timestamp: datetime, level: str, component: str, message: str, file: str, line_no: int):
        self.id = id_
        self.timestamp = timestamp
        self.level = level
        self.component = component
        self.message = message
        self.file = file
        self.line_no = line_no

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'timestamp': self.timestamp.strftime(TIMESTAMP_FORMAT),
            'level': self.level,
            'component': self.component,
            'message': self.message,
            'file': self.file,
            'line_no': self.line_no,
        }


class LogManager:
    def __init__(self, log_dir: str):
        self.log_dir = log_dir
        self.entries: List[LogEntry] = []
        self.index_by_id: Dict[str, LogEntry] = {}

    def load_logs(self):
        """Scan log_dir for files and parse them into memory."""
        entries = []
        if not os.path.isdir(self.log_dir):
            app.logger.warning(f"Log directory '{self.log_dir}' not found or not a directory.")
            self.entries = []
            self.index_by_id = {}
            return

        for root, dirs, files in os.walk(self.log_dir):
            for fname in sorted(files):
                path = os.path.join(root, fname)
                try:
                    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                        for i, line in enumerate(fh, start=1):
                            line = line.strip()
                            if not line:
                                continue
                            parsed = self.parse_line(line)
                            if parsed is None:
                                # skip malformed line but log it
                                app.logger.debug(f"Skipping malformed line {i} in {path}: {line}")
                                continue
                            timestamp, level, component, message = parsed
                            id_ = self.generate_id(path, i, timestamp, level, component)
                            entry = LogEntry(id_, timestamp, level, component, message, path, i)
                            entries.append(entry)
                except Exception as e:
                    app.logger.error(f"Failed to read file {path}: {e}")

        # sort entries by timestamp (ascending)
        entries.sort(key=lambda e: e.timestamp)
        self.entries = entries
        self.index_by_id = {e.id: e for e in entries}
        app.logger.info(f"Loaded {len(self.entries)} log entries from {self.log_dir}")

    @staticmethod
    def parse_line(line: str) -> Optional[tuple]:
        """Parse a single log line. Returns (timestamp: datetime, level, component, message) or None if malformed."""
        # Expecting tab-separated fields: Timestamp\tLevel\tComponent\tMessage
        parts = line.split('\t', 3)
        if len(parts) < 4:
            return None
        ts_str, level, component, message = parts
        try:
            timestamp = datetime.strptime(ts_str.strip(), TIMESTAMP_FORMAT)
        except ValueError:
            return None
        return timestamp, level.strip(), component.strip(), message.strip()

    @staticmethod
    def generate_id(file_path: str, line_no: int, timestamp: datetime, level: str, component: str) -> str:
        base = f"{file_path}:{line_no}:{timestamp.strftime(TIMESTAMP_FORMAT)}:{level}:{component}"
        return hashlib.sha1(base.encode('utf-8')).hexdigest()

    def filter_entries(self, level: Optional[str] = None, component: Optional[str] = None,
                       start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> List[LogEntry]:
        result = self.entries
        if level:
            result = [e for e in result if e.level.lower() == level.lower()]
        if component:
            result = [e for e in result if e.component.lower() == component.lower()]
        if start_time:
            result = [e for e in result if e.timestamp >= start_time]
        if end_time:
            result = [e for e in result if e.timestamp <= end_time]
        return result

    def stats(self) -> Dict[str, Any]:
        total = len(self.entries)
        levels = Counter(e.level for e in self.entries)
        components = Counter(e.component for e in self.entries)
        return {
            'total': total,
            'by_level': dict(levels),
            'by_component': dict(components)
        }


log_manager = LogManager(LOG_DIR)
log_manager.load_logs()


def parse_query_time(param: Optional[str]) -> Optional[datetime]:
    if not param:
        return None
    try:
        return datetime.strptime(param, TIMESTAMP_FORMAT)
    except ValueError:
        abort(400, description=f"Invalid time format for '{param}'. Expected: {TIMESTAMP_FORMAT}")


@app.route('/logs', methods=['GET'])
def get_logs():
    """Return logs with optional filters and pagination."""
    level = request.args.get('level')
    component = request.args.get('component')
    start_time = parse_query_time(request.args.get('start_time'))
    end_time = parse_query_time(request.args.get('end_time'))

    page = request.args.get('page', default='1')
    per_page = request.args.get('per_page', default=str(DEFAULT_PER_PAGE))
    try:
        page = int(page)
        per_page = int(per_page)
    except ValueError:
        abort(400, description='page and per_page must be integers')
    if page < 1:
        abort(400, description='page must be >= 1')

    if per_page < 1 or per_page > MAX_PER_PAGE:
        abort(400, description=f'per_page must be between 1 and {MAX_PER_PAGE}')

    filtered = log_manager.filter_entries(level=level, component=component, start_time=start_time, end_time=end_time)
    total = len(filtered)

    # pagination
    start = (page - 1) * per_page
    end = start + per_page
    page_entries = filtered[start:end]

    response = {
        'total': total,
        'page': page,
        'per_page': per_page,
        'entries': [e.to_dict() for e in page_entries]
    }
    return jsonify(response)


@app.route('/logs/stats', methods=['GET'])
def get_stats():
    return jsonify(log_manager.stats())


@app.route('/logs/<log_id>', methods=['GET'])
def get_log_by_id(log_id: str):
    entry = log_manager.index_by_id.get(log_id)
    if not entry:
        abort(404, description='Log entry not found')
    return jsonify(entry.to_dict())


@app.errorhandler(400)
def bad_request(e):
    return jsonify({'error': 'bad_request', 'message': e.description}), 400


@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'not_found', 'message': e.description}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'server_error', 'message': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
