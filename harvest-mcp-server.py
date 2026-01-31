import os
import json
import httpx
from datetime import datetime, date
from calendar import monthrange
from mcp.server.fastmcp import FastMCP


def get_finnish_public_holidays(year: int) -> list[date]:
    """Get Finnish public holidays for a given year."""
    from datetime import timedelta

    # Fixed holidays
    holidays = [
        date(year, 1, 1),   # New Year's Day
        date(year, 1, 6),   # Epiphany
        date(year, 5, 1),   # May Day
        date(year, 6, 20) if date(year, 6, 20).weekday() == 4 else
            date(year, 6, 20) + timedelta(days=(4 - date(year, 6, 20).weekday()) % 7),  # Midsummer Eve (Friday)
        date(year, 12, 6),  # Independence Day
        date(year, 12, 24), # Christmas Eve
        date(year, 12, 25), # Christmas Day
        date(year, 12, 26), # Boxing Day
    ]

    # Easter-based holidays (calculate Easter Sunday)
    # Using Anonymous Gregorian algorithm
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    easter = date(year, month, day)

    holidays.extend([
        easter - timedelta(days=2),   # Good Friday
        easter,                        # Easter Sunday
        easter + timedelta(days=1),    # Easter Monday
        easter + timedelta(days=39),   # Ascension Day
    ])

    return holidays


def count_working_days(year: int, month: int) -> int:
    """Count working days in a month (weekdays minus public holidays)."""
    holidays = get_finnish_public_holidays(year)
    _, days_in_month = monthrange(year, month)

    working_days = 0
    for day in range(1, days_in_month + 1):
        d = date(year, month, day)
        # Weekday (0=Mon, 6=Sun) and not a holiday
        if d.weekday() < 5 and d not in holidays:
            working_days += 1

    return working_days

# Initialize FastMCP server
mcp = FastMCP("harvest-api")

# Get environment variables for Harvest API
HARVEST_ACCOUNT_ID = os.environ.get("HARVEST_ACCOUNT_ID")
HARVEST_API_KEY = os.environ.get("HARVEST_API_KEY")

if not HARVEST_ACCOUNT_ID or not HARVEST_API_KEY:
    raise ValueError(
        "Missing Harvest API credentials. Set HARVEST_ACCOUNT_ID and HARVEST_API_KEY environment variables."
    )


# Helper function to make Harvest API requests
async def harvest_request(path, params=None, method="GET"):
    headers = {
        "Harvest-Account-Id": HARVEST_ACCOUNT_ID,
        "Authorization": f"Bearer {HARVEST_API_KEY}",
        "User-Agent": "Harvest MCP Server",
        "Content-Type": "application/json",
    }

    url = f"https://api.harvestapp.com/v2/{path}"

    async with httpx.AsyncClient() as client:
        if method == "GET":
            response = await client.get(url, headers=headers, params=params)
        else:
            response = await client.request(method, url, headers=headers, json=params)

        if response.status_code not in (200, 201):
            raise Exception(
                f"Harvest API Error: {response.status_code} {response.text}"
            )

        return response.json()


@mcp.tool()
async def list_users(is_active: bool = None, page: int = None, per_page: int = None):
    """List all users in your Harvest account.

    Args:
        is_active: Pass true to only return active users and false to return inactive users
        page: The page number for pagination
        per_page: The number of records to return per page (1-2000)
    """
    params = {}
    if is_active is not None:
        params["is_active"] = "true" if is_active else "false"
    else:
        params["is_active"] = "true"
    if page is not None:
        params["page"] = str(page)
    if per_page is not None:
        params["per_page"] = str(per_page)
    else:
        params["per_page"] = 200

    response = await harvest_request("users", params)
    return json.dumps(response, indent=2)


@mcp.tool()
async def get_user_details(user_id: int):
    """Retrieve details for a specific user.

    Args:
        user_id: The ID of the user to retrieve
    """
    response = await harvest_request(f"users/{user_id}")
    return json.dumps(response, indent=2)


@mcp.tool()
async def list_time_entries(
    user_id: int = None,
    from_date: str = None,
    to_date: str = None,
    is_running: bool = None,
    is_billable: bool = None,
):
    """List time entries with optional filtering.

    Args:
        user_id: Filter by user ID
        from_date: Only return time entries with a spent_date on or after the given date (YYYY-MM-DD)
        to_date: Only return time entries with a spent_date on or before the given date (YYYY-MM-DD)
        is_running: Pass true to only return running time entries and false to return non-running time entries
        is_billable: Pass true to only return billable time entries and false to return non-billable time entries
    """
    params = {}
    if user_id is not None:
        params["user_id"] = str(user_id)
    if from_date is not None:
        params["from"] = from_date
    if to_date is not None:
        params["to"] = to_date
    if is_running is not None:
        params["is_running"] = "true" if is_running else "false"
    if is_billable is not None:
        params["is_billable"] = "true" if is_billable else "false"

    response = await harvest_request("time_entries", params)
    return json.dumps(response, indent=2)


@mcp.tool()
async def create_time_entry(
    project_id: int, task_id: int, spent_date: str, hours: float, notes: str = None
):
    """Create a new time entry.

    Args:
        project_id: The ID of the project to associate with the time entry
        task_id: The ID of the task to associate with the time entry
        spent_date: The date when the time was spent (YYYY-MM-DD)
        hours: The number of hours spent
        notes: Optional notes about the time entry
    """
    params = {
        "project_id": project_id,
        "task_id": task_id,
        "spent_date": spent_date,
        "hours": hours,
    }

    if notes:
        params["notes"] = notes

    response = await harvest_request("time_entries", params, method="POST")
    return json.dumps(response, indent=2)


@mcp.tool()
async def stop_timer(time_entry_id: int):
    """Stop a running timer.

    Args:
        time_entry_id: The ID of the running time entry to stop
    """
    response = await harvest_request(
        f"time_entries/{time_entry_id}/stop", method="PATCH"
    )
    return json.dumps(response, indent=2)


@mcp.tool()
async def start_timer(project_id: int, task_id: int, notes: str = None):
    """Start a new timer.

    Args:
        project_id: The ID of the project to associate with the time entry
        task_id: The ID of the task to associate with the time entry
        notes: Optional notes about the time entry
    """
    params = {
        "project_id": project_id,
        "task_id": task_id,
    }

    if notes:
        params["notes"] = notes

    response = await harvest_request("time_entries", params, method="POST")
    return json.dumps(response, indent=2)


@mcp.tool()
async def list_projects(client_id: int = None, is_active: bool = None):
    """List projects with optional filtering.

    Args:
        client_id: Filter by client ID
        is_active: Pass true to only return active projects and false to return inactive projects
    """
    params = {}
    if client_id is not None:
        params["client_id"] = str(client_id)
    if is_active is not None:
        params["is_active"] = "true" if is_active else "false"

    response = await harvest_request("projects", params)
    return json.dumps(response, indent=2)


@mcp.tool()
async def get_project_details(project_id: int):
    """Get detailed information about a specific project.

    Args:
        project_id: The ID of the project to retrieve
    """
    response = await harvest_request(f"projects/{project_id}")
    return json.dumps(response, indent=2)


@mcp.tool()
async def list_clients(is_active: bool = None):
    """List clients with optional filtering.

    Args:
        is_active: Pass true to only return active clients and false to return inactive clients
    """
    params = {}
    if is_active is not None:
        params["is_active"] = "true" if is_active else "false"

    response = await harvest_request("clients", params)
    return json.dumps(response, indent=2)


@mcp.tool()
async def get_client_details(client_id: int):
    """Get detailed information about a specific client.

    Args:
        client_id: The ID of the client to retrieve
    """
    response = await harvest_request(f"clients/{client_id}")
    return json.dumps(response, indent=2)


@mcp.tool()
async def list_tasks(is_active: bool = None):
    """List all tasks with optional filtering.

    Args:
        is_active: Pass true to only return active tasks and false to return inactive tasks
    """
    params = {}
    if is_active is not None:
        params["is_active"] = "true" if is_active else "false"

    response = await harvest_request("tasks", params)
    return json.dumps(response, indent=2)


@mcp.tool()
async def get_unsubmitted_timesheets(
    user_id: int = None,
    from_date: str = None,
    to_date: str = None,
    page: int = None,
    per_page: int = None,
):
    """Get unsubmitted timesheets (time entries that haven't been submitted for approval).
    
    This function queries for time entries that are not yet closed/submitted, which typically
    means they are still editable and haven't been submitted for approval or invoicing.

    Args:
        user_id: Filter by specific user ID (optional)
        from_date: Only return time entries with a spent_date on or after the given date (YYYY-MM-DD)
        to_date: Only return time entries with a spent_date on or before the given date (YYYY-MM-DD)
        page: The page number for pagination
        per_page: The number of records to return per page (1-2000)
    """
    params = {}
    if user_id is not None:
        params["user_id"] = str(user_id)
    if from_date is not None:
        params["from"] = from_date
    if to_date is not None:
        params["to"] = to_date
    if page is not None:
        params["page"] = str(page)
    if per_page is not None:
        params["per_page"] = str(per_page)
    else:
        params["per_page"] = "200"

    # Get all time entries first
    response = await harvest_request("time_entries", params)
    
    # Filter for unsubmitted entries (those that are not closed)
    unsubmitted_entries = []
    if "time_entries" in response:
        for entry in response["time_entries"]:
            # Time entries that are not closed are considered unsubmitted
            if not entry.get("is_closed", False):
                unsubmitted_entries.append(entry)
    
    # Create a response structure similar to the original API response
    filtered_response = {
        "time_entries": unsubmitted_entries,
        "per_page": response.get("per_page", len(unsubmitted_entries)),
        "total_pages": 1,  # Simplified since we're filtering client-side
        "total_entries": len(unsubmitted_entries),
        "next_page": None,
        "previous_page": None,
        "page": response.get("page", 1),
        "links": response.get("links", {})
    }
    
    return json.dumps(filtered_response, indent=2)


@mcp.tool()
async def get_monthly_work_percentage(
    year: int,
    month: int,
    hours_per_day: float = 7.5,
):
    """Calculate work percentage for a given month compared to full-time.

    Returns a summary with total hours, expected hours, and work percentage.
    Categorizes time entries into actual work, public holidays, absences, etc.

    Args:
        year: The year (e.g., 2025)
        month: The month (1-12)
        hours_per_day: Hours per working day (default 7.5 for Finland)
    """
    # Fetch time entries for the month
    from_date = f"{year}-{month:02d}-01"
    _, last_day = monthrange(year, month)
    to_date = f"{year}-{month:02d}-{last_day:02d}"

    params = {"from": from_date, "to": to_date, "per_page": "2000"}
    response = await harvest_request("time_entries", params)

    entries = response.get("time_entries", [])

    # Categorize entries based on task name
    absence_keywords = ["unpaid absence", "palkaton"]
    holiday_keywords = ["public holiday", "arkipyhä", "holiday"]
    leave_keywords = ["day-off", "flextime", "saldo", "vacation", "loma", "sick", "sairas"]

    total_hours = 0.0
    actual_work_hours = 0.0
    public_holiday_hours = 0.0
    paid_leave_hours = 0.0
    unpaid_absence_hours = 0.0

    by_client = {}
    by_category = {
        "actual_work": 0.0,
        "public_holiday": 0.0,
        "paid_leave": 0.0,
        "unpaid_absence": 0.0,
    }

    for entry in entries:
        hours = entry.get("hours", 0)
        task_name = entry.get("task", {}).get("name", "").lower()
        client_name = entry.get("client", {}).get("name", "Unknown")

        # Categorize (public holidays excluded from total since already in expected_hours)
        if any(kw in task_name for kw in holiday_keywords):
            public_holiday_hours += hours
            by_category["public_holiday"] += hours
        elif any(kw in task_name for kw in absence_keywords):
            unpaid_absence_hours += hours
            by_category["unpaid_absence"] += hours
        elif any(kw in task_name for kw in leave_keywords):
            total_hours += hours
            paid_leave_hours += hours
            by_category["paid_leave"] += hours
        else:
            total_hours += hours
            actual_work_hours += hours
            by_category["actual_work"] += hours

            # Track by client for actual work only
            if client_name not in by_client:
                by_client[client_name] = 0.0
            by_client[client_name] += hours

    # Calculate expected hours (reduced by unpaid absence)
    working_days = count_working_days(year, month)
    expected_hours = working_days * hours_per_day - unpaid_absence_hours

    # Calculate percentages
    work_percentage = (total_hours / expected_hours * 100) if expected_hours > 0 else 0

    result = {
        "period": f"{year}-{month:02d}",
        "working_days": working_days,
        "hours_per_day": hours_per_day,
        "expected_hours": expected_hours,
        "summary": {
            "total_logged_hours": round(total_hours, 2),
            "unpaid_absence_hours": round(unpaid_absence_hours, 2),
            "work_percentage": round(work_percentage, 1),
        },
        "breakdown": {
            "actual_work": round(actual_work_hours, 2),
            "public_holidays": round(public_holiday_hours, 2),
            "paid_leave": round(paid_leave_hours, 2),
            "unpaid_absence": round(unpaid_absence_hours, 2),
        },
        "by_client": {k: round(v, 2) for k, v in sorted(by_client.items(), key=lambda x: -x[1])},
    }

    return json.dumps(result, indent=2)


if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport="stdio")
