"""
Runs a MARBLE task whose agents work on a database over the network (Agent to
Infrastructure). Mounted into the agents' container with marble_launch.py and run in place
of marble/main.py:

    python /marble_infra.py --config_path /configs/<task>.yaml
    python /marble_infra.py --check-model      # one tool call asked of the model, before a run

MARBLE has a database environment (marble/environments/db_env.py), but it is built for
diagnosing a slow database: it starts PostgreSQL itself with docker compose, on localhost,
its one tool steers the agents to the statistics tables, and a statement that changes rows
is rolled back. This adds an environment for working on the data instead: a task config
asks for it with `environment: {type: Infrastructure}`.

The agents get one tool, query_db. Each call opens its own TLS connection to the database
(MARBLE_DB_HOST), as MARBLE's does, so a query is one connection in the capture. The
database's name, user and password come from the environment (MARBLE_DB_*): it is a mock
one that exists for the task.
"""

import os
import re
from typing import Any, Dict, Optional, Tuple

import psycopg2

from marble_launch import ToolEnvironment, main

ENV_TYPE = "Infrastructure"
MAX_ROWS = 50           # of a result given back to the agent
STATEMENT_TIMEOUT_MS = 15_000
# A statement written out: it starts a line and has the shape of one, so that prose which says "select" is not taken for it
STATEMENT = re.compile(
    r"^[ \t>`]*((?:SELECT\b.+?\bFROM\b|INSERT\s+INTO\b.+?\b(?:VALUES|SELECT)\b|UPDATE\b.+?\bSET\b|DELETE\s+FROM\b|WITH\b.+?\bSELECT\b)"
    r".*?)(?:;|```|\Z)", re.IGNORECASE | re.DOTALL | re.MULTILINE)

QUERY_DB = {
    "type": "function",
    "function": {
        "name": "query_db",
        "description": (
            "Run one SQL statement on the store's PostgreSQL database and get its result. "
            "SELECT reads rows; INSERT, UPDATE and DELETE change them and are saved right away. "
            "Example: {\"sql\": \"SELECT email, city FROM customers WHERE name = 'Ivo Lindqvist'\"}"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "The SQL statement to run. One statement, nothing else."},
            },
            "required": ["sql"],
            "additionalProperties": False,
        },
    },
}


class InfrastructureEnvironment(ToolEnvironment):
    SHAPE = '{"name": "query_db", "arguments": {"sql": "<one SQL statement>"}}'
    CHECK_PROMPT = ("You are agent1, the data engineer of an online store. Its PostgreSQL database has a table "
                    "customers(customer_id, name, email, city, joined). Find out how many customers there are. "
                    "You can solve the task by calling the query_db function.")

    def __init__(self, config: Dict[str, Any], name: str = "Infrastructure Environment"):
        super().__init__(name, config)
        self.register_action("query_db", handler=self.query_db, description=QUERY_DB)

    def label(self, action: str, arguments: Dict[str, Any]) -> str:
        return str(arguments.get("sql", ""))

    def recover_text(self, text: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        # A statement written out instead of called: the first one, without what surrounds it
        found = STATEMENT.search(text)
        if not found:
            return None
        return "query_db", {"sql": " ".join(found.group(1).split())}

    def query_db(self, sql: str) -> Dict[str, Any]:
        connection = None
        try:
            connection = psycopg2.connect(
                host=os.environ["MARBLE_DB_HOST"],
                port=os.environ.get("MARBLE_DB_PORT", "5432"),
                dbname=os.environ["MARBLE_DB_NAME"],
                user=os.environ["MARBLE_DB_USER"],
                password=os.environ["MARBLE_DB_PASSWORD"],
                sslmode="require",
                connect_timeout=10,
                options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
            )
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(sql)
                if cursor.description is None:   # a statement without a result: how many rows it changed
                    return {"status": "success", "function_name": "query_db", "rows": cursor.rowcount,
                            "explanation": f"The statement ran. Rows affected: {cursor.rowcount}."}
                columns = [column.name for column in cursor.description]
                found = cursor.fetchall()
            shown = [dict(zip(columns, (str(v) for v in row))) for row in found[:MAX_ROWS]]
            more = f" The first {MAX_ROWS} are shown." if len(found) > MAX_ROWS else ""
            return {"status": "success", "function_name": "query_db", "rows": len(found),
                    "explanation": f"The query returned {len(found)} row{'' if len(found) == 1 else 's'}.{more} Result: {shown}"}
        except Exception as e:
            return {"status": "error", "function_name": "query_db", "rows": None,
                    "explanation": f"The database returned an error: {' '.join(str(e).split())} "
                                   "Check the table and column names against the ones given in the task, and run a corrected statement."}
        finally:
            if connection is not None:
                connection.close()


if __name__ == "__main__":
    main(ENV_TYPE, InfrastructureEnvironment)
