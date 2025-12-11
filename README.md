# flask_log_apis
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


